import sqlite3
import time
from pathlib import Path

DB_PATH = Path("data/evrima.db")
DB_PATH.parent.mkdir(exist_ok=True)

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_conn() as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS players (
            steam_id TEXT PRIMARY KEY,
            current_name TEXT,
            total_minutes INTEGER DEFAULT 0,
            primal_energy INTEGER DEFAULT 0,
            last_seen INTEGER,
            created_at INTEGER
        )
        """)
        conn.commit()

def ensure_player(steam_id, name):
    now = int(time.time())
    with get_conn() as conn:
        conn.execute("""
        INSERT INTO players (steam_id, current_name, total_minutes, primal_energy, last_seen, created_at)
        VALUES (?, ?, 0, 0, ?, ?)
        ON CONFLICT(steam_id) DO UPDATE SET
            current_name=excluded.current_name,
            last_seen=excluded.last_seen
        """, (steam_id, name, now, now))
        conn.commit()

def add_minutes(steam_id, minutes):
    with get_conn() as conn:
        conn.execute("""
        UPDATE players
        SET total_minutes = total_minutes + ?
        WHERE steam_id = ?
        """, (minutes, steam_id))
        conn.commit()

def add_energy(steam_id, amount):
    with get_conn() as conn:
        conn.execute("""
        UPDATE players
        SET primal_energy = primal_energy + ?
        WHERE steam_id = ?
        """, (amount, steam_id))
        conn.commit()

def get_player(steam_id):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM players WHERE steam_id = ?", (steam_id,)
        ).fetchone()
        return dict(row) if row else None