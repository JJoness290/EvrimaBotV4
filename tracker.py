import json
import time
from pathlib import Path

PLAYER_DATA_FILE = Path("player_data.json")

REWARD_INTERVAL_MINUTES = 60
REWARD_AMOUNT = 15


def load_json(path: Path, default):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return default
    return default


def save_json(path: Path, data):
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def handle_growth(players):
    # Prime/claim delivery is handled by discord_bot.py + game_admin_bridge.py
    return


class Tracker:
    def __init__(self):
        self.online_since = {}
        self.last_minute_tick = {}

    def update_players(self, players):
        """
        players = {steam_id: player_name}
        Keeps player_data.json in sync and preserves previous playtime across rejoins.
        """
        data = load_json(PLAYER_DATA_FILE, {})
        now = int(time.time())
        current_ids = set(players.keys())

        # Add / refresh online players
        for steam_id, name in players.items():
            if steam_id not in data:
                data[steam_id] = {
                    "name": name,
                    "steam_id": steam_id,
                    "total_minutes": 0,
                    "current_session_minutes": 0,
                    "energy": 0,
                    "sessions": 0,
                }

            data[steam_id]["name"] = name
            data[steam_id]["steam_id"] = steam_id

            if steam_id not in self.online_since:
                self.online_since[steam_id] = now
                self.last_minute_tick[steam_id] = now
                data[steam_id]["sessions"] = int(data[steam_id].get("sessions", 0)) + 1

            session_minutes = (now - self.online_since[steam_id]) // 60
            data[steam_id]["current_session_minutes"] = int(session_minutes)

        # Players who left
        for steam_id in list(self.online_since.keys()):
            if steam_id not in current_ids:
                if steam_id in data:
                    data[steam_id]["current_session_minutes"] = 0
                del self.online_since[steam_id]
                self.last_minute_tick.pop(steam_id, None)

        save_json(PLAYER_DATA_FILE, data)

    def tick(self):
        """
        Awards 15 energy per 60 minutes total playtime.
        Persists total playtime across leaving/rejoining.
        """
        data = load_json(PLAYER_DATA_FILE, {})
        now = int(time.time())

        for steam_id in list(self.online_since.keys()):
            if steam_id not in data:
                continue

            last_tick = self.last_minute_tick.get(steam_id, now)
            elapsed = now - last_tick

            if elapsed < 60:
                continue

            whole_minutes = elapsed // 60
            if whole_minutes <= 0:
                continue

            player = data[steam_id]

            old_total = int(player.get("total_minutes", 0))
            new_total = old_total + whole_minutes

            old_rewards = old_total // REWARD_INTERVAL_MINUTES
            new_rewards = new_total // REWARD_INTERVAL_MINUTES
            gained_energy = (new_rewards - old_rewards) * REWARD_AMOUNT

            player["total_minutes"] = new_total
            player["current_session_minutes"] = int((now - self.online_since[steam_id]) // 60)

            if gained_energy > 0:
                player["energy"] = int(player.get("energy", 0)) + gained_energy
                print(
                    f"[REWARD] {player.get('name', steam_id)} | "
                    f"{steam_id} | +{gained_energy} energy | "
                    f"total={player['total_minutes']} mins | "
                    f"energy={player['energy']}"
                )

            self.last_minute_tick[steam_id] = last_tick + (whole_minutes * 60)

        save_json(PLAYER_DATA_FILE, data)