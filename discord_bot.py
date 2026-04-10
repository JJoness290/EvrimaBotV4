import discord
from discord.ext import commands
import json
from pathlib import Path
from datetime import datetime, timedelta, timezone

TOKEN = "MTQ4NjQ2NTQ4ODczNjQ4NTQ0Ng.GOCPqh.UK1TpRD44ugqS2TkTfdKQalFd6u_O93LFxz2Bw"

DATA_FILE = Path("player_data.json")
LINK_FILE = Path("links.json")
SHOP_FILE = Path("shop.json")
PURCHASES_FILE = Path("purchases.json")
GAME_COMMANDS_FILE = Path("game_commands.json")
REFERRALS_FILE = Path("referrals.json")

PURCHASE_TIMEOUT_MINUTES = 15
QUEUED_TIMEOUT_MINUTES = 5

REFERRAL_REWARDS = {
    5: 15,
    10: 30,
    20: 60,
}

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

invite_cache = {}


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


def load_referrals():
    return load_json(REFERRALS_FILE, {})


def save_referrals(data):
    save_json(REFERRALS_FILE, data)


def ensure_referral_record(referrals, discord_id: str):
    if discord_id not in referrals:
        referrals[discord_id] = {
            "count": 0,
            "users": [],
            "rewards": [],
        }


def get_player(ctx):
    links = load_json(LINK_FILE, {})
    data = load_json(DATA_FILE, {})

    steam_id = links.get(str(ctx.author.id))
    if not steam_id:
        return None, None

    return data.get(steam_id), steam_id


def get_player_by_discord_id(discord_id: str):
    links = load_json(LINK_FILE, {})
    data = load_json(DATA_FILE, {})

    steam_id = links.get(discord_id)
    if not steam_id:
        return None, None, data

    return data.get(steam_id), steam_id, data


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


async def cache_guild_invites(guild: discord.Guild):
    try:
        invites = await guild.invites()
        invite_cache[guild.id] = {invite.code: invite.uses for invite in invites}
    except Exception:
        if guild.id not in invite_cache:
            invite_cache[guild.id] = {}


def reward_referral_if_eligible(inviter_id: str, guild: discord.Guild):
    referrals = load_referrals()
    ensure_referral_record(referrals, inviter_id)

    record = referrals[inviter_id]
    rewarded_levels = set(record.get("rewards", []))
    gained_messages = []

    for invite_count, energy_reward in sorted(REFERRAL_REWARDS.items()):
        reward_key = str(invite_count)
        if record.get("count", 0) >= invite_count and reward_key not in rewarded_levels:
            player, steam_id, data = get_player_by_discord_id(inviter_id)
            if player and steam_id and steam_id in data:
                data[steam_id]["energy"] = int(data[steam_id].get("energy", 0)) + energy_reward
                save_json(DATA_FILE, data)
                record["rewards"].append(reward_key)
                gained_messages.append(
                    f"🎉 <@{inviter_id}> reached **{invite_count} invites** and earned **+{energy_reward} energy**!"
                )

    save_referrals(referrals)

    if gained_messages:
        general_channel = discord.utils.get(guild.text_channels, name="general")
        if general_channel:
            return gained_messages, general_channel

    return [], None


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    for guild in bot.guilds:
        await cache_guild_invites(guild)


@bot.event
async def on_guild_join(guild):
    await cache_guild_invites(guild)


@bot.event
async def on_member_join(member):
    if member.bot:
        return

    general_channel = discord.utils.get(member.guild.text_channels, name="general")
    if general_channel:
        await general_channel.send(
            f"👋 Welcome {member.mention} to Primal Abyss!\n"
            f"⚡ Earn energy by playing\n"
            f"🔗 Use !link <steamid>"
        )

    if datetime.now(timezone.utc) - member.created_at < timedelta(days=1):
        await cache_guild_invites(member.guild)
        return

    previous_invites = invite_cache.get(member.guild.id, {})
    used_inviter_id = None

    try:
        current_invites = await member.guild.invites()
    except Exception:
        current_invites = []

    if current_invites:
        for invite in current_invites:
            previous_uses = previous_invites.get(invite.code, 0)
            if invite.uses > previous_uses and invite.inviter:
                used_inviter_id = str(invite.inviter.id)
                break

        invite_cache[member.guild.id] = {invite.code: invite.uses for invite in current_invites}

    if not used_inviter_id:
        return

    if used_inviter_id == str(member.id):
        return

    referrals = load_referrals()
    ensure_referral_record(referrals, used_inviter_id)
    record = referrals[used_inviter_id]

    if str(member.id) in record["users"]:
        save_referrals(referrals)
        return

    record["users"].append(str(member.id))
    record["count"] = len(record["users"])
    save_referrals(referrals)

    gained_messages, reward_channel = reward_referral_if_eligible(used_inviter_id, member.guild)
    if reward_channel and gained_messages:
        for message in gained_messages:
            await reward_channel.send(message)


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


@bot.command()
async def invites(ctx):
    referrals = load_referrals()
    discord_id = str(ctx.author.id)
    ensure_referral_record(referrals, discord_id)
    save_referrals(referrals)

    record = referrals[discord_id]
    await ctx.send(
        f"🔗 **{ctx.author.display_name}** has **{record.get('count', 0)}** valid invites.\n"
        f"🏆 Reward milestones: 5 / 10 / 20"
    )


@bot.command()
async def leaderboard(ctx):
    referrals = load_referrals()

    leaderboard_rows = []
    for discord_id, record in referrals.items():
        leaderboard_rows.append((discord_id, int(record.get("count", 0))))

    if not leaderboard_rows:
        await ctx.send("📭 No invite referrals tracked yet.")
        return

    leaderboard_rows.sort(key=lambda x: x[1], reverse=True)
    top_five = leaderboard_rows[:5]

    lines = ["🏆 **Top Inviters**\n"]
    for idx, (discord_id, count) in enumerate(top_five, start=1):
        user = bot.get_user(int(discord_id))
        display_name = user.name if user else f"User {discord_id}"
        lines.append(f"{idx}. **{display_name}** — {count} invites")

    await ctx.send("\n".join(lines))


bot.run(TOKEN)
