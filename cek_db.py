import sqlite3
import os

# Lokasi database
db_path = "pustaka/database/market_data.db"

if not os.path.exists(db_path):
    print(f"❌ File database tidak ditemukan di: {db_path}")
    print("Pastikan bot sudah dijalankan minimal sekali.")
else:
    print(f"✅ Membuka database: {db_path}...\n")
    try:
        # Koneksi ke database
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # 1. Cek Daftar Tabel
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = cursor.fetchall()
        print(f"📂 Daftar Tabel: {tables}")

        # 2. Cek Isi Tabel 'candles' (5 Data Terakhir)
        if ('candles',) in tables:
            print("\n📊 5 Data Terakhir di tabel 'candles':")
            print(f"{'PAIR':<10} | {'TF':<5} | {'TIMESTAMP':<15} | {'CLOSE':<12} | {'VOLUME'}")
            print("-" * 65)
            
            cursor.execute("SELECT pair, timeframe, timestamp, close, volume FROM candles ORDER BY timestamp DESC LIMIT 5")
            rows = cursor.fetchall()
            
            if not rows:
                print("⚠️ Tabel masih kosong. Tunggu bot berjalan beberapa saat.")
            
            for row in rows:
                # row[2] adalah timestamp, bisa kita format jika mau
                print(f"{row[0]:<10} | {row[1]:<5} | {row[2]:<15} | {row[3]:<12} | {row[4]}")
        else:
            print("\n⚠️ Tabel 'candles' belum dibuat.")

        conn.close()

    except Exception as e:
        print(f"❌ Error: {e}")