import sqlite3
import time
import sys
import os
import traceback
import requests
import pandas as pd
from datetime import datetime

# Fix Path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

class LibraryManager:
    def __init__(self, log_queue, data_queue):
        self.log_queue = log_queue
        self.data_queue = data_queue
        
        # Setup Folder Database
        self.db_dir = getattr(config, 'DATABASE_DIR', 'pustaka/database')
        if not os.path.exists(self.db_dir):
            os.makedirs(self.db_dir)
            
        self.db_path = os.path.join(self.db_dir, 'market_data.db')
        self.history_url = config.INDODAX_HISTORY_OHLC
        
        # Inisialisasi Tabel
        self.init_db()

    def init_db(self):
        """Membuat tabel jika belum ada dengan skema yang efisien"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Tabel Candle: Primary Key Komposit (pair + timeframe + timestamp) mencegah duplikat
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS candles (
                    pair TEXT,
                    timeframe INTEGER,
                    timestamp INTEGER,
                    open REAL,
                    high REAL,
                    low REAL,
                    close REAL,
                    volume REAL,
                    PRIMARY KEY (pair, timeframe, timestamp)
                )
            ''')
            
            # Index untuk mempercepat query Research
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_pair_ts ON candles (pair, timestamp DESC)')
            
            conn.commit()
            conn.close()
            self.log_queue.put({"type": "INFO", "data": f"PUSTAKA: Database Ready at {self.db_path}"})
        except Exception as e:
            self.log_queue.put({"type": "ERROR", "data": f"PUSTAKA DB Init Error: {e}"})

    def fetch_history_api(self, pair):
        """Mengambil data history awal dari API Indodax (Warmup)"""
        try:
            now_ts = int(time.time())
            # Ambil history 24 jam terakhir (cukup untuk indikator RSI/MA)
            lookback = getattr(config, 'HISTORY_LOOKBACK_SECONDS', None)
            from_ts = now_ts - lookback
            
            # Format Symbol: btc_idr -> BTCIDR
            symbol_clean = pair.upper().replace('_', '')
            
            params = {
                "symbol": symbol_clean,
                "tf": str(config.TIMEFRAME), # 1 menit
                "from": from_ts,
                "to": now_ts
            }
            
            # Retry logic sederhana
            for attempt in range(2):
                resp = requests.get(self.history_url, params=params, timeout=10)
                if resp.status_code == 200:
                    data = resp.json()
                    if not data or not isinstance(data, list): return None
                    
                    # Format API Indodax: 
                    # {"Time": ..., "Open": ..., "High": ..., "Low": ..., "Close": ..., "Volume": ...}
                    # Kita butuh convert ke list of list untuk batch insert
                    candles = []
                    for c in data:
                        candles.append((
                            pair,
                            config.TIMEFRAME,
                            c['Time'],
                            float(c['Open']),
                            float(c['High']),
                            float(c['Low']),
                            float(c['Close']),
                            float(c['Volume'])
                        ))
                    return candles
                time.sleep(1) # Jeda antar retry
            return None
        except:
            return None

    def save_batch(self, candle_list):
        """Menyimpan banyak data sekaligus (Batch Insert)"""
        if not candle_list: return
        
        conn = None
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # INSERT OR REPLACE: Jika data timestamp sama sudah ada, timpa dengan yang baru
            cursor.executemany('''
                INSERT OR REPLACE INTO candles (pair, timeframe, timestamp, open, high, low, close, volume)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', candle_list)
            
            conn.commit()
        except Exception as e:
            self.log_queue.put({"type": "ERROR", "data": f"PUSTAKA Save Error: {e}"})
        finally:
            if conn: conn.close()

    def process_queue(self):
        """Memproses data yang masuk dari Recon Scanner"""
        
        # 1. Kumpulkan data real-time dari Recon
        live_candles = []
        while not self.data_queue.empty():
            try:
                payload = self.data_queue.get()
                
                # Kasus 1: Update Candle Real-time
                if payload['type'] == 'CANDLE_UPDATE':
                    # Format payload: {'pair': '...', 'data': [ts, o, h, l, c, v]}
                    p_data = payload['data']
                    live_candles.append((
                        payload['pair'],
                        config.TIMEFRAME,
                        p_data[0], p_data[1], p_data[2], p_data[3], p_data[4], p_data[5]
                    ))
                
                # Kasus 2: Permintaan Warmup (Download History)
                elif payload['type'] == 'WARMUP_REQ':
                    pair = payload['pair']
                    history_data = self.fetch_history_api(pair)
                    if history_data:
                        self.save_batch(history_data)
                        self.log_queue.put({"type": "INFO", "data": f"PUSTAKA: Warmed up {pair} ({len(history_data)} candles)"})
                    time.sleep(0.2) # Jeda agar tidak kena rate limit
                    
            except:
                break
        
        # 2. Simpan data real-time jika ada
        if live_candles:
            self.save_batch(live_candles)
            self.log_queue.put({"type": "INFO", "data": f"PUSTAKA: Saved {len(live_candles)} live updates."})

    def run(self):
        self.log_queue.put({"type": "INFO", "data": "PUSTAKA: Engine Started (SQLite Mode)."})
        
        while True:
            try:
                self.process_queue()
                time.sleep(0.5) # Responsif tapi hemat CPU
                
            except Exception as e:
                self.log_queue.put({"type": "ERROR", "data": f"PUSTAKA CRASH: {e}"})
                traceback.print_exc()
                time.sleep(5)

def start_pustaka(log_queue, data_queue):
    man = LibraryManager(log_queue, data_queue)
    man.run()