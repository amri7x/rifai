import time
import requests
import multiprocessing
import sys
import os

# Fix Path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

class TelegramNotifier:
    def __init__(self, notify_queue):
        self.queue = notify_queue
        self.token = getattr(config, 'TELEGRAM_TOKEN', '')
        self.chat_id = getattr(config, 'TELEGRAM_CHAT_ID', '')
        self.enabled = getattr(config, 'ENABLE_TELEGRAM', False)
        self.api_url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        self.initial_capital = getattr(config, 'INITIAL_CAPITAL', 0)
        self.session_pnl = 0.0

    def send_message(self, message):
        if not self.enabled or not self.token or not self.chat_id:
            return
        
        try:
            payload = {
                'chat_id': self.chat_id,
                'text': message,
                'parse_mode': 'Markdown'
            }
            requests.post(self.api_url, data=payload, timeout=10)
        except Exception as e:
            print(f"TELEGRAM ERROR: {e}")

    def run(self):
        print("SYSTEM: Telegram Notifier Active...")

        if self.initial_capital == 0:
            print("WARNING: 'INITIAL_CAPITAL' di config.py belum diset atau 0.") 
            print("         Total Aset di Telegram mungkin tidak akurat.")

        while True:
            try:
                if not self.queue.empty():
                    packet = self.queue.get()
                    
                    # Format Pesan Laporan Penjualan
                    if packet['type'] == 'SALE_REPORT':
                        data = packet['data']

                        pnl_amount = data.get('pnl_amt', 0)
                        self.session_pnl += pnl_amount
                        
                        estimated_total_asset = self.initial_capital + self.session_pnl
                        if self.initial_capital == 0:
                            display_total = f"Rp {data['wallet']:,.0f} (IDR Only)"
                        else:
                            display_total = f"Rp {estimated_total_asset:,.0f}"
                        # Emoji berdasarkan PnL
                        icon = "🟢" if data['pnl_amt'] >= 0 else "🔴"

                        # Emoji untuk Total PnL Sesi
                        total_icon = "profit" if self.session_pnl >= 0 else "loss" # Opsional, logic visual
                        pnl_sign = "+" if self.session_pnl >= 0 else ""
                        buy_cap = data.get('buy_capital', 0)
                        sell_tot = data.get('sell_total', 0)
                        
                        msg = (
                            f"{icon} **LAPORAN PENJUALAN** {icon}\n\n"
                            f"🪙 **Aset:** {data['pair'].upper()}\n"
                            f"📈 **Strategy:** {data['strategy']}\n"
                            f"----------------------------\n"
                            f"💵 **Modal Beli:** Rp {buy_cap:,.0f} (@ {data['buy_price']:,.0f})\n"
                            f"💰 **Total Jual:** Rp {sell_tot:,.0f} (@ {data['sell_price']:,.0f})\n"
                            f"📊 **PnL Bersih:** {data['pnl_pct']:.2f}% (Rp {data['pnl_amt']:,.0f})\n"
                            f"----------------------------\n"
                            f"📅 **Waktu:** {data['time']}\n"
                            #f"----------------------------\n"
                            #f"💼 **Total Saldo:** Rp {data['wallet']:,.0f}\n"
                            #f"💰 **Est. Total Aset:** {display_total}\n"
                            #f"🏆 **Total PnL Sesi:** {pnl_sign}Rp {self.session_pnl:,.0f}"
                        )
                        self.send_message(msg)
                        
                time.sleep(1)
            except Exception as e:
                # print(f"Notifier Error: {e}") # Debugging
                time.sleep(5)

def start_notifier(notify_queue):
    bot = TelegramNotifier(notify_queue)
    bot.run()