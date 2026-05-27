# config.py

# === MODE SIMULASI (PAPER TRADING) ===
# Set True untuk simulasi, False untuk trading uang asli
PAPER_MODE = True  
INITIAL_PAPER_BALANCE = 500_000 # Modal palsu
INITIAL_CAPITAL = 500_000  # Modal acuan

# === SYSTEM & NETWORK ===
INDODAX_WS_URL = "wss://ws3.indodax.com/ws/"
INDODAX_API_URL = "https://indodax.com"
INDODAX_HISTORY_OHLC = "https://indodax.com/tradingview/history_v2"
# Token WS sering berubah, pastikan update berkala atau buat mekanisme auto-fetch
WS_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJleHAiOjE5NDY2MTg0MTV9.UR1lBM6Eqh0yWz-PVirw1uPCxe60FdchR8eNVdsskeo"

# ======= Global Time Refresh ===== #
REFRESH_RATE = 3.0
SYSTEM_LOOP_DELAY = 1.0
SYSTEM_MAX_RESTARTS = 5

# === KREDENSIAL API (WAJIB DIISI) ===
INDODAX_API_KEY = "My_Api_Key"
INDODAX_SECRET_KEY = "My_Secret_Key"

# === TELEGRAM NOTIFICATION ===
ENABLE_TELEGRAM = False
TELEGRAM_TOKEN = "8538665559:AAETfoLOErBYOQNAECUN6hbvBpSVTh7Zi7Q" 
TELEGRAM_CHAT_ID = "8380207878"

# === FOLDER SISTEM ===
DATABASE_DIR = "pustaka/database"

# === FILTER ASET ===
BASE_CURRENCY = "_idr"
WHITELIST = []
BLACKLIST = [
    'btc_idr', 'eth_idr',      # Market Cap Raksasa (Lambat)
    'usdt_idr', 'usdc_idr',    # Stable Coin
    'busd_idr', 'idrt_idr',    
    'usdp_idr', 'paxg_idr',    
    'dai_idr']

# ======== Recon Scanner  ========== #
TIMEFRAME = 1       
MIN_VOL_IDR = 800_000_000
MIN_PRICE = 50                
MIN_DAILY_VOLATILITY = 1.0    
RECON_MAX_CANDIDATES = 15

# === BUZZ DETECTOR ===
BUZZ_MIN_VOL_CHANGE = 50_000_000  
BUZZ_MIN_PRICE_CHANGE = 1.5       
BUZZ_SCAN_INTERVAL = 3            
BUZZ_MIN_DAILY_VOL = 500_000_000  

# === KONFIGURASI HUNTER ===
HUNTER_OBSERVATION_TIME = 5     
HUNTER_MAX_RETRIES = 5          
HUNTER_MIN_TRADES = 3           
HUNTER_MIN_BUY_RATIO = 0.6      
HUNTER_MAX_SPREAD = 1.5         
HUNTER_MAX_WALL_RATIO = 3.0     

# --- CONFIG AGENT INTELLIGENCE ---
TOTAL_SCALP_AGENTS = 5
TOTAL_DAY_AGENTS = 1
AGENT_OBSERVATION_CYCLES = 15     
AGENT_OBSERVATION_TIME = 2       
AGENT_MAX_SPREAD = 2.0           
AGENT_MAX_WALL_RATIO = 5.0       
AGENT_MIN_BUY_RATIO = 0.30        
TRAILING_STOP_PERCENT = 1.5      

# === RISK MANAGEMENT ===
BUY_AMOUNT_MIN = 50_000    
BUY_AMOUNT_MAX = 80_000    
HARD_STOP_LOSS_PERCENT = 1.5       
TRAILING_ACTIVATION_PERCENT = 2  

# === AGENT SAFETY FILTER (ANTI PUCUK) ===
AGENT_RSI_MAX = 75.0            
AGENT_EMA_TOLERANCE_PCT = 2.5   

# === INDODAX FEE (PAJAK) ===
# Fee ini akan digunakan Agent untuk menghitung Net Profit real
FEE_TAKER = 0.0051  # 0.51% (Market Order - Kena saat Jual/Beli Instant)
FEE_MAKER = 0.0031  # 0.31% (Limit Order - Kena saat Pasang Jaring)

# === SENTIMEN PASAR ===
ENABLE_SENTIMENT = True
SENTIMENT_API_URL = "https://api.alternative.me/fng/"
SENTIMENT_UPDATE_INTERVAL = 600 
MAX_GREED_ALLOWED = 80          

# ======== RESEARCH PARAMETERS ======== #
HISTORY_LOOKBACK_SECONDS = 86400    
EMA_PERIOD = 20                 
VOLUME_MA_PERIOD = 20           
DB_LOAD_LIMIT = 50              
RSI_PERIOD = 14                 
RSI_OVERBOUGHT = 70             
RSI_OVERSOLD = 45               

# === STRATEGI 1: SCALPING ===
SCALP_ENABLE = True
SCALP_TIMEFRAME = '1min'
SCALP_PROFIT_TARGET = 2.5       
SCALP_VOL_MULTIPLIER = 2.5      
SCALP_MIN_VALUE_IDR = 2_000_000 

# === STRATEGI 2: DAY TRADE ===
DAY_ENABLE = True
DAY_TIMEFRAME = '3min'          
DAY_PROFIT_TARGET = 5.0         
DAY_MOMENTUM_PERIOD = 5         
DAY_VOL_MULTIPLIER = 1.2        
DAY_MIN_VALUE_IDR = 2_000_000      

# === SPECIAL OPS ===
TOTAL_SPECIAL_AGENTS = 1  
SPECIAL_STRATEGY_LABEL = "MOMENTUM" 
MANUAL_TARGETS = []

# =========================================================
# === KONFIGURASI POST-TRADE (RE-ENTRY STRATEGY) - BARU ===
# =========================================================
# Fitur agar Agent tidak langsung kabur setelah jual, tapi cari pantulan
ENABLE_POST_TRADE_WATCH = True

# Durasi maksimal menunggu pantulan setelah jual (detik)
POST_TRADE_WAIT_TIME = 900  # 15 Menit

# Parameter Bollinger Band untuk Shadow Limit (Menangkap Pisau Jatuh)
POST_TRADE_BB_PERIOD = 20
POST_TRADE_BB_STD = 2.0

# Jarak toleransi Reclaim (Buffer 0.2%)
# Harga harus naik sedikit di atas garis Bawah Bollinger untuk validasi buy
POST_TRADE_RECLAIM_BUFFER = 0.2