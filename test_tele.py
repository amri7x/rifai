import requests

# Ganti dengan data Anda
TOKEN = "8538665559:AAETfoLOErBYOQNAECUN6hbvBpSVTh7Zi7Q"
CHAT_ID = "8380207878"

msg = "Halo Bos! Sistem Notifikasi Trading Siap."
url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"

try:
    data = {"chat_id": CHAT_ID, "text": msg}
    response = requests.post(url, data=data)
    print("Status:", response.json())
except Exception as e:
    print("Error:", e)