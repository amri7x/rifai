import os
import time
import requests
import pandas as pd
import ta
import sqlite3
import sys
import json

# Fix Path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

REFRESH_RATE = getattr(config, 'REFRESH_RATE', 3.0)

class ResearchEngine:
    # Perhatikan: Menerima 2 Queue sekarang
    def __init__(self, log_queue, scalp_queue, day_queue):
        self.log_queue = log_queue
        self.scalp_queue = scalp_queue
        self.day_queue = day_queue
        self.db_path = os.path.join(getattr(config, 'DATABASE_DIR', 'pustaka/database'), 'market_data.db')
        self.last_signals = {} 
        self.active_pairs = []
        self.last_pair_refresh = 0
        self.scan_counter = 0

    def refresh_active_pairs(self):
        if time.time() - self.last_pair_refresh < 60: return
        try:
            if not os.path.exists(self.db_path): return
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT DISTINCT pair FROM candles")
            rows = cursor.fetchall()
            conn.close()
            self.active_pairs = [row[0] for row in rows if row[0] not in config.BLACKLIST]
            self.last_pair_refresh = time.time()
            if self.active_pairs:
                self.log_queue.put({"type": "INFO", "data": f"RESEARCH: Loaded {len(self.active_pairs)} assets for analysis."})
        except: pass

    def get_data_from_db(self, pair, limit = getattr(config, 'DB_LOAD_LIMIT', 50)):
        try:
            conn = sqlite3.connect(self.db_path)
            query = f"SELECT * FROM candles WHERE pair='{pair}' ORDER BY timestamp DESC LIMIT {limit}"
            df = pd.read_sql_query(query, conn)
            conn.close()
            if df.empty: return None
            return df.iloc[::-1].reset_index(drop=True)
        except: return None

    def calculate_indicators(self, df):
        if len(df) < config.VOLUME_MA_PERIOD: return df
        try:
            df['rsi'] = ta.momentum.rsi(df['close'], window=config.RSI_PERIOD)
            ema_p = getattr(config, 'EMA_PERIOD', 20)
            df['ema_20'] = ta.trend.ema_indicator(df['close'], window=ema_p)
            df['vol_ma'] = df['volume'].rolling(window=config.VOLUME_MA_PERIOD).mean()
        except: pass
        return df

    def run_strategies(self, df, pair):
        if len(df) < 20 or 'rsi' not in df.columns: return
        last = df.iloc[-1]

        # Format Value IDR (Juta/Milyar)
        val_idr = last['close'] * last['volume']
        val_str = f"{val_idr/1_000_000:.1f}M" if val_idr > 1000000000 else f"{val_idr/1_000_000:.0f}Jt"

        # --- DETEKSI AKTIVITAS RESEARCH (LOGGING) ---
        # Jika ada lonjakan volume signifikan (> 2x rata-rata) tapi belum beli, kita Log sebagai "Pantauan"
        if last['volume'] > (last['vol_ma'] * config.SCALP_VOL_MULTIPLIER) and val_idr > config.SCALP_MIN_VALUE_IDR:
             # Cek apakah baru saja di log (biar ga spam per detik)
            signal_id_log = f"{pair}_LOG_{last['timestamp']}"
            if signal_id_log not in self.last_signals:
                self.log_queue.put({
                    "type": "INFO", 
                    "data": f"RESEARCH: {pair} Vol Spike ({val_str}) | RSI: {last['rsi']:.1f} | Monitoring..."
                })
                self.last_signals[signal_id_log] = True
        
        # 1. STRATEGI SCALPING -> Kirim ke Scalp Queue
        if config.SCALP_ENABLE:
            is_spike = last['volume'] > (last['vol_ma'] * config.SCALP_VOL_MULTIPLIER)
            is_uptrend = last['close'] >= last['open']
            is_rsi_safe = last['rsi'] < config.RSI_OVERBOUGHT
            val_idr = last['close'] * last['volume']
            
            if is_spike and is_uptrend and is_rsi_safe and val_idr >= config.SCALP_MIN_VALUE_IDR:
                self.trigger_signal(pair, "SCALP_SPIKE", last, val_idr, self.scalp_queue)
                return 

        # 2. STRATEGI DAY TRADE -> Kirim ke Day Queue
        if config.DAY_ENABLE:
            is_above_ema = last['close'] > last['ema_20']
            is_rsi_mid = config.RSI_OVERSOLD < last['rsi'] < config.RSI_OVERBOUGHT
            if is_above_ema and is_rsi_mid:
                mom_period = getattr(config, 'DAY_MOMENTUM_PERIOD', 3)
                recent = df.iloc[-mom_period:]
                if all(recent['close'] >= recent['open']):
                    val_idr = last['close'] * last['volume']
                    if val_idr > config.DAY_MIN_VALUE_IDR:
                        self.trigger_signal(pair, "DAY_TREND", last, val_idr, self.day_queue)

    def trigger_signal(self, pair, strategy, row, val_idr, target_queue):
        signal_id = f"{pair}_{strategy}_{row['timestamp']}"
        if signal_id in self.last_signals: return
        
        formatted_val = f"{val_idr/1_000_000:.1f}M" if val_idr > 1000000000 else f"{val_idr/1_000_000:.1f}Jt"
        msg = (f"{strategy}: {pair} | Vol: {formatted_val} | RSI: {row['rsi']:.1f}")
        
        self.log_queue.put({"type": "SIGNAL", "data": msg})
        
        # KIRIM KE ANTRIAN YANG SESUAI
        target_queue.put({
            "type": "BUY",
            "data": f"{strategy}:{pair}|{row['close']}"
        })
        
        self.last_signals[signal_id] = True

    def run(self):
        self.log_queue.put({"type": "INFO", "data": "RESEARCH: Brain Online (Routing 2 Strategies)."})
        while True:
            try:
                self.refresh_active_pairs()

                self.scan_counter += 1
                if self.scan_counter % 10 == 0:
                     if self.active_pairs:
                        self.log_queue.put({
                            "type": "INFO", 
                            "data": f"RESEARCH: Deep analyzing {len(self.active_pairs)} pairs..."
                        })

                for pair in self.active_pairs:
                    df = self.get_data_from_db(pair)
                    if df is not None:
                        df = self.calculate_indicators(df)
                        self.run_strategies(df, pair)
                time.sleep(REFRESH_RATE)
            except Exception as e:
                self.log_queue.put({"type": "ERROR", "data": f"RESEARCH CRASH: {str(e)}"})
                time.sleep(5)

def start_research(log_queue, scalp_queue, day_queue):
    engine = ResearchEngine(log_queue, scalp_queue, day_queue)
    engine.run()