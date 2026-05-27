import time
import hmac
import hashlib
import requests
import json
import urllib.parse
import threading
import websocket
import sys
import os
import random
import ta
import pandas as pd
import numpy as np
from datetime import datetime

# Fix Path untuk import config
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

# Config Fallback
REFRESH_RATE = getattr(config, 'REFRESH_RATE', 3.0)
PAPER_MODE = getattr(config, 'PAPER_MODE', False)

class TradingAgent:
    def __init__(self, log_queue, signal_queue, notify_queue, bot_id):
        self.log_queue = log_queue
        self.signal_queue = signal_queue
        self.notify_queue = notify_queue
        self.bot_id = bot_id 
        self.shared_active_assets = None
        
        # File State & Wallet
        self.state_file = f"state_{self.bot_id}.json"
        self.paper_wallet_file = "paper_wallet.json"
        
        # API Credentials
        self.api_key = config.INDODAX_API_KEY
        self.secret_key = config.INDODAX_SECRET_KEY.encode('utf-8')
        self.base_url = config.INDODAX_API_URL
        self.history_url = config.INDODAX_HISTORY_OHLC
        
        # WebSocket Internal
        self.ws_url = getattr(config, 'INDODAX_WS_URL', "wss://ws3.indodax.com/ws/")
        self.ws_token = None 
        self.ws_app = None
        self.ws_connected = False
        self.subscribed_channels = set()
        self.server_time_offset = 0
        
        # === MEMORY INTELLIGENCE ===
        self.active_order = self.load_state()
        self.price_cache = {} 
        self.latest_book = {"bids": [], "asks": []}
        self.recent_trades = []
        self.target_pair_monitor = None 
        self.current_activity = "IDLE"
        
        # === MEMORY POST-TRADE (SNIPER) ===
        self.post_trade_active = False
        self.post_trade_start_time = 0
        self.post_trade_pair = None
        self.post_trade_history = [] 
        self.post_trade_oversold_triggered = False # Flag V-Shape
        self.shadow_limit_price = 0  

        if PAPER_MODE: self.init_paper_wallet()

    # =========================================================
    # === WEBSOCKET CORE ===
    # =========================================================
    def fetch_new_ws_token(self):
        return getattr(config, 'WS_TOKEN', None)

    def _ws_on_open(self, ws):
        auth_payload = {"params": {"token": self.ws_token}, "id": 1}
        ws.send(json.dumps(auth_payload))

    def _ws_on_message(self, ws, message):
        try:
            response = json.loads(message)
            msg_id = response.get("id")

            # 1. Auth Response
            if msg_id == 1: 
                if "result" in response and response["result"].get("client"):
                    self.ws_connected = True
                    # Re-subscribe jika sedang pegang aset atau memantau post-trade
                    if self.active_order: 
                        self._subscribe_pair(self.active_order['pair'], include_orderbook=True)
                    if self.post_trade_active and self.post_trade_pair: 
                        self._subscribe_pair(self.post_trade_pair, include_orderbook=False)
                else: 
                    self.ws_connected = False
            
            # 2. Data Stream
            elif "result" in response and "data" in response["result"]:
                res = response["result"]
                channel = res.get("channel", "")
                data_content = res.get("data", {})

                # A. Trade Activity (Harga & Volume)
                if "trade-activity" in channel and "data" in data_content:
                    trades = data_content["data"]
                    symbol = channel.split("-")[-1] 
                    if trades:
                        # Update Price Cache
                        price = float(trades[0][4])
                        self.price_cache[symbol] = price
                        
                        # Filter Target Monitor (Untuk Tape Reading)
                        target = self.target_pair_monitor
                        if not target and self.post_trade_active: 
                            target = self._format_pair_v4(self.post_trade_pair)
                        
                        if target and symbol == target:
                            for t in trades:
                                self.recent_trades.append({"side": t[3], "price": float(t[4]), "vol": float(t[5])})

                # B. Order Book (Untuk Analisis Tembok)
                elif "order-book" in channel and "data" in data_content:
                    ob_data = data_content.get("data", {})
                    pair_in_channel = channel.split("-")[-1]
                    target = self.target_pair_monitor
                    
                    if target and pair_in_channel == target:
                        if "bid" in ob_data: self.latest_book["bids"] = ob_data["bid"]
                        if "ask" in ob_data: self.latest_book["asks"] = ob_data["ask"]

        except Exception as e: pass

    def _ws_run_forever(self):
        while True:
            try:
                self.ws_token = self.fetch_new_ws_token()
                self.ws_app = websocket.WebSocketApp(
                    self.ws_url, on_open=self._ws_on_open, on_message=self._ws_on_message,
                    header={"User-Agent": "Mozilla/5.0"}
                )
                self.ws_app.run_forever(ping_interval=30, ping_timeout=10)
                time.sleep(5)
            except: time.sleep(5)

    def start_websocket_thread(self):
        t = threading.Thread(target=self._ws_run_forever); t.daemon = True; t.start()

    def _subscribe_pair(self, pair, include_orderbook=False):
        if not self.ws_connected or not self.ws_app: return
        sym = self._format_pair_v4(pair)
        
        # Channel Trade (Wajib)
        if f"trade-{sym}" not in self.subscribed_channels:
            payload = {"method": 1, "params": {"channel": f"market:trade-activity-{sym}"}, "id": 2}
            self.ws_app.send(json.dumps(payload))
            self.subscribed_channels.add(f"trade-{sym}")
        
        # Channel Orderbook (Opsional, hanya saat butuh Intelligence)
        if include_orderbook and f"ob-{sym}" not in self.subscribed_channels:
            payload = {"method": 1, "params": {"channel": f"market:order-book-{sym}"}, "id": 3}
            self.ws_app.send(json.dumps(payload))
            self.subscribed_channels.add(f"ob-{sym}")

    # =========================================================
    # === INTELLIGENCE ENGINE (TAPE READING) ===
    # =========================================================
    def _calculate_market_health(self):
        """
        Menganalisa kesehatan market realtime dengan 'Tape Reading' Logic.
        Return: Score (0-100), Status (BULLISH/BEARISH)
        """
        try:
            bids = self.latest_book.get("bids", [])
            asks = self.latest_book.get("asks", [])
            
            if not bids or not asks: return 50.0, "NEUTRAL"

            # 1. ANALISA TEMBOK (STATIS)
            # Ambil 10 lapis teratas
            bid_vol_top = sum([float(x['idr_volume']) for x in bids[:10]])
            ask_vol_top = sum([float(x['idr_volume']) for x in asks[:10]])
            
            if bid_vol_top == 0: bid_vol_top = 1
            wall_ratio = ask_vol_top / bid_vol_top 
            
            # 2. ANALISA SERANGAN / ATTACK POWER (KINETIS)
            buy_attack_vol = 0
            sell_dump_vol = 0
            
            if self.recent_trades:
                # Ambil 50 trade terakhir sebagai sampel momentum
                recent = self.recent_trades[-50:]
                for t in recent:
                    trade_val = float(t['price']) * float(t['vol'])
                    if t['side'] == 'buy': buy_attack_vol += trade_val
                    else: sell_dump_vol += trade_val
            
            # 3. WALL EATING VELOCITY (Rasio Serangan terhadap Tembok)
            wall_attack_ratio = 0
            if ask_vol_top > 0:
                wall_attack_ratio = buy_attack_vol / ask_vol_top
            
            # --- SKORING ---
            score = 50.0
            
            # A. Skor Tembok
            if wall_ratio < 0.6: score += 15       # Tembok Beli Tebal
            elif wall_ratio > 2.0: score -= 15     # Tembok Jual Tebal
            
            # B. Skor Dominasi Trade
            total_activity = buy_attack_vol + sell_dump_vol
            if total_activity > 0:
                buy_dominance = buy_attack_vol / total_activity
                if buy_dominance > 0.65: score += 20
                elif buy_dominance < 0.35: score -= 20
            
            # C. THE SMARTS (Kecerdasan Override)
            # Jika Tembok Jual Tebal TAPI Serangan Buyer Masif -> BULLISH
            if wall_ratio > 2.0 and wall_attack_ratio > 0.3:
                score += 35 # Override Bearish jadi Bullish

            status = "NEUTRAL"
            if score >= 65: status = "BULLISH"
            elif score <= 35: status = "BEARISH"
            
            return score, status

        except Exception as e:
            return 50.0, "NEUTRAL"

    # =========================================================
    # === ENTRY VALIDATION (MATA ELANG) ===
    # =========================================================
    def validate_technical_setup(self, pair):
        """
        Cek teknikal kilat sebelum konek WS (Hemat resource).
        Filter: RSI Overbought & Harga terlalu jauh dari EMA (FOMO).
        """
        try:
            rsi_max = getattr(config, 'AGENT_RSI_MAX', 75.0)
            ema_tolerance = getattr(config, 'AGENT_EMA_TOLERANCE_PCT', 2.5) / 100.0
            rsi_period = getattr(config, 'RSI_PERIOD', 14)
            ema_period = getattr(config, 'EMA_PERIOD', 20)

            # Snapshot 60 menit terakhir
            now_ts = int(time.time())
            from_ts = now_ts - (60 * 60) 
            symbol_clean = pair.upper().replace('_', '')
            
            params = {"symbol": symbol_clean, "tf": "1", "from": from_ts, "to": now_ts}
            resp = requests.get(self.history_url, params=params, timeout=5)
            if resp.status_code != 200: return True, "API Skip" 
            
            data = resp.json()
            if not data or len(data) < (ema_period + 5): return True, "Not Enough Data"
            
            df = pd.DataFrame(data)
            df['close'] = df['Close'].astype(float)
            
            # Hitung Indikator
            rsi = ta.momentum.rsi(df['close'], window=rsi_period)
            current_rsi = rsi.iloc[-1]
            
            ema = ta.trend.ema_indicator(df['close'], window=ema_period)
            current_price = df['close'].iloc[-1]
            current_ema = ema.iloc[-1]
            
            # Check RSI
            if current_rsi > rsi_max:
                return False, f"RSI Overbought ({current_rsi:.1f})"
            
            # Check EMA Deviation
            if current_ema > 0:
                deviasi = (current_price - current_ema) / current_ema
                if deviasi > ema_tolerance: 
                    return False, f"Price too high ({deviasi*100:.1f}%)"

            return True, f"Technical OK (RSI: {current_rsi:.1f})"

        except Exception as e:
            return True, f"Tech Check Err: {str(e)}"

    def _analyze_entry_quality(self, pair):
        """
        Menganalisa Order Book Realtime untuk Entry yang aman.
        """
        bids = self.latest_book.get("bids", [])
        asks = self.latest_book.get("asks", [])

        if not bids or not asks: return False, "Data Orderbook Kosong"

        try:
            best_bid = float(bids[0]['price'])
            best_ask = float(asks[0]['price'])
            spread = ((best_ask - best_bid) / best_bid) * 100
            
            # Cek Spread
            max_spread = getattr(config, 'AGENT_MAX_SPREAD', 2.0)
            if spread > max_spread: return False, f"Spread Lebar: {spread:.2f}%"

            # Cek Wall Ratio
            bid_vol = sum([float(x['idr_volume']) for x in bids[:5]])
            ask_vol = sum([float(x['idr_volume']) for x in asks[:5]])
            if bid_vol == 0: bid_vol = 1
            wall_ratio = ask_vol / bid_vol
            
            max_wall = getattr(config, 'AGENT_MAX_WALL_RATIO', 5.0)
            if wall_ratio > max_wall: return False, f"Tembok Jual Tebal: {wall_ratio:.1f}x"

            return True, f"OK. Spread {spread:.1f}%, Wall {wall_ratio:.1f}x"

        except Exception as e:
            return False, f"Analisis Error: {str(e)}"

    # =========================================================
    # === EXECUTION LOGIC ===
    # =========================================================
    def smart_execute_buy(self, signal_msg):
        """
        Entry Flow: Lock -> Tech Check -> WS Connect -> Observe -> Buy
        """
        parts = signal_msg.split('|')
        info = parts[0].split(':')
        strategy, pair = info[0], info[1]

        # 1. CEK LIST BERSAMA (Locking)
        if self.shared_active_assets is not None:
            if pair in self.shared_active_assets: return
            self.shared_active_assets.append(pair)

        self.current_activity = f"VALIDATING {pair}..."
        self.broadcast_status()
        self.log_queue.put({"type": "INFO", "data": f"{self.bot_id}: Validating {pair}..."})

        # 2. TECHNICAL SANITY CHECK
        is_tech_safe, tech_msg = self.validate_technical_setup(pair)
        if not is_tech_safe:
            self.log_queue.put({"type": "WARNING", "data": f"{self.bot_id} REJECT {pair}: {tech_msg}"})
            if self.shared_active_assets is not None and pair in self.shared_active_assets:
                self.shared_active_assets.remove(pair)
            self.current_activity = "REJECTED (TECH)"
            return 

        # 3. Setup Monitor Realtime
        sym = self._format_pair_v4(pair)
        self.target_pair_monitor = sym
        self.latest_book = {"bids": [], "asks": []} 
        self._subscribe_pair(pair, include_orderbook=True)
        
        # 4. LOOP OBSERVASI
        valid_entry = False
        msg = ""
        obs_cycles = getattr(config, 'AGENT_OBSERVATION_CYCLES', 5)
        obs_time = getattr(config, 'AGENT_OBSERVATION_TIME', 2)
        min_confirmations = 3
        consecutive_wins = 0
        
        self.log_queue.put({"type": "INFO", "data": f"{self.bot_id}: Observing {pair}..."})
        
        for i in range(obs_cycles):
            time.sleep(obs_time) 
            is_good, msg = self._analyze_entry_quality(pair)
            
            if is_good:
                consecutive_wins += 1
                self.current_activity = f"OBSERVING {pair}: {consecutive_wins}/{min_confirmations} OK"
                self.broadcast_status()
                if consecutive_wins >= min_confirmations:
                    valid_entry = True
                    break
            else:
                consecutive_wins = 0 
                self.current_activity = f"OBSERVING {pair}: RESET ({msg[:15]})" 
                self.broadcast_status()
        
        self.target_pair_monitor = None
        
        if valid_entry:
            self.current_activity = "EXECUTING BUY..." 
            self.broadcast_status()
            self._execute_market_buy(pair, strategy)
        else:
            self.current_activity = "CANCELLED"
            self.broadcast_status()
            if self.shared_active_assets is not None and pair in self.shared_active_assets:
                try: self.shared_active_assets.remove(pair)
                except: pass

    def _execute_market_buy(self, pair, strategy):
        # Double check locking
        if self.shared_active_assets is not None:
             if pair not in self.shared_active_assets: self.shared_active_assets.append(pair)

        entry = self.get_realtime_price(pair)
        if not entry: 
            if self.shared_active_assets is not None and pair in self.shared_active_assets:
                self.shared_active_assets.remove(pair)
            return
        
        min_buy = getattr(config, 'BUY_AMOUNT_MIN', 20000)
        max_buy = getattr(config, 'BUY_AMOUNT_MAX', 30000)
        target_amount = random.randint(min_buy, max_buy)
        
        # Fee Calculation
        fee_taker = getattr(config, 'FEE_TAKER', 0.0051)
        fee_multiplier = 1.0 - fee_taker
        
        success = False
        final_price = entry
        amount_spent = 0
        
        if PAPER_MODE:
            wallet = self.get_paper_balance()
            if wallet['idr'] >= target_amount:
                amount_spent = target_amount
                coin_amt = (amount_spent / final_price) * fee_multiplier
                self.update_paper_wallet(-amount_spent, pair.split('_')[0], coin_amt)
                success = True
                self.log_queue.put({"type": "SUCCESS", "data": f"{self.bot_id} BUY (Paper): Rp {amount_spent:,.0f} {pair}"})
            else:
                self.log_queue.put({"type": "WARNING", "data": f"{self.bot_id} Saldo Paper Habis!"})

        else:
             # Real Buy implementation would go here
             pass

        if success:
            self.save_state("HOLDING", pair, entry_price=final_price, highest_price=final_price, strategy=strategy, amount_idr=amount_spent)
            self._subscribe_pair(pair)
        else:
            if self.shared_active_assets is not None and pair in self.shared_active_assets:
                self.shared_active_assets.remove(pair)

    # =========================================================
    # === POSITION MANAGEMENT (HOLDING) ===
    # =========================================================
    def manage_active_position(self):
        if not self.active_order or self.active_order['status'] != 'HOLDING': return
        
        pair = self.active_order['pair']
        
        # 1. Paksa Monitoring Aktif
        target_fmt = self._format_pair_v4(pair)
        if self.target_pair_monitor != target_fmt:
            self.target_pair_monitor = target_fmt
            self._subscribe_pair(pair, include_orderbook=True)
        
        entry = self.active_order.get('entry_price', 0)
        highest = self.active_order.get('highest_price', 0)
        curr = self.get_realtime_price(pair)
        if not curr: return

        # Update Highest
        if curr > highest:
            highest = curr
            self.active_order['highest_price'] = highest
            self.save_state("HOLDING", pair, entry, highest, self.active_order['strategy'], self.active_order.get('amount_idr', 0))

        # 2. INTEL CHECK
        health_score, market_status = self._calculate_market_health()
        
        pnl_pct = ((curr - entry) / entry) * 100
        self.current_activity = f"HOLD {pnl_pct:.2f}% | {market_status} (Sc:{health_score:.0f})"

        # 3. DYNAMIC TRAILING & DEFENSE
        trailing_pct = getattr(config, 'TRAILING_STOP_PERCENT', 2.0)
        activation_pct = getattr(config, 'TRAILING_ACTIVATION_PERCENT', 1.5)
        hard_sl_pct = getattr(config, 'HARD_STOP_LOSS_PERCENT', 3.0)

        # A. Skenario PROFIT (Trailing Mode)
        if (highest - entry) / entry * 100 >= activation_pct:
            if market_status == "BULLISH": trailing_pct *= 1.5 # Longgar
            elif market_status == "BEARISH": trailing_pct *= 0.5 # Ketat
            
            stop_price = highest * (1 - (trailing_pct / 100))
            if curr <= stop_price:
                self.execute_sell(pair, curr, f"Trailing Stop ({market_status})")

        # B. Skenario LOSS (Defense Mode)
        else:
            stop_price = entry * (1 - (hard_sl_pct / 100))
            if curr <= stop_price:
                # Defense: Jika market score > 60, tahan (Dead Cat Bounce hope)
                if health_score > 60:
                    self.current_activity = "DEFENDING (Strong Buy Wall)"
                    return 
                self.execute_sell(pair, curr, "Hard Stop Loss")

    def execute_sell(self, pair, price, reason):
        self.current_activity = f"SELLING... ({reason})"
        self.broadcast_status()
        self.log_queue.put({"type": "WARNING", "data": f"{self.bot_id}: {reason} Hit {pair} @ {price:,.0f}"})
        
        success = False
        pnl = 0
        total_sell_val = 0
        coin = pair.split('_')[0]
        
        entry = self.active_order.get('entry_price', 0)
        buy_capital = self.active_order.get('amount_idr', 0)
        fee_multiplier = 1.0 - getattr(config, 'FEE_TAKER', 0.0051)

        if PAPER_MODE:
            wallet = self.get_paper_balance()
            coin_amt = wallet["assets"].get(coin, 0)
            if coin_amt > 0:
                gross_sell = coin_amt * price
                net_idr = gross_sell * fee_multiplier
                self.update_paper_wallet(net_idr, coin, -coin_amt)
                
                if buy_capital > 0: pnl = net_idr - buy_capital
                else: pnl = net_idr - (entry * coin_amt)
                
                total_sell_val = net_idr
                success = True
                self.log_queue.put({"type": "SUCCESS", "data": f"{self.bot_id} SOLD (Paper): Rp {total_sell_val:,.0f} (PnL {pnl:,.0f}) | {reason}"})
            else:
                success = True 
        else:
            # Real sell logic here
            pass

        if success:
            report_data = {
                "pair": pair, "strategy": self.active_order.get('strategy', 'MANUAL'),
                "buy_price": entry, "sell_price": price, "pnl_amt": pnl,
                "pnl_pct": ((price - entry) / entry) * 100, "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "wallet": 0, "buy_capital": buy_capital, "sell_total": total_sell_val, "reason": reason
            }
            self.notify_queue.put({"type": "SALE_REPORT", "data": report_data})
            self.log_queue.put({"type": "PNL_UPDATE", "bot_id": self.bot_id, "amount": pnl})
            
            # === TRANSISI KE POST-TRADE WATCH (SNIPER MODE) ===
            if getattr(config, 'ENABLE_POST_TRADE_WATCH', True):
                self.log_queue.put({"type": "INFO", "data": f"{self.bot_id}: Sold {pair}. Switching to WATCH mode (Shadow Limit)."})
                self.active_order = None 
                if os.path.exists(self.state_file): os.remove(self.state_file)
                
                self.post_trade_active = True
                self.post_trade_pair = pair
                self.post_trade_start_time = time.time()
                self.post_trade_history = [] 
                self.post_trade_oversold_triggered = False # Reset V-Shape Flag
                self.current_activity = "WATCHING DIP (Shadow Limit)"
            else:
                self.target_pair_monitor = None
                if self.shared_active_assets is not None and pair in self.shared_active_assets:
                    try: self.shared_active_assets.remove(pair)
                    except: pass
                self.active_order = None
                self.current_activity = "IDLE"

    # =========================================================
    # === POST-TRADE WATCH (SNIPER LOGIC) ===
    # =========================================================
    def _monitor_post_trade(self):
        if not self.post_trade_active or not self.post_trade_pair: return
        
        pair = self.post_trade_pair
        curr_price = self.get_realtime_price(pair)
        if not curr_price: return

        # 1. Timeout Check
        if time.time() - self.post_trade_start_time > getattr(config, 'POST_TRADE_WAIT_TIME', 900):
            self.log_queue.put({"type": "INFO", "data": f"{self.bot_id}: Stop watching {pair}. Timeout."})
            self._cleanup_post_trade()
            return

        # 2. Collect Data
        self.post_trade_history.append(curr_price)
        if len(self.post_trade_history) > 50: self.post_trade_history.pop(0)

        if len(self.post_trade_history) < 20: 
            self.current_activity = f"WATCHING {pair}: Collecting Data ({len(self.post_trade_history)}/20)"
            return

        # 3. Bollinger Calculation
        series = pd.Series(self.post_trade_history)
        bb_window = getattr(config, 'POST_TRADE_BB_PERIOD', 20)
        bb_std = getattr(config, 'POST_TRADE_BB_STD', 2.0)
        
        sma = series.rolling(window=bb_window).mean().iloc[-1]
        std = series.rolling(window=bb_window).std().iloc[-1]
        lower_band = sma - (bb_std * std)
        
        buffer_pct = getattr(config, 'POST_TRADE_RECLAIM_BUFFER', 0.2)
        reclaim_price = lower_band * (1 + (buffer_pct/100))
        
        self.shadow_limit_price = lower_band
        state_msg = "WAITING DIP"

        # 4. LOGIKA V-SHAPE
        # Fase A: Menyelam
        if curr_price < lower_band:
            self.post_trade_oversold_triggered = True
            state_msg = "OVERSOLD (Ready)"
        elif self.post_trade_oversold_triggered:
            state_msg = "RECOVERING..."

        self.current_activity = f"WATCHING {pair}: P:{curr_price:,.0f} | Limit:{lower_band:,.0f} | [{state_msg}]"

        # Fase B: Reclaim & Execute
        if self.post_trade_oversold_triggered and curr_price > reclaim_price:
            msg = f"REBOUND DETECTED: {pair} Reclaimed {lower_band:,.0f} -> {curr_price:,.0f}"
            self.log_queue.put({"type": "SIGNAL", "data": msg})
            
            self.current_activity = "EXECUTING RE-ENTRY..."
            self._execute_market_buy(pair, "REBOUND_SNIPER")
            self._cleanup_post_trade()

    def _cleanup_post_trade(self):
        self.target_pair_monitor = None
        pair = self.post_trade_pair
        if self.shared_active_assets is not None and pair in self.shared_active_assets:
            try: self.shared_active_assets.remove(pair)
            except: pass
        
        self.post_trade_active = False
        self.post_trade_pair = None
        self.post_trade_history = []
        self.current_activity = "IDLE"

    # =========================================================
    # === UTILS ===
    # =========================================================
    def get_realtime_price(self, pair):
        mock_path = "mock_tickers.json"
        if os.path.exists(mock_path):
            try:
                with open(mock_path, "r") as f:
                    data = json.load(f)['tickers']
                    if pair in data: return float(data[pair]['last'])
            except: pass
            
        sym = self._format_pair_v4(pair)
        if self.ws_connected and sym in self.price_cache: 
            return self.price_cache[sym]
        try: 
            resp = requests.get(f"{self.base_url}/api/ticker/{pair}", timeout=3).json()
            price = float(resp['ticker']['last'])
            self.price_cache[sym] = price
            return price
        except: return None

    def broadcast_status(self):
        try:
            position = None
            status = "IDLE"
            if self.active_order and self.active_order['status'] == 'HOLDING':
                status = "ACTIVE"
                pair = self.active_order['pair']
                entry = self.active_order['entry_price']
                buy_capital = self.active_order.get('amount_idr', 0)
                curr = self.get_realtime_price(pair)
                if not curr: curr = entry
                pnl_pct = ((curr - entry) / entry) * 100 if entry > 0 else 0
                highest = self.active_order.get('highest_price', entry)
                stop_loss = highest * (1 - getattr(config, 'TRAILING_STOP_PERCENT', 2.0)/100)
                current_value = (curr / entry) * buy_capital if entry > 0 else 0
                position = {
                    "pair": pair, "strategy": self.active_order.get('strategy', 'MANUAL'),
                    "entry": entry, "current": curr, "pnl_pct": pnl_pct,
                    "highest": highest, "stop_loss": stop_loss,
                    "current_value": current_value
                }
            
            wallet_idr = 0
            if PAPER_MODE:
                w = self.get_paper_balance()
                wallet_idr = w.get('idr', 0)

            self.log_queue.put({
                "type": "AGENT_UPDATE", 
                "bot_id": self.bot_id,
                "data": {
                    "wallet_idr": wallet_idr, "status": status,
                    "connection": "WS" if self.ws_connected else "API",
                    "position": position, "mode": "PAPER" if PAPER_MODE else "REAL",
                    "activity": self.current_activity
                }
            })
        except: pass

    def _format_pair_v4(self, pair_raw): return pair_raw.replace('_', '').lower()
    
    def sync_server_time(self):
        try:
            resp = requests.get(f"{self.base_url}/api/server_time", timeout=5).json()
            self.server_time_offset = int(resp['server_time']) - int(time.time() * 1000)
        except: self.server_time_offset = 0

    def get_nonce(self): return int(time.time() * 1000) + self.server_time_offset

    def _sign_and_request(self, params={}):
        if PAPER_MODE and params.get('method') == 'trade': return {"success": 0, "error": "Paper Mode"}
        params['nonce'] = self.get_nonce()
        query = urllib.parse.urlencode(params)
        sign = hmac.new(self.secret_key, query.encode('utf-8'), hashlib.sha512).hexdigest()
        try: return requests.post(f"{self.base_url}/tapi", headers={'Key': self.api_key, 'Sign': sign}, data=params, timeout=10).json()
        except: return None

    def save_state(self, status, pair, entry_price=0, highest_price=0, strategy="", amount_idr=0):
        state = { "status": status, "pair": pair, "entry_price": entry_price, "highest_price": highest_price, "strategy": strategy, "amount_idr": amount_idr, "timestamp": str(datetime.now()) }
        with open(self.state_file, "w") as f: json.dump(state, f)
        self.active_order = state

    def load_state(self):
        if os.path.exists(self.state_file):
            try: 
                with open(self.state_file, "r") as f: return json.load(f)
            except: return None
        return None

    def init_paper_wallet(self):
        if not os.path.exists(self.paper_wallet_file):
            wallet = {"idr": getattr(config, 'INITIAL_PAPER_BALANCE', 10000000), "assets": {}}
            with open(self.paper_wallet_file, "w") as f: json.dump(wallet, f)

    def get_paper_balance(self):
        for _ in range(5): 
            try: 
                with open(self.paper_wallet_file, "r") as f: return json.load(f)
            except: time.sleep(0.1)
        return {"idr": 0, "assets": {}}

    def update_paper_wallet(self, idr_change, asset_name, asset_change):
        for _ in range(10):
            try:
                wallet = self.get_paper_balance()
                wallet["idr"] += idr_change
                current_asset = wallet["assets"].get(asset_name, 0)
                wallet["assets"][asset_name] = current_asset + asset_change
                with open(self.paper_wallet_file, "w") as f: json.dump(wallet, f)
                return wallet
            except: time.sleep(0.05)
        return None

    def run(self):
        self.log_queue.put({"type": "INFO", "data": f"{self.bot_id} (Smart Agent) Online."})
        self.sync_server_time()
        self.start_websocket_thread()
        time.sleep(1)
        
        while True:
            try:
                # 1. Manage Active Position (Priority)
                if self.active_order:
                    self.manage_active_position()
                
                # 2. Monitor Post-Trade (Re-Entry Strategy)
                elif self.post_trade_active:
                    self._monitor_post_trade()
                
                # 3. New Signal
                elif not self.signal_queue.empty():
                    sig = self.signal_queue.get()
                    if sig['type'] == 'BUY': self.smart_execute_buy(sig['data'])
                
                # Idle Status
                if not self.active_order and not self.post_trade_active:
                    self.current_activity = "IDLE"

                self.broadcast_status() 
                time.sleep(REFRESH_RATE)
            
            except Exception as e:
                self.log_queue.put({"type": "ERROR", "data": f"{self.bot_id} ERR: {e}"})
                time.sleep(5)

def start_agent(log_queue, signal_queue, notify_queue, bot_id):
    TradingAgent(log_queue, signal_queue, notify_queue, bot_id).run()