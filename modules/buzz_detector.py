import time
import requests
import json
import sys
import os

# Fix Path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

class BuzzDetector:
    def __init__(self, log_queue, signal_queue):
        self.log_queue = log_queue
        self.signal_queue = signal_queue
        self.base_url = config.INDODAX_API_URL
        self.history = {}
        
        self.MIN_VOL_CHANGE = getattr(config, 'BUZZ_MIN_VOL_CHANGE', 50_000_000)
        self.MIN_PRICE_CHANGE = getattr(config, 'BUZZ_MIN_PRICE_CHANGE', 0.5)
        self.SCAN_INTERVAL = getattr(config, 'BUZZ_SCAN_INTERVAL', 3)
        self.MIN_DAILY_VOL = getattr(config, 'BUZZ_MIN_DAILY_VOL', 500_000_000)
        self.STRATEGY_LABEL = getattr(config, 'SPECIAL_STRATEGY_LABEL', 'PUMP_CHASER')

        self.MAX_HISTORY_SECONDS = 300
        self.MIN_OBSERVATION_SECONDS = 60
        self.market_memory = {}
        self.cooldown_list = {}

    def get_ticker_all(self):
        # === MODE SIMULASI / GOD MODE ===
        mock_path = "mock_tickers.json"
        if os.path.exists(mock_path):
            try:
                with open(mock_path, "r") as f:
                    return json.load(f)['tickers']
            except Exception:
                return None
                
        # === MODE NORMAL (INTERNET) ===
        try:
            # Mengambil data seluruh market sekaligus 
            resp = requests.get(f"{self.base_url}/api/ticker_all", timeout=5).json()
            return resp['tickers']
        except Exception as e:
            return None

    def clean_history(self, current_time):
        """Menghapus data snapshot yang sudah kadaluarsa (> 5 menit)"""
        for pair in list(self.market_memory.keys()):
            # Filter hanya data yang usianya < MAX_HISTORY_SECONDS
            self.market_memory[pair] = [
                snap for snap in self.market_memory[pair] 
                if current_time - snap['ts'] <= self.MAX_HISTORY_SECONDS
            ]
            # Hapus key jika list kosong untuk hemat memori
            if not self.market_memory[pair]:
                del self.market_memory[pair]

        # Bersihkan Cooldown
        for pair in list(self.cooldown_list.keys()):
            if current_time > self.cooldown_list[pair]:
                del self.cooldown_list[pair]

    def detect_momentum(self):
        tickers = self.get_ticker_all()
        if not tickers: return

        current_time = time.time()
        
        # 1. Maintenance Memory
        self.clean_history(current_time)
        
        for pair_raw, data in tickers.items():
            if not pair_raw.endswith('_idr'): continue
            
            # Abaikan koin volume kecil (Ghost town) atau sedang cooldown
            if pair_raw in self.cooldown_list: continue
            
            try:
                vol_idr_now = float(data['vol_idr'])
                last_price = float(data['last'])
                buy_price = float(data['buy'])
                sell_price = float(data['sell'])
            except: continue

            if vol_idr_now < self.MIN_DAILY_VOL: continue
            
            # 2. Simpan Snapshot Data
            if pair_raw not in self.market_memory:
                self.market_memory[pair_raw] = []
            
            self.market_memory[pair_raw].append({
                'ts': current_time,
                'price': last_price,
                'vol': vol_idr_now
            })

            # 3. Analisa Momentum
            snapshots = self.market_memory[pair_raw]
            if len(snapshots) < 5: continue # Butuh minimal beberapa data point

            first_snap = snapshots[0]
            last_snap = snapshots[-1]
            
            time_delta = last_snap['ts'] - first_snap['ts']

            # Hanya analisa jika kita sudah memantau minimal 1 menit (60 detik)
            if time_delta < self.MIN_OBSERVATION_SECONDS: 
                continue

            # Hitung Perubahan
            price_change_pct = ((last_snap['price'] - first_snap['price']) / first_snap['price']) * 100
            vol_accumulated = last_snap['vol'] - first_snap['vol']
            
            # Logic: Apakah ini Pump & Dump?
            # Cek harga tertinggi dalam periode ini
            max_price_in_window = max(s['price'] for s in snapshots)
            
            # Syarat 1: Harga saat ini harus dekat dengan High (Konsisten naik)
            # Jika harga drop > 1% dari High, berarti momentum hilang (Pump & Dump)
            is_uptrend_intact = last_snap['price'] >= (max_price_in_window * 0.99)
            
            # Syarat 2: Spread harus wajar (menghindari manipulasi orderbook kosong)
            spread = ((sell_price - buy_price) / buy_price) * 100
            is_spread_ok = spread < 2.5 

            # === TRIGGER SINYAL ===
            if (price_change_pct >= self.MIN_PRICE_CHANGE and 
                vol_accumulated >= self.MIN_VOL_CHANGE and 
                is_uptrend_intact and 
                is_spread_ok):
                
                duration_str = f"{time_delta:.0f}s"
                msg_log = (f"MOMENTUM: {pair_raw} | Naik +{price_change_pct:.2f}% dalam {duration_str} | "
                           f"Vol +{vol_accumulated/1_000_000:.1f}M")
                
                self.log_queue.put({"type": "SIGNAL", "data": msg_log})

                # Kirim Sinyal Buy
                # Format: STRATEGY:PAIR|PRICE
                signal_data = f"{self.STRATEGY_LABEL}:{pair_raw}|{last_price}"
                
                self.signal_queue.put({
                    "type": "BUY",
                    "data": signal_data
                })
                
                # Set Cooldown 5 Menit untuk pair ini (agar tidak spam beli di pucuk)
                self.cooldown_list[pair_raw] = current_time + 300 
                
                # Reset memory pair ini agar analisa ulang dari nol nanti
                self.market_memory[pair_raw] = []

    def run(self):
        self.log_queue.put({"type": "INFO", "data": "SCANNER: Buzz Detector Online."})
        while True:
            try:
                self.detect_momentum()
                time.sleep(self.SCAN_INTERVAL)
            except Exception as e:
                self.log_queue.put({"type": "ERROR", "data": f"SCANNER ERR: {e}"})
                time.sleep(5)

def start_buzz_detector(log_queue, signal_queue):
    service = BuzzDetector(log_queue, signal_queue)
    service.run()