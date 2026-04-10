import time
import json
from pathlib import Path
from db import init_db
from tracker import Tracker, handle_growth
from rcon_client import get_players

PLAYER_DATA_FILE = Path("player_data.json")


def load_json(path: Path, default):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return default
    return default


def print_live_status(players):
    data = load_json(PLAYER_DATA_FILE, {})

    print(f"\n--- Online: {len(players)} ---")
    for steam_id, name in players.items():
        p = data.get(steam_id, {})
        session = int(p.get("current_session_minutes", 0))
        total = int(p.get("total_minutes", 0))
        energy = int(p.get("energy", 0))

        print(
            f"{name} | "
            f"{steam_id} | "
            f"session={session} mins | "
            f"total={total} mins | "
            f"energy={energy}"
        )


def main():
    init_db()
    tracker = Tracker()

    while True:
        try:
            players = get_players()

            tracker.update_players(players)
            tracker.tick()
            handle_growth(players)

            print_live_status(players)

        except Exception as e:
            print("ERROR:", e)

        time.sleep(5)


if __name__ == "__main__":
    main()