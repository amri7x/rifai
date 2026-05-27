import json
import time
import os
import sys
import random
from datetime import datetime

# --- KONFIGURASI FILE ---
FILE_TICKER = "mock_tickers.json"     # Dibaca oleh Buzz Detector
FILE_STREAM = "mock_stream.json"      # Dibaca oleh Hunter/Agent (sebagai pengganti WebSocket)

def load_json(filepath):
    if os.path.exists(filepath):
        try:
            with open(filepath, "r") as f: return json.load(f)
        except: return {}
    return {}

def save_json(filepath, data):
    try:
        with open(filepath, "w") as f:
            json.dump(data, f, indent=2)
        return True
    except Exception as e:
        print(f"❌ Gagal simpan {filepath}: {e}")
        return False

def init_files():
    """Memastikan file mock tersedia"""
    if not os.path.exists(FILE_TICKER):
        save_json(FILE_TICKER, {"tickers": {}})
    if not os.path.exists(FILE_STREAM):
        save_json(FILE_STREAM, {})
    print("✅ File Mock Siap.")

# --- GENERATOR DATA PALSU ---

def generate_orderbook(price, trend="bullish"):
    """
    Membuat Orderbook palsu.
    - Bullish: Tembok Beli tebal, Spread tipis.
    - Bearish/Trap: Tembok Jual tebal, Spread lebar.
    """
    bids = []
    asks = []
    
    # Setting Spread
    spread_pct = 0.5 if trend == "bullish" else 2.5 # Bullish spread 0.5%, Trap 2.5%
    ask_price = price * (1 + spread_pct/100)
    
    # Generate 10 Layer
    for i in range(10):
        # BIDS (Orang mau beli)
        bid_p = price - (i * (price * 0.001))
        bid_v = random.randint(100, 500) * 1_000_000 if trend == "bullish" else random.randint(10, 50) * 1_000_000
        bids.append({"price": str(bid_p), "idr_volume": str(bid_v)})
        
        # ASKS (Orang mau jual)
        ask_p = ask_price + (i * (ask_price * 0.001))
        ask_v = random.randint(10, 50) * 1_000_000 if trend == "bullish" else random.randint(200, 800) * 1_000_000
        asks.append({"price": str(ask_p), "idr_volume": str(ask_v)})
        
    return {"bids": bids, "asks": asks}

def generate_trades(price, trend="bullish"):
    """
    Membuat Trade History palsu.
    - Bullish: Banyak 'buy', volume besar.
    - Bearish: Banyak 'sell', volume kecil/jarang.
    """
    trades = []
    count = 15 if trend == "bullish" else 5
    
    for i in range(count):
        side = "buy" if trend == "bullish" and random.random() > 0.2 else "sell"
        trade_price = price * random.uniform(0.99, 1.01)
        vol = random.randint(5, 50) * 1_000_000
        
        # Format Indodax Trade: [id, time, unknown, side, price, vol, unknown]
        # Kita sesuaikan dengan format yang dibaca Hunter (dict)
        trades.append({
            "side": side,
            "price": trade_price,
            "vol_idr": vol,
            "time": str(datetime.now())
        })
    return trades

# --- SKENARIO ---

def scenario_perfect_pump(pair):
    """Skenario: Harga naik, Volume naik, Orderbook Bagus (Validasi Hunter Lolos)"""
    print(f"\n🚀 MENYUNTIKKAN 'PERFECT PUMP' ke {pair}...")
    
    # 1. Update TICKER (Untuk Buzz Detector)
    tickers = load_json(FILE_TICKER)
    current_tickers = tickers.get("tickers", {})
    
    # Setup data dasar jika belum ada
    if pair not in current_tickers:
        base_price = 1000
        base_vol = 1_000_000_000
    else:
        base_price = float(current_tickers[pair]['last'])
        base_vol = float(current_tickers[pair]['vol_idr'])

    new_price = base_price * 1.05 # Naik 5%
    new_vol = base_vol + 200_000_000 # Tambah 200 Juta Volume
    
    current_tickers[pair] = {
        "last": str(int(new_price)),
        "vol_idr": str(int(new_vol)),
        "high": str(int(new_price)),
        "buy": str(int(new_price)),
        "sell": str(int(new_price*1.01)),
        "server_time": int(time.time()*1000)
    }
    save_json(FILE_TICKER, {"tickers": current_tickers})
    print(f"   ✅ Ticker Updated: Harga +5%, Vol +200jt (Pemicu Scanner)")

    # 2. Update STREAM (Untuk Hunter Agent)
    stream_data = load_json(FILE_STREAM)
    
    stream_data[pair] = {
        "orderbook": generate_orderbook(new_price, trend="bullish"),
        "trades": generate_trades(new_price, trend="bullish")
    }
    save_json(FILE_STREAM, stream_data)
    print(f"   ✅ Stream Updated: Orderbook Tebal Beli, Trade Rame Buy (Pemicu Hunter)")
    print("   👉 Segera cek log Hunter/Agent!")

def scenario_fake_pump(pair):
    """Skenario: Harga naik, tapi Orderbook Jelek (Hunter harus Reject)"""
    print(f"\n⚠️ MENYUNTIKKAN 'FAKE PUMP / TRAP' ke {pair}...")
    
    # 1. Update TICKER (Scanner akan mendeteksi ini sebagai sinyal)
    tickers = load_json(FILE_TICKER)
    current_tickers = tickers.get("tickers", {})
    
    if pair not in current_tickers: base_price = 1000; base_vol = 1_000_000_000
    else: base_price = float(current_tickers[pair]['last']); base_vol = float(current_tickers[pair]['vol_idr'])

    new_price = base_price * 1.03 # Naik 3%
    new_vol = base_vol + 100_000_000
    
    current_tickers[pair] = {
        "last": str(int(new_price)),
        "vol_idr": str(int(new_vol)),
        "high": str(int(new_price)),
        "server_time": int(time.time()*1000)
    }
    save_json(FILE_TICKER, {"tickers": current_tickers})
    print(f"   ✅ Ticker Updated: Pemicu Scanner Terkirim")

    # 2. Update STREAM (Hunter akan melihat ini jelek)
    stream_data = load_json(FILE_STREAM)
    stream_data[pair] = {
        "orderbook": generate_orderbook(new_price, trend="bearish"), # Spread lebar, Tembok Jual
        "trades": generate_trades(new_price, trend="bearish") # Sepi
    }
    save_json(FILE_STREAM, stream_data)
    print(f"   ✅ Stream Updated: Orderbook Jelek (Spread Lebar/Tembok Jual)")
    print("   👉 Hunter seharusnya me-REJECT sinyal ini.")

def main():
    init_files()
    while True:
        print("\n==========================================")
        print("   🎮 GOD MODE SIMULATOR (V3 - FULL STACK)")
        print("==========================================")
        print("1. Inject PERFECT PUMP (Scanner ✅ -> Hunter ✅ -> Agent BUY)")
        print("2. Inject FAKE PUMP (Scanner ✅ -> Hunter ❌ Reject)")
        print("3. Reset Data")
        print("4. Keluar")
        
        pilihan = input("\nPilih Menu (1-4): ")

        if pilihan == "4": sys.exit()
        
        if pilihan == "3":
            save_json(FILE_TICKER, {"tickers": {}})
            save_json(FILE_STREAM, {})
            print("Data di-reset.")
            continue

        pair = input("Masukkan Nama Koin (misal: btc_idr): ").lower()
        if not pair.endswith("_idr"): pair += "_idr"

        if pilihan == "1":
            scenario_perfect_pump(pair)
        elif pilihan == "2":
            scenario_fake_pump(pair)

if __name__ == "__main__":
    main()