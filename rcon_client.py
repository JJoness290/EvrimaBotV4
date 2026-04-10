import subprocess

RCON_SCRIPT = r"C:\Users\joshu\Downloads\The-Isle-Evrima-Server-Tools-main\TheIsle_RCON.py"
IP = "68.168.208.54"
PORT = "11218"
PASSWORD = "qFHrZpel6qwF"


def run_rcon(command):
    result = subprocess.run([
        "python",
        RCON_SCRIPT,
        "--ip", IP,
        "--port", PORT,
        "--password", PASSWORD,
        "--command", command
    ], input="\n", capture_output=True, text=True)

    return result.stdout


def get_players():
    raw = run_rcon("list")

    lines = [l.strip() for l in raw.splitlines() if l.strip()]

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