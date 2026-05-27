import requests
import time
import sys
import os
import json # Ditambahkan karena ada penggunaan json.load di kode Anda
import traceback
from datetime import datetime

# === TAMBAHAN UNTUK AUTO RE-CONNECT ===
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

class ReconScanner:
    def __init__(self, log_queue, data_queue):
        self.log_queue = log_queue   
        self.data_queue = data_queue 
        self.api_url = f"{config.INDODAX_API_URL}/api/summaries"
        
        self.monitored_pairs = set()
        self.candle_buffer = {}
        self.last_minute = datetime.now().minute

        # === SETUP SESI DENGAN AUTO RETRY ===
        self.session = self._create_retry_session()

    def _create_retry_session(self, retries=3, backoff_factor=1, status_forcelist=(500, 502, 504)):
        """
        Membuat session yang otomatis mencoba reconnect jika koneksi putus
        atau server error, dengan jeda waktu (backoff).
        """
        session = requests.Session()
        retry = Retry(
            total=retries,
            read=retries,
            connect=retries,
            backoff_factor=backoff_factor, # Tunggu 1s, 2s, 4s...
            status_forcelist=status_forcelist,
        )
        adapter = HTTPAdapter(max_retries=retry)
        session.mount('http://', adapter)
        session.mount('https://', adapter)
        return session

    def process_candle(self, pair, price, vol_idr_24h):
        if pair not in self.candle_buffer:
            self.candle_buffer[pair] = {
                "open": price, "high": price, "low": price, "close": price,
                "vol_start": vol_idr_24h, "vol_final": vol_idr_24h
            }
        else:
            c = self.candle_buffer[pair]
            c["high"] = max(c["high"], price)
            c["low"] = min(c["low"], price)
            c["close"] = price
            c["vol_final"] = vol_idr_24h

    def finalize_candles(self):
        # Format Baru: Integer Timestamp (Unix)
        ts_now = int(time.time()) 
        # Bulatkan ke menit terdekat (hapus detik)
        ts_minute = ts_now - (ts_now % 60)
        
        count = 0
        for pair, data in self.candle_buffer.items():
            real_vol = max(0, data["vol_final"] - data["vol_start"])
            
            # Format Baru: List Sederhana [ts, o, h, l, c, v]
            candle_list = [
                ts_minute,
                data["open"],
                data["high"],
                data["low"],
                data["close"],
                real_vol
            ]

            self.data_queue.put({
                "type": "CANDLE_UPDATE",
                "pair": pair,
                "data": candle_list
            })
            count += 1

        if count > 0:
            self.log_queue.put({"type": "RECON", "data": f"Candle Finalized: {count} assets sent to Pustaka."})

        self.candle_buffer.clear()

    def run(self):
        self.log_queue.put({"type": "INFO", "data": "RECON: Scanner Started with Auto-Reconnect."})
        
        while True:
            try:
                start_time = time.time()
                now = datetime.now()

                # Cek pergantian menit untuk finalisasi candle
                if now.minute != self.last_minute:
                    self.finalize_candles()
                    self.last_minute = now.minute

                # === MODIFIKASI SIMULATOR ===
                mock_path = "mock_tickers.json"
                data = None
                
                # 1. Cek apakah file Mock ada (Offline Mode)
                if os.path.exists(mock_path):
                    try:
                        with open(mock_path, "r") as f:
                            data = json.load(f)
                    except: pass
                
                # 2. Jika tidak ada Mock, ambil dari Internet (Online Mode)
                # MENGGUNAKAN SELF.SESSION AGAR AUTO-RECONNECT
                if data is None:
                    try:
                        # Timeout sedikit diperpanjang agar tidak gampang putus
                        response = self.session.get(self.api_url, timeout=10)
                        if response.status_code == 200:
                            data = response.json()
                    except requests.exceptions.RequestException as e:
                        # Log warning ringan, tidak perlu crash loop
                        # self.log_queue.put({"type": "WARNING", "data": f"RECON: Conn unstable, retrying..."})
                        pass 

                # Lanjut ke proses data
                if data: 
                    tickers = data.get('tickers', {})
                    
                    # List penampung kandidat
                    candidates = []

                    for pair_id, details in tickers.items():
                        # 1. Filter Wajib (IDR & Blacklist)
                        if not pair_id.endswith(config.BASE_CURRENCY): continue
                        if pair_id in config.BLACKLIST: continue
                        
                        # 2. Cek Whitelist (Jika diisi, skip yang tidak terdaftar)
                        if config.WHITELIST and pair_id not in config.WHITELIST: continue

                        try:
                            last_price = float(details.get('last', 0))
                            vol_idr = float(details.get('vol_idr', 0))
                            high = float(details.get('high', 0))
                            low = float(details.get('low', 0))
                        except: continue

                        # 3. Filter Harga & Volume
                        if last_price < getattr(config, 'MIN_PRICE', 50): continue
                        if vol_idr < config.MIN_VOL_IDR: continue

                        # 4. Hitung Volatilitas
                        volatility = 0
                        if low > 0:
                            volatility = ((high - low) / low) * 100
                        
                        # 5. Filter Keliaran
                        if volatility < getattr(config, 'MIN_DAILY_VOLATILITY', 3.0): continue

                        # Masukkan ke keranjang seleksi
                        candidates.append({
                            'pair': pair_id,
                            'price': last_price,
                            'vol': vol_idr,
                            'volatility': volatility
                        })

                    # === SORTING STRATEGY ===
                    candidates.sort(key=lambda x: x['volatility'], reverse=True)
                    max_can = getattr(config, 'RECON_MAX_CANDIDATES', 15)
                    top_picks = candidates[:max_can]

                    for item in top_picks:
                        pair_id = item['pair']
                        last_price = item['price']
                        vol_idr = item['vol']
                        
                        # Logika Warmup (Pustaka)
                        if pair_id not in self.monitored_pairs:
                            self.monitored_pairs.add(pair_id)
                            self.data_queue.put({
                                "type": "WARMUP_REQ", 
                                "pair": pair_id
                            })
                            self.log_queue.put({"type": "INFO", "data": f"RECON: Tracking {pair_id} (Volat: {item['volatility']:.1f}%)"})

                        # Proses Candle
                        self.process_candle(pair_id, last_price, vol_idr)

                # Jeda loop sesuai config
                elapsed = time.time() - start_time
                time.sleep(max(0, getattr(config, 'REFRESH_RATE', 3.0) - elapsed))

            except Exception as e:
                # Error Catching Utama (Jika sesi retry pun gagal total)
                self.log_queue.put({"type": "CRITICAL", "data": f"RECON ERR: {str(e)}"})
                # traceback.print_exc() # Opsional: nyalakan jika ingin debug mendalam
                
                # Jika error parah, reset session
                try:
                    self.session.close()
                    self.session = self._create_retry_session()
                    self.log_queue.put({"type": "INFO", "data": "RECON: Session reset completed."})
                except: pass
                
                time.sleep(5)

def start_recon(log_queue, data_queue):
    scanner = ReconScanner(log_queue, data_queue)
    scanner.run()