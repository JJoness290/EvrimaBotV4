import json
import re
import subprocess
import time
import traceback
import threading
import os
import sys
from pathlib import Path
from datetime import datetime
import paramiko

print("SCRIPT STARTED")

# =========================
# CONFIG FILE
# =========================
CONFIG_FILE = Path("config.json")

def load_config():
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text())
    return {
        "scan_interval": 5,
        "energy_per_interval": 10,
        "interval_minutes": 5
    }

def save_config(cfg):
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2))


# =========================
# SERVER CONFIG
# =========================
RCON_SCRIPT = r"C:\Users\joshu\Downloads\The-Isle-Evrima-Server-Tools-main\TheIsle_RCON.py"

IP = "68.168.208.54"
RCON_PORT = "11218"
RCON_PASSWORD = "qFHrZpel6qwF"

SFTP_HOST = "68.168.208.54"
SFTP_PORT = 11216
SFTP_USER = "server26449"
SFTP_PASSWORD = "LYcxz02dLm"

REMOTE_LOG = "server/TheIsle/Saved/Logs/TheIsle.log"

DATA_FILE = Path("player_data.json")
STATE_FILE = Path("player_state.json")
LOCAL_LOG_COPY = Path("latest_join_scan.log")


# =========================
# HELPERS
# =========================
def load_json(path, default):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except:
            return default
    return default

def save_json(path, data):
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


# =========================
# RCON
# =========================
def run_playerlist():
    cmd = [
        "python",
        RCON_SCRIPT,
        "--ip", IP,
        "--port", RCON_PORT,
        "--password", RCON_PASSWORD,
        "--command", "list",
    ]

    result = subprocess.run(cmd, input="\n", capture_output=True, text=True, timeout=20)
    return (result.stdout or "") + (result.stderr or "")


def parse_playerlist(raw_text):
    lines = [l.strip() for l in raw_text.splitlines() if l.strip()]

    ids, names = None, None

    for line in lines:
        if "," not in line:
            continue

        parts = [p.strip() for p in line.split(",") if p.strip()]

        if all(p.isdigit() for p in parts):
            ids = parts
        else:
            names = parts

    if not ids or not names:
        return {}

    return {ids[i]: names[i] for i in range(min(len(ids), len(names)))}


# =========================
# LOG BACKFILL
# =========================
def download_log():
    t = paramiko.Transport((SFTP_HOST, SFTP_PORT))
    t.connect(username=SFTP_USER, password=SFTP_PASSWORD)
    sftp = paramiko.SFTPClient.from_transport(t)
    sftp.get(REMOTE_LOG, str(LOCAL_LOG_COPY))
    sftp.close()
    t.close()


def find_join_times(current_players):
    try:
        download_log()
        log = LOCAL_LOG_COPY.read_text(errors="ignore")
    except Exception as e:
        print("LOG ERROR:", e)
        return {}

    result = {}
    pattern = re.compile(r"\[(.*?)\].*?\[(\d+)\]")

    for line in log.splitlines():
        m = pattern.search(line)
        if not m:
            continue

        eos = m.group(2)
        if eos not in current_players:
            continue

        try:
            dt = datetime.strptime(m.group(1), "%Y.%m.%d-%H.%M.%S")
            result[eos] = int(dt.timestamp())
        except:
            continue

    return result


# =========================
# TRACKING (INTERVAL ENERGY)
# =========================
def update(players):
    cfg = load_config()

    interval = cfg["interval_minutes"]
    energy_per_interval = cfg["energy_per_interval"]

    data = load_json(DATA_FILE, {})
    state = load_json(STATE_FILE, {"online_since": {}})

    now = int(time.time())
    online = state["online_since"]

    join_times = find_join_times({e: n for e, n in players.items() if e not in online})

    # JOIN
    for eos, name in players.items():
        data.setdefault(eos, {
            "name": name,
            "total_minutes": 0,
            "current_session_minutes": 0,
            "energy": 0,
            "sessions": 0
        })

        if eos not in online:
            online[eos] = join_times.get(eos, now)
            data[eos]["sessions"] += 1
            print(f"JOIN: {name}")

    # LEAVE
    for eos in list(online.keys()):
        if eos not in players:
            start = online[eos]
            minutes = (now - start) // 60

            data[eos]["total_minutes"] += minutes
            data[eos]["current_session_minutes"] = 0

            print(f"LEAVE: {data[eos]['name']} ({minutes} min)")
            del online[eos]

    # 🔥 LIVE ENERGY SYSTEM
    for eos in players:
        if eos in online:
            session_minutes = (now - online[eos]) // 60
            data[eos]["current_session_minutes"] = session_minutes

            total = data[eos]["total_minutes"]
            combined = total + session_minutes

            expected_energy = (combined // interval) * energy_per_interval

            if expected_energy > data[eos]["energy"]:
                gained = expected_energy - data[eos]["energy"]
                data[eos]["energy"] = expected_energy
                print(f"ENERGY (LIVE): {data[eos]['name']} +{gained}")

    state["online_since"] = online
    save_json(DATA_FILE, data)
    save_json(STATE_FILE, state)
    return data


def print_status(players, data):
    print(f"\n--- {datetime.now()} ---")
    print(f"Online: {len(players)}")

    for eos, name in players.items():
        p = data.get(eos, {})
        print(f"{name} | session={p.get('current_session_minutes',0)} | total={p.get('total_minutes',0)} | energy={p.get('energy',0)}")


# =========================
# MENU UI
# =========================
def menu():
    while True:
        print("\n=== CONTROL PANEL ===")
        print("1. Change scan interval")
        print("2. Restart bot")
        print("3. Reset logs")
        print("4. Show config")

        choice = input("> ")

        if choice == "1":
            new = int(input("New interval (sec): "))
            cfg = load_config()
            cfg["scan_interval"] = new
            save_config(cfg)
            print("Updated.")

        elif choice == "2":
            print("Restarting...")
            subprocess.Popen([sys.executable, __file__])
            os._exit(0)

        elif choice == "3":
            if DATA_FILE.exists(): DATA_FILE.unlink()
            if STATE_FILE.exists(): STATE_FILE.unlink()
            print("Reset complete.")

        elif choice == "4":
            print(load_config())


# =========================
# MAIN LOOP
# =========================
def run():
    print("Bot running...")

    threading.Thread(target=menu, daemon=True).start()

    while True:
        try:
            raw = run_playerlist()
            players = parse_playerlist(raw)

            if players:
                data = update(players)
                print_status(players, data)

        except Exception:
            print("CRASH — restarting...")
            traceback.print_exc()
            time.sleep(5)

        cfg = load_config()
        time.sleep(cfg["scan_interval"])


if __name__ == "__main__":
    run()