import time
import keyboard
import sys
import os
from rich.console import Console
from rich.table import Table
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.text import Text
from rich.align import Align
from rich import box
from datetime import datetime

# Fix Path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

class Headquarters:
    def __init__(self, msg_queue):
        self.queue = msg_queue
        self.logs = []
        self.signals = []


        ##self.wallet_info = "Connecting..."
        self.total_pnl = 0.0
        self.wallet_balance = 0.0
        self.trading_mode = "PAPER" if getattr(config, 'PAPER_MODE', True) else "REAL"
        
        # Init Data Agent
        self.agents_data = {}
        for i in range(1, config.TOTAL_SCALP_AGENTS + 1):
            self.agents_data[f"Agent-Scalp-{i}"] = {"status": "BOOTING", "position": None, "activity": "INIT"}
        for i in range(1, config.TOTAL_DAY_AGENTS + 1):
            self.agents_data[f"Agent-Day-{i}"] = {"status": "BOOTING", "position": None, "activity": "INIT"}
        total_specials = getattr(config, 'TOTAL_SPECIAL_AGENTS', 1)
        for i in range(1, total_specials + 1):
            self.agents_data[f"Agent-Spec-{i}"] = {"status": "BOOTING", "position": None, "activity": "INIT"}

        # --- NEW: Init Data Hunter ---
        self.hunter_data = {
            "status": "IDLE",
            "target": "-",
            "detail": "System Start",
            "timestamp": "-"
        }

        # --- NEW: Scroll Control ---
        self.scroll_offset = 0

    def make_layout(self):
        layout = Layout()
        layout.split(
            Layout(name="header", size=4),
            Layout(name="body", ratio=1)
        )

        # --- MODIFIED: Struktur Utama (Kiri vs Kanan) ---
        layout["body"].split_row(
            Layout(name="left_panel", ratio=4),  # Panel Kiri menampung Logs + Signal
            Layout(name="agents_grid", ratio=8)  # Panel Kanan menampung Squad + Hunter
        )
        
        # --- Bagian Kiri: Logs (Atas) & Signals (Bawah) ---
        layout["left_panel"].split_column(
            Layout(name="logs", ratio=7),       # Logs mendapat porsi lebih besar
            Layout(name="signals_box", ratio=3) # Signals dipindah ke sini (bawah logs)
        )

        return layout

    def generate_header(self):
        # Warna PnL (Hijau jika untung, Merah jika rugi)
        pnl_color = "bright_green" if self.total_pnl >= 0 else "bold red"
        pnl_sign = "+" if self.total_pnl >= 0 else ""
        
        # Grid untuk Header (Biar Rapi)
        grid = Table.grid(expand=True)
        grid.add_column(justify="center", ratio=1)
        
        # Baris 1: Judul
        grid.add_row(f"[bold white]INDODAX ARMY BOT V3[/bold white] | [bold yellow]COMMANDER MODE ({self.trading_mode})[/bold yellow]")
        
        # Baris 2: Statistik Uang (SALDO & PNL)
        stats_text = (
            f"💰 SALDO: [bold cyan]Rp {self.wallet_balance:,.0f}[/bold cyan]   |   "
            f"🏆 PnL SESI: [{pnl_color}]{pnl_sign}Rp {self.total_pnl:,.0f}[/{pnl_color}]"
        )
        grid.add_row(stats_text)
        
        return Panel(grid, style="on blue")

    def generate_agent_table(self):
        grid = Table(box=box.SIMPLE_HEAD, expand=True, show_edge=False)
        # [UPDATE] Kolom Agent ID kita lebarkan sedikit
        grid.add_column("Agent ID", style="bold white", width=22) 
        grid.add_column("Status", width=12, justify="left") 
        grid.add_column("Asset/Strat", style="cyan", width=12)
        grid.add_column("Entry", justify="right", width=10)
        grid.add_column("Now", justify="right", width=10)
        grid.add_column("PnL", justify="right", width=8)
        grid.add_column("Trailing", justify="right", style="dim")

        sorted_keys = sorted(self.agents_data.keys(), key=lambda x: (x.split('-')[1], x))
        
        for bot_id in sorted_keys:
            data = self.agents_data[bot_id]
            status = data.get('status', 'UNKNOWN')
            pos = data.get('position')
            conn = data.get('connection', 'API')
            activity = data.get('activity', 'IDLE')
            act_color = "dim white"
            val_suffix = ""

            # --- LOGIKA PEWARNAAN ID AGENT (BARU) ---
            id_color = "white" # Default (untuk Agent-Day atau lainnya)
            
            if "Scalp" in bot_id:
                id_color = "yellow"
            elif "Spec" in bot_id: # Spec adalah pengganti Hunter/Special Ops
                id_color = "bold red"
            
            # Terapkan warna ke bot_id
            formatted_bot_id = f"[{id_color}]{bot_id}[/{id_color}]"
            # ----------------------------------------

            if "VALIDATING" in activity: act_color = "bold yellow"
            elif "BUY" in activity: act_color = "bold cyan"
            elif "SELL" in activity: act_color = "bold red"
            elif "HOLDING" in activity:
                act_color = "green"
                if pos:
                    curr_val = pos.get('current_value', 0)
                    if curr_val > 0:
                        val_suffix = f" Rp {curr_val:,.0f}"

            agent_display = f"{formatted_bot_id}\n[{act_color}]{activity}{val_suffix}[/{act_color}]"

            if status == "ACTIVE": base_txt = "[bold green]TRADING[/bold green]"
            elif status == "IDLE": base_txt = "[dim green]STANDBY[/dim green]"
            elif status == "BOOTING": base_txt = "[yellow]BOOTING..[/yellow]"
            else: base_txt = "[red]OFFLINE[/red]"
            
            conn_color = "cyan" if conn == "WS" else "yellow"
            status_txt = f"{base_txt} [{conn_color}]({conn})[/{conn_color}]"
            
            if pos:
                strat = pos.get('strategy', 'MANUAL')
                pair = pos.get('pair', '???').upper()
                strat_color = "magenta" if "SCALP" in strat else "blue"
                asset_txt = f"{pair}\n[{strat_color}]{strat}[/{strat_color}]"
                entry_txt = f"{pos.get('entry', 0):,.0f}"
                now_txt = f"[bold]{pos.get('current', 0):,.0f}[/bold]"
                pnl_val = pos.get('pnl_pct', 0)
                pnl_color = "bright_green" if pnl_val >= 0 else "red"
                pnl_txt = f"[{pnl_color}]{pnl_val:+.2f}%[/{pnl_color}]"
                trail_txt = f"H:{pos.get('highest', 0):,.0f}\nS:[red]{pos.get('stop_loss', 0):,.0f}[/red]"
            else:
                asset_txt, entry_txt, now_txt, pnl_txt, trail_txt = ("-", "-", "-", "-", "-")

            # [UPDATE] Gunakan agent_display sebagai kolom pertama
            grid.add_row(agent_display, status_txt, asset_txt, entry_txt, now_txt, pnl_txt, trail_txt)
            grid.add_row("", "", "", "", "", "", "", end_section=True)

        return Panel(grid, title=f"[bold yellow]ACTIVE SQUAD MONITOR[/bold yellow]", border_style="blue")

    def generate_log_panel(self):
        text = Text()
        height = 20 # Jumlah baris log yang ditampilkan

        # Logika Scrolling
        total_logs = len(self.logs)
        if self.scroll_offset == 0:
            # Mode Auto-Scroll (Tampilkan paling baru)
            visible_logs = self.logs[-height:]
            title_status = ""
            border_col = "white"
        else:
            # Mode History (User sedang scroll ke atas)
            # Hitung start dan end index dari belakang
            end_index = -self.scroll_offset
            start_index = end_index - height
            if end_index == 0: end_index = None # Fix slicing bug
            # Handling slice python agar tidak error
            # Jika start_index terlalu jauh, python handle otomatis, tapi kita rapikan:
            visible_logs = self.logs[start_index:end_index]
            
            title_status = f"[bold yellow](HISTORY -{self.scroll_offset})[/bold yellow]"
            border_col = "yellow"

        for log in visible_logs: 
            ts = log['time']
            msg = str(log['msg'])
            lvl = log['level']
            color = "white"
            if lvl == "ERROR": color = "red"
            elif lvl == "SUCCESS": color = "green"
            elif lvl == "WARNING": color = "yellow"
            elif lvl == "SIGNAL": color = "cyan"
            elif "CRITICAL" in lvl: color = "bold red"
            text.append(f"{ts} ", style="dim")
            text.append(f"{msg}\n", style=color)
            
        return Panel(text, title=f"SYSTEM LOGS {title_status}", border_style=border_col)

        for log in self.logs[-20:]: 
            ts = log['time']
            msg = str(log['msg'])
            lvl = log['level']
            color = "white"
            if lvl == "ERROR": color = "red"
            elif lvl == "SUCCESS": color = "green"
            elif lvl == "WARNING": color = "yellow"
            elif lvl == "SIGNAL": color = "cyan"
            elif "CRITICAL" in lvl: color = "bold red"
            text.append(f"{ts} ", style="dim")
            text.append(f"{msg}\n", style=color)
        return Panel(text, title="SYSTEM LOGS", border_style="white")

    def run(self):
        layout = self.make_layout()
        #layout["header"].update(Panel(Align.center("[bold white]INDODAX ARMY BOT V3 - COMMANDER MODE[/]"), style="on blue"))

        # Info navigasi untuk user
        print("Tekan [PANAH ATAS] untuk scroll log lama, [END] atau [PANAH BAWAH] mentok untuk kembali ke auto-scroll.")

        with Live(layout, refresh_per_second=4, screen=True) as live:
            while True:
                # --- NEW: Keyboard Listeners ---
                # Cek apakah user menekan tombol Panah Atas
                if keyboard.is_pressed('up'):
                    # Batasi agar tidak scroll melebihi jumlah log yang ada
                    if self.scroll_offset < len(self.logs) - 20:
                        self.scroll_offset += 1
                
                # Cek apakah user menekan tombol Panah Bawah
                if keyboard.is_pressed('down'):
                    if self.scroll_offset > 0:
                        self.scroll_offset -= 1
                
                # Cek tombol END (Reset ke paling bawah/terbaru)
                if keyboard.is_pressed('end'):
                    self.scroll_offset = 0
                # -------------------------------

                while not self.queue.empty():
                    packet = self.queue.get()
                    ts = datetime.now().strftime("%H:%M:%S")
                    
                    # 1. Update Agent Scalp/Day
                    if packet.get('type') == 'AGENT_UPDATE':
                        b_id = packet.get('bot_id')
                        d = packet.get('data')
                        self.agents_data[b_id] = d 
                        self.wallet_balance = d.get('wallet_idr', 0)
                        continue

                    if packet.get('type') == 'PNL_UPDATE':
                        amount = packet.get('amount', 0)
                        self.total_pnl += amount
                        continue
                    
                    # 2. Update Hunter (NEW)
                    if packet.get('type') == 'HUNTER_UPDATE':
                        self.hunter_data = packet.get('data')
                        continue 

                    msg = packet.get('data', '')
                    if packet.get('type') == 'SIGNAL':
                        self.signals.append(f"{ts} | {msg}")
                    
                    self.logs.append({"time": ts, "level": packet.get('type', 'INFO'), "msg": msg})


                # === PERBAIKAN HEADER ===
                pnl_color = "bright_green" if self.total_pnl >= 0 else "bold red"
                pnl_sign = "+" if self.total_pnl >= 0 else ""
                
                # Format Rupiah yang rapi
                txt_saldo = f"SALDO: Rp {self.wallet_balance:,.0f}"
                txt_pnl = f"PnL SESI: [{pnl_color}]{pnl_sign}Rp {self.total_pnl:,.0f}[/{pnl_color}]"

                header_text = f"[bold white]INDODAX ARMY BOT V3[/bold white] | [bold yellow]COMMANDER MODE[/bold yellow]"
                sub_header = Align.center(f"{txt_saldo}  |  {txt_pnl}")
                
                # Combine title dan stats
                grid_header = Table.grid(expand=True)
                grid_header.add_column(justify="center", ratio=1)
                grid_header.add_row(header_text)
                grid_header.add_row(sub_header)

                layout["header"].update(Panel(grid_header, style="on blue"))
                # ==========================
                
                #header_text = f"[bold white]INDODAX ARMY BOT V3[/bold white] | [bold yellow]COMMANDER MODE[/bold yellow]"
                #sub_header = f"TOTAL REALIZED PnL: [{pnl_color}]{pnl_sign}Rp {self.total_pnl:,.0f}[/{pnl_color}]"
                
                #combined_header = Align.center(f"{header_text}\n{sub_header}")
                #layout["header"].update(Panel(combined_header, style="on blue"))
                # ==========================

                
                # Render Semua Panel Bawah
                layout["header"].update(self.generate_header())
                layout["logs"].update(self.generate_log_panel())
                layout["agents_grid"].update(self.generate_agent_table())
                
                sig_text = Text()
                if not self.signals:
                    sig_text.append("Scanning Market...", style="dim italic")
                else:
                    for s in self.signals[-6:]: 
                        sig_text.append(f"{s}\n", style="cyan")
                        
                layout["signals_box"].update(Panel(sig_text, title="LATEST SIGNALS", border_style="magenta"))
                
                time.sleep(0.05)