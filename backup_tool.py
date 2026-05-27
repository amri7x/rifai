import os
import shutil
import time
from datetime import datetime

# === KONFIGURASI ===
SOURCE_DIR = os.getcwd() # Folder saat ini
BACKUP_ROOT_DIR = os.path.join(SOURCE_DIR, "#Backups_Project") # Folder tujuan

# Daftar folder/file yang TIDAK PERLU dibackup (untuk menghemat tempat)
IGNORE_LIST = [
    '#Backups_Project', # Jangan backup folder backup itu sendiri (looping)
    '__pycache__',     # File sampah Python
    '.git',            # Git folder
    'venv',            # Virtual Environment
    '.idea',           # Settingan Editor
    '.vscode'
]

# Apakah database CSV perlu dibackup? 
# False = Hanya backup skrip (Lebih cepat & ringan)
# True = Backup skrip + data history (Berat)
BACKUP_DATABASE = False 

def get_next_backup_name():
    """Menghitung urutan backup dan membuat nama folder."""
    if not os.path.exists(BACKUP_ROOT_DIR):
        os.makedirs(BACKUP_ROOT_DIR)
        return "backup-1"

    # Hitung folder yang sudah ada yang diawali "backup-"
    existing_folders = [f for f in os.listdir(BACKUP_ROOT_DIR) 
                        if os.path.isdir(os.path.join(BACKUP_ROOT_DIR, f)) 
                        and f.startswith("backup-")]
    
    # Ambil angka terbesar
    max_num = 0
    for folder in existing_folders:
        try:
            # Format nama: backup-1 (Waktu...)
            # Kita ambil angka setelah dash pertama
            parts = folder.split(' ')[0] # Ambil "backup-X"
            num = int(parts.split('-')[1])
            if num > max_num:
                max_num = num
        except:
            continue
            
    return f"backup-{max_num + 1}"

def custom_ignore(path, names):
    """Filter pintar untuk menentukan file mana yang harus dicopy."""
    ignored_names = []
    
    for name in names:
        # 1. Cek Ignore List Utama
        if name in IGNORE_LIST:
            ignored_names.append(name)
        
        # 2. Cek File Database (Jika config BACKUP_DATABASE = False)
        # Kita asumsikan file database berekstensi .csv ada di folder 'database'
        if not BACKUP_DATABASE and name.endswith('.csv') and 'database' in path:
            ignored_names.append(name)

    return ignored_names

def run_backup():
    print(f"[{datetime.now().strftime('%H:%M:%S')}] MEMULAI PROSES BACKUP...")
    
    # 1. Siapkan Nama
    sequence_name = get_next_backup_name()
    timestamp = datetime.now().strftime("%Y-%m-%d %H-%M-%S")
    full_folder_name = f"{sequence_name} ({timestamp})"
    
    dest_path = os.path.join(BACKUP_ROOT_DIR, full_folder_name)
    
    # 2. Eksekusi Copy
    try:
        shutil.copytree(SOURCE_DIR, dest_path, ignore=custom_ignore)
        print(f"SUCCESS! Backup berhasil disimpan di:")
        print(f"📂 {dest_path}")
        print("-" * 30)
    except Exception as e:
        print(f"GAGAL: Terjadi kesalahan saat backup - {e}")

if __name__ == "__main__":
    run_backup()
    # Biarkan window terbuka sebentar agar user bisa baca status
    input("Tekan Enter untuk keluar...")