import multiprocessing
import time
import sys
import os
from multiprocessing import Manager
from core.hq import Headquarters
from modules.recon_scanner import start_recon
from modules.pustaka import start_pustaka
from modules.research import start_research
from modules.agent import start_agent
from modules.buzz_detector import start_buzz_detector
from modules.notifier import start_notifier

# Fix Path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

max_r = getattr(config, 'SYSTEM_MAX_RESTARTS', None)

def start_hq(log_queue):
    hq_system = Headquarters(log_queue)
    hq_system.run()

def spawn_process(name, target, args):
    p = multiprocessing.Process(target=target, args=args, name=name)
    p.daemon = True
    return p

# Helper untuk Inject Manual Target
def inject_manual_targets(log_queue, target_queue):
    targets = getattr(config, 'MANUAL_TARGETS', [])
    if targets:
        log_queue.put({"type": "INFO", "data": f"SYSTEM: Injecting {len(targets)} Manual Targets..."})
        for pair in targets:
            # Format: "MANUAL_TARGET:pair_id|0"
            # Harga 0 karena agent nanti akan cek harga real-time sendiri
            msg = f"MANUAL_TARGET:{pair}|0" 
            target_queue.put({"type": "BUY", "data": msg})
            time.sleep(0.5)

def start_agent(log_queue, signal_queue, notify_queue, bot_id, shared_active_assets):
    # Pass shared list ke Class Agent
    from modules.agent import TradingAgent
    bot = TradingAgent(log_queue, signal_queue, notify_queue, bot_id)
    bot.shared_active_assets = shared_active_assets # Inject dependency
    bot.run()

if __name__ == "__main__":
    try:
        multiprocessing.set_start_method('spawn')
    except RuntimeError: pass
    
    manager = Manager()
    shared_active_assets = manager.list()
    log_queue = multiprocessing.Queue()
    data_queue = multiprocessing.Queue()
    notify_queue = multiprocessing.Queue()
    scalp_signal_queue = multiprocessing.Queue() 
    day_signal_queue = multiprocessing.Queue()
    special_signal_queue = multiprocessing.Queue()

    process_map = {}

    try:
        # 1. Start HQ
        p_hq = spawn_process("HQ-Dashboard", start_hq, (log_queue,))
        p_hq.start()
        process_map["HQ-Dashboard"] = {"process": p_hq, "target": start_hq, "args": (log_queue,), "restarts": 0}
        
        time.sleep(2) 
        log_queue.put({"type": "INFO", "data": "SYSTEM: Initializing Core Modules..."})

        # 1.5 Start Notifier (BARU)
        if config.ENABLE_TELEGRAM:
            p_notif = spawn_process("Telegram-Bot", start_notifier, (notify_queue,))
            p_notif.start()
            process_map["Telegram-Bot"] = {"process": p_notif, "target": start_notifier, "args": (notify_queue,), "restarts": 0}

        # 2. Start Core Systems (Termasuk BUZZ DETECTOR Baru)
        core_jobs = [
            ("Pustaka-DB", start_pustaka, (log_queue, data_queue)),
            ("Recon-Scanner", start_recon, (log_queue, data_queue)), 
            ("Buzz-Detector", start_buzz_detector, (log_queue, special_signal_queue)), 
            ("Research-Brain", start_research, (log_queue, scalp_signal_queue, day_signal_queue))
        ]

        for name, target, args in core_jobs:
            p = spawn_process(name, target, args)
            p.start()
            process_map[name] = {"process": p, "target": target, "args": args, "restarts": 0}
            time.sleep(1)

        # 3. Start SCALP Agents
        log_queue.put({"type": "INFO", "data": f"SYSTEM: Deploying {config.TOTAL_SCALP_AGENTS} SCALP Squad..."})
        for i in range(1, config.TOTAL_SCALP_AGENTS + 1):
            bot_name = f"Agent-Scalp-{i}"
            p = spawn_process(bot_name, start_agent, (log_queue, scalp_signal_queue, notify_queue, bot_name, shared_active_assets))
            p.start()
            process_map[bot_name] = {"process": p, "target": start_agent, "args": (log_queue, scalp_signal_queue, notify_queue, bot_name), "restarts": 0}
            time.sleep(0.5)

        # 4. Start DAY Agents 
        log_queue.put({"type": "INFO", "data": f"SYSTEM: Deploying {config.TOTAL_DAY_AGENTS} DAY Squad..."})
        for i in range(1, config.TOTAL_DAY_AGENTS + 1):
            bot_name = f"Agent-Day-{i}"
            p = spawn_process(bot_name, start_agent, (log_queue, day_signal_queue, notify_queue, bot_name, shared_active_assets))
            p.start()
            process_map[bot_name] = {"process": p, "target": start_agent, "args": (log_queue, day_signal_queue, notify_queue, bot_name), "restarts": 0}
            time.sleep(0.5)

        # 4.5 === START SPECIAL AGENTS (PENGGANTI HUNTER) ===
        total_specials = getattr(config, 'TOTAL_SPECIAL_AGENTS', 1)
        log_queue.put({"type": "INFO", "data": f"SYSTEM: Deploying {total_specials} SPECIAL OPS (Hunter) Agents..."})
        
        for i in range(1, total_specials + 1):
            # Beri nama keren agar terlihat beda di HQ
            bot_name = f"Agent-Spec-{i}" 
            
            # Perhatikan: Queue yang dipassing adalah special_signal_queue
            p = spawn_process(bot_name, start_agent, (log_queue, special_signal_queue, notify_queue, bot_name, shared_active_assets))
            p.start()
            process_map[bot_name] = {"process": p, "target": start_agent, "args": (log_queue, special_signal_queue, notify_queue, bot_name), "restarts": 0}

        # 5. INJECT MANUAL TARGETS (One Time)
        inject_manual_targets(log_queue, special_signal_queue)

        log_queue.put({"type": "SUCCESS", "data": "ARMY READY. SPECIAL OPS STANDBY."})

        # Monitoring Loop
        while True:
            time.sleep(5)
            for name, info in process_map.items():
                if not info['process'].is_alive():
                    if info['restarts'] < max_r:
                        log_queue.put({"type": "WARNING", "data": f"SYSTEM: {name} DIED. Reviving..."})
                        new_p = spawn_process(name, info['target'], info['args'])
                        new_p.start()
                        info['process'] = new_p
                        info['restarts'] += 1
                    else:
                        log_queue.put({"type": "CRITICAL", "data": f"SYSTEM: {name} GAVE UP."})
                        
    except KeyboardInterrupt:
        for name, info in process_map.items():
            info['process'].terminate()
        sys.exit(0)