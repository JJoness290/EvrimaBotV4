import discord
from discord.ext import commands
from discord.ext import tasks
import json
from pathlib import Path
from datetime import datetime, timedelta
import time
from rcon_client import run_rcon

TOKEN = "YOUR_DISCORD_BOT_TOKEN"

DATA_FILE = Path("player_data.json")
LINK_FILE = Path("links.json")
SHOP_FILE = Path("shop.json")
PURCHASES_FILE = Path("purchases.json")
GAME_COMMANDS_FILE = Path("game_commands.json")

PURCHASE_TIMEOUT_MINUTES = 15
QUEUED_TIMEOUT_MINUTES = 5

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

last_announcement_time = 0
announcement_messages = [
    "🌋 Welcome to Primal Abyss",
    "⚡ Earn energy while you survive",
    "💬 Join our Discord for rewards",
]
announcement_index = 0


def load_json(path: Path, default):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return default
    return default


def save_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def load_shop():
    return load_json(SHOP_FILE, {})


def load_purchases():
    return load_json(PURCHASES_FILE, [])


def save_purchases(data):
    save_json(PURCHASES_FILE, data)


def load_game_commands():
    return load_json(GAME_COMMANDS_FILE, [])


def save_game_commands(data):
    save_json(GAME_COMMANDS_FILE, data)


def get_player(ctx):
    links = load_json(LINK_FILE, {})
    data = load_json(DATA_FILE, {})

    steam_id = links.get(str(ctx.author.id))
    if not steam_id:
        return None, None

    return data.get(steam_id), steam_id


def find_shop_price(item_name: str):
    shop = load_shop()
    for category, items in shop.items():
        if item_name in items:
            return items[item_name], category
    return None, None


def get_next_command_id(commands_data):
    if not commands_data:
        return 1

    max_id = 0
    for entry in commands_data:
        try:
            cid = int(str(entry.get("id", "0")).replace("cmd_", ""))
            max_id = max(max_id, cid)
        except Exception:
            pass

    return max_id + 1


def parse_dt(value: str):
    if not value:
        return None

    for fmt in (
        None,
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
    ):
        try:
            if fmt is None:
                return datetime.fromisoformat(value)
            return datetime.strptime(value, fmt)
        except Exception:
            continue

    return None


def expire_old_purchases():
    purchases = load_purchases()
    data = load_json(DATA_FILE, {})
    game_commands = load_game_commands()

    now = datetime.now()
    changed_purchases = False
    changed_data = False
    changed_commands = False

    for purchase in purchases:
        status = purchase.get("status")
        steam_id = purchase.get("steam_id")
        item = str(purchase.get("item", "")).lower().strip()

        if status == "UNCLAIMED":
            created_at = parse_dt(purchase.get("time", ""))
            if not created_at:
                continue

            if now - created_at >= timedelta(minutes=PURCHASE_TIMEOUT_MINUTES):
                price, _ = find_shop_price(item)
                if price is not None and steam_id in data:
                    data[steam_id]["energy"] = data[steam_id].get("energy", 0) + price
                    changed_data = True

                purchase["status"] = "EXPIRED"
                purchase["delivery_note"] = f"Expired after {PURCHASE_TIMEOUT_MINUTES} minutes"
                changed_purchases = True

        elif status == "QUEUED_FOR_PRIME":
            claimed_at = parse_dt(purchase.get("claimed_at", "")) or parse_dt(purchase.get("time", ""))
            if not claimed_at:
                continue

            if now - claimed_at >= timedelta(minutes=QUEUED_TIMEOUT_MINUTES):
                for cmd in game_commands:
                    if (
                        cmd.get("steam_id") == steam_id
                        and str(cmd.get("item", "")).lower().strip() == item
                        and cmd.get("status") in {"PENDING", "SENDING"}
                    ):
                        cmd["status"] = "EXPIRED"
                        cmd["completed_at"] = str(datetime.now())
                        changed_commands = True

                purchase["status"] = "UNCLAIMED"
                purchase["delivery_note"] = f"Prime queue expired after {QUEUED_TIMEOUT_MINUTES} minutes"
                changed_purchases = True

    if changed_purchases:
        save_purchases(purchases)
    if changed_data:
        save_json(DATA_FILE, data)
    if changed_commands:
        save_game_commands(game_commands)


def has_open_purchase(steam_id: str) -> bool:
    purchases = load_purchases()
    open_statuses = {"UNCLAIMED", "QUEUED_FOR_PRIME", "CLAIMING"}
    return any(
        p.get("steam_id") == steam_id and p.get("status") in open_statuses
        for p in purchases
    )


def get_claimable_purchase_index(purchases, steam_id: str):
    for i in range(len(purchases) - 1, -1, -1):
        p = purchases[i]
        if p.get("steam_id") == steam_id and p.get("status") == "UNCLAIMED":
            return i, "UNCLAIMED"

    for i in range(len(purchases) - 1, -1, -1):
        p = purchases[i]
        if p.get("steam_id") == steam_id and p.get("status") == "QUEUED_FOR_PRIME":
            return i, "QUEUED_FOR_PRIME"

    return None, None


def get_online_players_from_data():
    data = load_json(DATA_FILE, {})
    online = []

    for steam_id, player in data.items():
        session = int(player.get("current_session_minutes", 0))
        if session > 0:
            online.append({
                "name": player.get("name", "Unknown"),
                "steam_id": steam_id,
                "session": session,
                "total": int(player.get("total_minutes", 0)),
                "energy": int(player.get("energy", 0)),
            })

    return online


def send_rcon_command(command: str):
    return run_rcon(command)


@tasks.loop(seconds=5)
async def timed_server_announcements():
    global last_announcement_time
    global announcement_index

    current_time = time.time()

    if current_time - last_announcement_time >= 600:
        message = announcement_messages[announcement_index % len(announcement_messages)]
        send_rcon_command(f"announce {message}")
        last_announcement_time = current_time
        announcement_index = (announcement_index + 1) % len(announcement_messages)


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    if not timed_server_announcements.is_running():
        timed_server_announcements.start()


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    raise error


@bot.command()
async def link(ctx, steam_id: str):
    links = load_json(LINK_FILE, {})
    links[str(ctx.author.id)] = steam_id
    save_json(LINK_FILE, links)
    await ctx.send(f"✅ Linked to {steam_id}")


@bot.command()
async def stats(ctx):
    expire_old_purchases()

    player, steam_id = get_player(ctx)
    if not player:
        await ctx.send("❌ Use !link first")
        return

    previous_total = int(player.get("total_minutes", 0))
    current_session = int(player.get("current_session_minutes", 0))
    combined_total = previous_total + current_session
    energy = int(player.get("energy", 0))
    name = player.get("name", "Unknown")

    await ctx.send(
        f"📊 **{name}**\n"
        f"🆔 Steam ID: `{steam_id}`\n"
        f"⏱ Current session: {current_session} mins\n"
        f"🕒 Previously played: {previous_total} mins\n"
        f"📈 Total tracked: {combined_total} mins\n"
        f"⚡ Energy: {energy}"
    )


@bot.command()
async def online(ctx):
    expire_old_purchases()

    players = get_online_players_from_data()
    if not players:
        await ctx.send("📭 No tracked players are currently online.")
        return

    lines = [f"🟢 **Online Players ({len(players)})**\n"]
    for p in players:
        lines.append(
            f"**{p['name']}**\n"
            f"🆔 `{p['steam_id']}`\n"
            f"⏱ Session: {p['session']} mins\n"
            f"🕒 Previous total: {p['total']} mins\n"
            f"⚡ Energy: {p['energy']}\n"
        )

    await ctx.send("\n".join(lines))


@bot.command()
async def shop(ctx):
    expire_old_purchases()

    shop_data = load_shop()
    msg = "🛒 **Primal Abyss Shop**\n\n"

    for cat, items in shop_data.items():
        msg += f"**{cat.upper()}**\n"
        for item, price in items.items():
            msg += f"{item} — ⚡ {price}\n"
        msg += "\n"

    await ctx.send(msg)


@bot.command()
async def buy(ctx, item: str):
    expire_old_purchases()

    data = load_json(DATA_FILE, {})
    purchases = load_purchases()
    player, steam_id = get_player(ctx)

    if not player:
        await ctx.send("❌ Use !link first")
        return

    item = item.lower().strip()
    price, category = find_shop_price(item)

    if price is None:
        await ctx.send("❌ Item not found")
        return

    if category == "extras":
        await ctx.send("❌ Extras are not part of the prime claim flow")
        return

    if has_open_purchase(steam_id):
        await ctx.send("❌ You already have an active purchase. Use `!claim` first.")
        return

    if player.get("energy", 0) < price:
        await ctx.send("❌ Not enough energy")
        return

    player["energy"] -= price
    save_json(DATA_FILE, data)

    purchases.append({
        "player": player["name"],
        "steam_id": steam_id,
        "item": item,
        "status": "UNCLAIMED",
        "time": str(datetime.now()),
        "claimed_at": None,
        "delivery_note": None,
    })
    save_purchases(purchases)

    await ctx.send(
        f"🧬 **{item.upper()} PURCHASED**\n\n"
        f"⚡ -{price} energy\n"
        f"📦 Claim saved\n"
        f"⏳ Expires in {PURCHASE_TIMEOUT_MINUTES} minutes if not claimed\n\n"
        f"Use `!claim` when you are ready to be primed."
    )


@bot.command()
async def claim(ctx):
    expire_old_purchases()

    player, steam_id = get_player(ctx)

    if not player:
        await ctx.send("❌ Use !link first")
        return

    purchases = load_purchases()
    purchase_index, purchase_status = get_claimable_purchase_index(purchases, steam_id)

    if purchase_index is None:
        await ctx.send("❌ You do not have any active dinosaur purchases.")
        return

    if purchase_status == "QUEUED_FOR_PRIME":
        purchase = purchases[purchase_index]
        await ctx.send(
            f"⏳ Your prime is already queued.\n\n"
            f"🧬 Dino: **{purchase['item'].upper()}**\n"
            f"Use `!myclaims` to check status, or wait for the bridge."
        )
        return

    game_commands = load_game_commands()

    existing_pending = any(
        cmd.get("steam_id") == steam_id
        and str(cmd.get("item", "")).lower().strip() == str(purchases[purchase_index]["item"]).lower().strip()
        and cmd.get("status") in {"PENDING", "SENDING"}
        for cmd in game_commands
    )
    if existing_pending:
        purchases[purchase_index]["status"] = "QUEUED_FOR_PRIME"
        purchases[purchase_index]["claimed_at"] = str(datetime.now())
        purchases[purchase_index]["delivery_note"] = "Existing pending prime command found"
        save_purchases(purchases)

        await ctx.send("⏳ Your prime is already queued and waiting to be sent.")
        return

    next_id = get_next_command_id(game_commands)
    command_text = f"/elder {steam_id} prime"

    game_commands.append({
        "id": f"cmd_{next_id:03d}",
        "steam_id": steam_id,
        "player_name": player["name"],
        "item": purchases[purchase_index]["item"],
        "command": command_text,
        "status": "PENDING",
        "created_at": str(datetime.now()),
        "completed_at": None
    })
    save_game_commands(game_commands)

    purchases[purchase_index]["status"] = "QUEUED_FOR_PRIME"
    purchases[purchase_index]["claimed_at"] = str(datetime.now())
    purchases[purchase_index]["delivery_note"] = command_text
    save_purchases(purchases)

    await ctx.send(
        f"⚡ **PRIME QUEUED**\n\n"
        f"🧬 Dino: **{purchases[purchase_index]['item'].upper()}**\n"
        f"👤 Player: **{player['name']}**\n"
        f"📨 Command queued: `{command_text}`\n\n"
        f"Stay in game while the admin bridge sends it."
    )


@bot.command()
async def myclaims(ctx):
    expire_old_purchases()

    player, steam_id = get_player(ctx)

    if not player:
        await ctx.send("❌ Use !link first")
        return

    purchases = load_purchases()
    mine = [p for p in purchases if p.get("steam_id") == steam_id]

    if not mine:
        await ctx.send("📭 You have no purchases.")
        return

    lines = ["📦 **Your Purchases**\n"]
    for p in mine[-10:]:
        lines.append(
            f"{p.get('item', '?')} — {p.get('status', '?')} — {p.get('time', '?')}"
        )

    await ctx.send("\n".join(lines))


bot.run(TOKEN)
