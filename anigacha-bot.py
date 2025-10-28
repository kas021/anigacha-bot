"""
Discord Gacha Bot
Open source demo. Rolls characters, lets users claim them, tracks currency and inventory.

REQUIRES:
- A .env file with DISCORD_BOT_TOKEN, GUILD_ID (optional), and BOT_OWNER_ID
- Python 3.10+ with discord.py, aiohttp, python-dotenv installed

See README.md for complete setup instructions.
"""

import os
import sqlite3
import random
import asyncio
import aiohttp
from datetime import datetime, timedelta
from typing import Optional, List, Dict

import discord
from discord.ext import commands
from dotenv import load_dotenv

# ==================== LOAD TOKEN ====================

load_dotenv()
TOKEN = os.getenv("DISCORD_BOT_TOKEN")

# ==================== CONFIG / CONSTANTS ====================

DB_PATH = "anime_card_bot.db"

ROLL_LIMIT = 10                 # rolls per batch
ROLL_RESET_HOURS = 1            # hours before new batch of rolls
CLAIM_COOLDOWN_HOURS = 3        # time between successful $claim
DAILY_COOLDOWN_HOURS = 20       # time between $daily rewards
VOTE_RESET_HOURS = 12           # cooldown for $rolls reset
CLAIM_WINDOW_SECONDS = 120      # how long after $w you can claim that roll

CASH_DAILY_MIN = 200
CASH_DAILY_MAX = 400
CASH_CLAIM_MIN = 50
CASH_CLAIM_MAX = 200

# Load from environment variables for security
# Set these in your .env file:
# GUILD_ID = your_server_id_here (optional, currently unused in this prefix-command version)
# BOT_OWNER_ID = your_discord_user_id_here (required for owner commands)
GUILD_ID = int(os.getenv("GUILD_ID", "0"))

# Support single owner ID from env var
owner_id = os.getenv("BOT_OWNER_ID", "0")
BOT_OWNER_IDS = {int(owner_id)} if owner_id and owner_id != "0" else set()

# ==================== TIME HELPERS ====================

def now_utc() -> datetime:
    return datetime.utcnow()

def dt_to_str(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt else None

def str_to_dt(s: Optional[str]) -> Optional[datetime]:
    return datetime.fromisoformat(s) if s else None

def humanize_delta(td: timedelta) -> str:
    total_seconds = int(td.total_seconds())
    if total_seconds < 0:
        total_seconds = 0
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    if hours > 0:
        return f"{hours}h {minutes}m"
    if minutes > 0:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"

# ==================== DB DECORATOR ====================

def with_db(func):
    """open/close sqlite for each call so we don't forget commits."""
    def wrapper(*args, **kwargs):
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        result = func(cursor, *args, **kwargs)
        conn.commit()
        conn.close()
        return result
    return wrapper

# ==================== DB SETUP / QUERIES ====================

@with_db
def setup_db(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            cash INTEGER DEFAULT 1000,
            daily_time TEXT,
            last_roll_batch TEXT,
            rolls_left INTEGER DEFAULT 10,
            last_claim TEXT,
            last_vote TEXT,
            vote_count INTEGER DEFAULT 0,
            is_admin INTEGER DEFAULT 0
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cards (
            card_id   INTEGER PRIMARY KEY AUTOINCREMENT,
            name      TEXT,
            series    TEXT,
            age       TEXT,
            image_url TEXT,
            rarity    INTEGER,
            value     INTEGER,
            owner_id  INTEGER
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS inventory (
            user_id INTEGER,
            card_id INTEGER,
            PRIMARY KEY(user_id, card_id)
        )
    """)

@with_db
def get_user(cursor, user_id: int):
    cursor.execute("""
        SELECT user_id, cash, daily_time, last_roll_batch, rolls_left,
               last_claim, last_vote, vote_count, is_admin
        FROM users
        WHERE user_id = ?
    """, (user_id,))
    row = cursor.fetchone()

    if row:
        return {
            "user_id": row[0],
            "cash": row[1],
            "daily_time": row[2],
            "last_roll_batch": row[3],
            "rolls_left": row[4],
            "last_claim": row[5],
            "last_vote": row[6],
            "vote_count": row[7],
            "is_admin": row[8],
        }

    # create default row if missing
    cursor.execute("""
        INSERT INTO users (
            user_id, cash, daily_time,
            last_roll_batch, rolls_left,
            last_claim, last_vote,
            vote_count, is_admin
        )
        VALUES (?, 1000, NULL, NULL, ?, NULL, NULL, 0, 0)
    """, (user_id, ROLL_LIMIT))

    return {
        "user_id": user_id,
        "cash": 1000,
        "daily_time": None,
        "last_roll_batch": None,
        "rolls_left": ROLL_LIMIT,
        "last_claim": None,
        "last_vote": None,
        "vote_count": 0,
        "is_admin": 0,
    }

@with_db
def set_daily_time(cursor, user_id: int, when_iso: str):
    cursor.execute("""
        UPDATE users
        SET daily_time = ?
        WHERE user_id = ?
    """, (when_iso, user_id))

@with_db
def add_cash(cursor, user_id: int, delta: int):
    cursor.execute("""
        UPDATE users
        SET cash = cash + ?
        WHERE user_id = ?
    """, (delta, user_id))
    cursor.execute("SELECT cash FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    return row[0] if row else None

@with_db
def grant_new_roll_batch(cursor, user_id: int, when_iso: str, roll_limit: int):
    cursor.execute("""
        UPDATE users
        SET rolls_left = ?,
            last_roll_batch = ?
        WHERE user_id = ?
    """, (roll_limit, when_iso, user_id))

@with_db
def set_rolls_left(cursor, user_id: int, new_left: int):
    cursor.execute("""
        UPDATE users
        SET rolls_left = ?
        WHERE user_id = ?
    """, (new_left, user_id))

@with_db
def set_last_claim(cursor, user_id: int, when_iso: str):
    cursor.execute("""
        UPDATE users
        SET last_claim = ?
        WHERE user_id = ?
    """, (when_iso, user_id))

@with_db
def record_vote_and_reset_rolls(cursor, user_id: int, when_iso: str, roll_limit: int):
    cursor.execute("""
        UPDATE users
        SET vote_count = vote_count + 1,
            last_vote = ?,
            rolls_left = ?,
            last_roll_batch = ?
        WHERE user_id = ?
    """, (when_iso, roll_limit, when_iso, user_id))

@with_db
def character_exists(cursor, name: str, series: str) -> Optional[int]:
    cursor.execute("""
        SELECT card_id FROM cards
        WHERE name = ? AND series = ?
        LIMIT 1
    """, (name, series))
    row = cursor.fetchone()
    return row[0] if row else None

@with_db
def insert_card(cursor, name: str, series: str, age: str,
                image_url: str, rarity: int, value: int):
    cursor.execute("""
        INSERT INTO cards (name, series, age, image_url, rarity, value, owner_id)
        VALUES (?, ?, ?, ?, ?, ?, NULL)
    """, (name, series, age, image_url, rarity, value))
    return cursor.lastrowid

@with_db
def get_random_card(cursor):
    cursor.execute("""
        SELECT card_id, name, series, age, image_url, rarity, value
        FROM cards
        ORDER BY RANDOM()
        LIMIT 1
    """)
    row = cursor.fetchone()
    if not row:
        return None
    return {
        "card_id": row[0],
        "name": row[1],
        "series": row[2],
        "age": row[3],
        "image_url": row[4],
        "rarity": row[5],
        "value": row[6],
    }

@with_db
def get_card_by_id(cursor, card_id: int):
    cursor.execute("""
        SELECT card_id, name, series, age, image_url, rarity, value, owner_id
        FROM cards
        WHERE card_id = ?
    """, (card_id,))
    row = cursor.fetchone()
    if not row:
        return None
    return {
        "card_id": row[0],
        "name": row[1],
        "series": row[2],
        "age": row[3],
        "image_url": row[4],
        "rarity": row[5],
        "value": row[6],
        "owner_id": row[7],
    }

@with_db
def add_card_to_inventory(cursor, user_id: int, card_id: int):
    cursor.execute("""
        UPDATE cards
        SET owner_id = ?
        WHERE card_id = ?
    """, (user_id, card_id))
    cursor.execute("""
        INSERT OR IGNORE INTO inventory (user_id, card_id)
        VALUES (?, ?)
    """, (user_id, card_id))

@with_db
def get_inventory(cursor, user_id: int):
    cursor.execute("""
        SELECT c.card_id, c.name, c.series, c.rarity, c.value
        FROM cards c
        JOIN inventory i ON c.card_id = i.card_id
        WHERE i.user_id = ?
        ORDER BY c.rarity DESC, c.value DESC
    """, (user_id,))
    rows = cursor.fetchall()
    cards = []
    for r in rows:
        cards.append({
            "card_id": r[0],
            "name": r[1],
            "series": r[2],
            "rarity": r[3],
            "value": r[4],
        })
    return cards

# create DB if first run
setup_db()

# ==================== ANILIST FETCHER ====================

class AniListAPI:
    BASE_URL = "https://graphql.anilist.co"

    @staticmethod
    async def fetch_characters(limit: int = 100) -> List[Dict]:
        """
        Pull character data from AniList.
        We'll grab name, series, image, favorites count.
        We'll stop once we hit 'limit'.
        """
        query = """
        query ($page: Int, $perPage: Int) {
            Page(page: $page, perPage: $perPage) {
                characters {
                    name {
                        full
                        native
                    }
                    image {
                        large
                    }
                    media {
                        nodes {
                            title {
                                romaji
                            }
                        }
                    }
                    favourites
                }
            }
        }
        """

        characters: List[Dict] = []

        async with aiohttp.ClientSession() as session:
            page = 1
            per_page = 50

            while len(characters) < limit and page <= 20:
                variables = {"page": page, "perPage": per_page}
                try:
                    async with session.post(
                        AniListAPI.BASE_URL,
                        json={"query": query, "variables": variables}
                    ) as resp:
                        if resp.status != 200:
                            print(f"AniList HTTP {resp.status}")
                            break

                        data = await resp.json()
                        page_chars = (
                            data.get("data", {})
                                .get("Page", {})
                                .get("characters", [])
                        )

                        for ch in page_chars:
                            name = ch.get("name", {}).get("full", "Unknown")
                            name_native = ch.get("name", {}).get("native", "")
                            img = ch.get("image", {}).get("large", "")
                            favs = ch.get("favourites", 0)

                            media_nodes = ch.get("media", {}).get("nodes", [])
                            series = "Unknown Series"
                            if media_nodes:
                                series = (
                                    media_nodes[0]
                                    .get("title", {})
                                    .get("romaji", "Unknown Series")
                                )

                            characters.append({
                                "name": name,
                                "name_native": name_native,
                                "image_url": img,
                                "series": series,
                                "favorites": favs
                            })

                            if len(characters) >= limit:
                                break

                    await asyncio.sleep(1)  # chill so AniList doesn't slap us
                except Exception as e:
                    print(f"Error fetching page {page}: {e}")
                    await asyncio.sleep(1)
                page += 1

        return characters

# ==================== BOT SETUP ====================

intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.messages = True
intents.message_content = True  # required for prefix commands that read messages

bot = commands.Bot(command_prefix="$", intents=intents)

# in-memory recent rolls so we can claim
# bot.last_rolls[msg_id] = {
#   "card_id": ...,
#   "roller_id": ...,
#   "rolled_at": iso string
# }
bot.last_rolls = {}

# ==================== INTERNAL HELPERS ====================

def is_bot_owner(user_id: int) -> bool:
    return user_id in BOT_OWNER_IDS

async def send_cooldown(ctx: commands.Context, base_msg: str, next_time: datetime):
    delta = next_time - now_utc()
    await ctx.send(
        f"{ctx.author.mention} {base_msg} Try again in {humanize_delta(delta)}."
    )

# ==================== COMMANDS ====================

@bot.event
async def on_ready():
    guild_info = f"in guild {GUILD_ID}" if GUILD_ID != 0 else ""
    print(f"{bot.user} is online {guild_info} and ready.")

@bot.command(name="info")
async def info_cmd(ctx: commands.Context):
    msg = (
        "**Anime Card Game Info**\n"
        "• `$w` (or `$roll`) rolls a random character. You get limited rolls per hour.\n"
        "• `$claim` claims your latest roll. Claim cooldown is 3 hours.\n"
        "• `$daily` gives you free cash every 20 hours.\n"
        "• Claiming also gives bonus cash.\n"
        "• `$inventory` shows collections.\n"
        "• `$balance` shows your cash.\n"
        "• `$rolls` gives a fresh batch of rolls (vote reset style), but only every 12h.\n"
        "• `$populate <num>` (owner only) bulk-loads characters from AniList.\n"
        "• `$addcard` lets owner add a single custom character.\n"
        "\nAnti-abuse:\n"
        "• Only the roller can claim their roll, and only for a short window.\n"
        "• No infinite roll spam.\n"
        "• Card injection is owner locked.\n"
    )
    await ctx.send(msg)

@bot.command(name="balance")
async def balance_cmd(ctx: commands.Context):
    user_id = ctx.author.id
    user_data = get_user(user_id)
    await ctx.send(
        f"{ctx.author.mention} you currently have {user_data['cash']} cash."
    )

@bot.command(name="daily")
async def daily_cmd(ctx: commands.Context):
    user_id = ctx.author.id
    user_data = get_user(user_id)

    now = now_utc()
    last_daily_dt = str_to_dt(user_data["daily_time"])

    if last_daily_dt:
        elapsed = now - last_daily_dt
        if elapsed < timedelta(hours=DAILY_COOLDOWN_HOURS):
            next_time = last_daily_dt + timedelta(hours=DAILY_COOLDOWN_HOURS)
            await send_cooldown(
                ctx,
                "Daily already claimed.",
                next_time
            )
            return

    reward = random.randint(CASH_DAILY_MIN, CASH_DAILY_MAX)
    new_cash = add_cash(user_id, reward)
    set_daily_time(user_id, dt_to_str(now))

    await ctx.send(
        f"{ctx.author.mention} you received {reward} cash. New balance: {new_cash}."
    )

@bot.command(name="rolls")
async def rolls_cmd(ctx: commands.Context):
    """
    Controlled roll batch reset (vote reward style).
    Cooldown 12h between uses.
    """
    user_id = ctx.author.id
    user_data = get_user(user_id)

    now = now_utc()
    last_vote_dt = str_to_dt(user_data["last_vote"])

    if last_vote_dt:
        elapsed = now - last_vote_dt
        if elapsed < timedelta(hours=VOTE_RESET_HOURS):
            next_time = last_vote_dt + timedelta(hours=VOTE_RESET_HOURS)
            await send_cooldown(
                ctx,
                "You already used your roll reset.",
                next_time
            )
            return

    record_vote_and_reset_rolls(user_id, dt_to_str(now), ROLL_LIMIT)

    await ctx.send(
        f"{ctx.author.mention} your rolls have been reset to {ROLL_LIMIT}."
    )

@bot.command(name="vote")
async def vote_cmd(ctx: commands.Context):
    await ctx.send(
        f"{ctx.author.mention} support the bot (fake vote):\n"
        f"https://top.gg/vote\n"
        f"then use `$rolls` to refresh your rolls."
    )

@bot.command(name="w", aliases=["roll"])
async def roll_cmd(ctx: commands.Context):
    # block DMs so people can't farm secretly
    if ctx.guild is None:
        await ctx.send("Use this command in a server, not in DMs.")
        return

    user_id = ctx.author.id
    user_data = get_user(user_id)
    now = now_utc()

    last_batch_dt = str_to_dt(user_data["last_roll_batch"])
    rolls_left = user_data["rolls_left"]

    # refresh batch if time passed
    need_refresh = (last_batch_dt is None) or (
        now - last_batch_dt >= timedelta(hours=ROLL_RESET_HOURS)
    )
    if need_refresh:
        grant_new_roll_batch(user_id, dt_to_str(now), ROLL_LIMIT)
        rolls_left = ROLL_LIMIT
        last_batch_dt = now

    # out of rolls
    if rolls_left <= 0:
        reset_time = last_batch_dt + timedelta(hours=ROLL_RESET_HOURS)
        await send_cooldown(
            ctx,
            "No rolls left.",
            reset_time
        )
        return

    # get a random card
    card = get_random_card()
    if not card:
        await ctx.send(
            "No cards in the database yet. "
            "Owner needs to run `$populate 200` or `$addcard ...`"
        )
        return

    # create embed
    embed = discord.Embed(
        title=card["name"],
        description=(
            f"Series: {card['series']}\n"
            f"Rarity: {card['rarity']}★\n"
            f"Value: {card['value']} cash"
        ),
        color=discord.Color.purple()
    )
    embed.set_footer(
        text=f"Rolled by {ctx.author.display_name} • Use $claim within {CLAIM_WINDOW_SECONDS}s"
    )
    if card["image_url"]:
        embed.set_image(url=card["image_url"])

    # send publicly
    sent_message = await ctx.send(embed=embed)

    # remember roll so $claim can target it
    bot.last_rolls[sent_message.id] = {
        "card_id": card["card_id"],
        "roller_id": user_id,
        "rolled_at": dt_to_str(now),
    }

    # spend 1 roll
    new_left = rolls_left - 1
    set_rolls_left(user_id, new_left)

@bot.command(name="claim", aliases=["c"])
async def claim_cmd(ctx: commands.Context):
    # no DM farming
    if ctx.guild is None:
        await ctx.send("Use this command in a server, not in DMs.")
        return

    user_id = ctx.author.id
    user_data = get_user(user_id)
    now = now_utc()

    # 3h claim cooldown
    last_claim_dt = str_to_dt(user_data["last_claim"])
    if last_claim_dt:
        elapsed = now - last_claim_dt
        if elapsed < timedelta(hours=CLAIM_COOLDOWN_HOURS):
            next_time = last_claim_dt + timedelta(hours=CLAIM_COOLDOWN_HOURS)
            await send_cooldown(
                ctx,
                "You already claimed recently.",
                next_time
            )
            return

    # find most recent eligible roll from THIS user in THIS channel
    target_message = None
    target_data = None

    async for message in ctx.channel.history(limit=25):
        if message.author.id != bot.user.id:
            continue
        if message.id not in bot.last_rolls:
            continue

        roll_data = bot.last_rolls[message.id]

        # must match roller
        if roll_data["roller_id"] != user_id:
            continue

        rolled_at_dt = str_to_dt(roll_data["rolled_at"])
        if not rolled_at_dt:
            continue

        # must be within claim window
        if (now - rolled_at_dt).total_seconds() > CLAIM_WINDOW_SECONDS:
            continue

        target_message = message
        target_data = roll_data
        break

    if not target_data:
        await ctx.send(
            f"{ctx.author.mention} no recent roll found for you, or claim window expired."
        )
        return

    card_id = target_data["card_id"]

    # give them the card
    add_card_to_inventory(user_id, card_id)

    # reward money
    reward = random.randint(CASH_CLAIM_MIN, CASH_CLAIM_MAX)
    new_cash = add_cash(user_id, reward)

    # set claim cooldown
    set_last_claim(user_id, dt_to_str(now))

    # burn this roll so it can't be claimed twice
    if target_message.id in bot.last_rolls:
        del bot.last_rolls[target_message.id]

    # reply nicely
    card_info = get_card_by_id(card_id)
    char_name = card_info["name"] if card_info else "Unknown Card"

    await ctx.send(
        f"{ctx.author.mention} claimed **{char_name}** "
        f"and earned {reward} cash. Balance: {new_cash}."
    )

@bot.command(name="inventory")
async def inventory_cmd(ctx: commands.Context, user: Optional[discord.Member] = None):
    target = user or ctx.author
    inv = get_inventory(target.id)

    if not inv:
        await ctx.send(f"{target.display_name} has no cards.")
        return

    lines = []
    total_value = 0
    for i, card in enumerate(inv):
        if i >= 20:
            lines.append("...and more.")
            break
        lines.append(
            f"[{card['card_id']}] {card['name']} ({card['series']}) "
            f"| {card['rarity']}★ | {card['value']} cash"
        )
        total_value += card["value"]

    embed = discord.Embed(
        title=f"{target.display_name}'s Inventory",
        description="\n".join(lines),
        color=discord.Color.gold()
    )
    embed.set_footer(
        text=f"Total cards: {len(inv)} • Estimated value: {total_value} cash"
    )

    await ctx.send(embed=embed)

@bot.command(name="addcard")
async def addcard_cmd(
    ctx: commands.Context,
    name: str = None,
    series: str = None,
    age: str = None,
    image_url: str = None,
    rarity: int = None,
    value: int = None
):
    """
    Owner-only manual card insert.
    Usage:
    $addcard "Asuka" "Evangelion" "14" "https://img.url" 4 1200
    """
    # check owner
    if ctx.author.id not in BOT_OWNER_IDS:
        await ctx.send("You are not authorized to use this command. This action is owner-only.")
        return

    # if they just typed $addcard with no args, be helpful instead of exploding
    if (
        name is None or series is None or age is None
        or image_url is None or rarity is None or value is None
    ):
        await ctx.send(
            "Usage:\n"
            "$addcard <name> <series> <age> <image_url> <rarity:int 1-5> <value:int>\n\n"
            'Example:\n'
            '$addcard "Asuka" "Neon Genesis Evangelion" "14" "https://image.png" 4 1200'
        )
        return

    # insert
    card_id = insert_card(name, series, age, image_url, rarity, value)

    await ctx.send(
        f"Card added with ID {card_id}: {name} ({series}), rarity {rarity}★, value {value}."
    )

@bot.command(name="populate")
async def populate_cmd(ctx: commands.Context, limit: int = 500):
    """
    Owner-only bulk import from AniList.
    Example: $populate 200
    """
    # only owner, not random server admins
    if ctx.author.id not in BOT_OWNER_IDS:
        await ctx.send("You are not authorized to populate the database. This action is owner-only.")
        return

    # sanity clamp
    if limit < 1:
        limit = 1
    if limit > 1000:
        limit = 1000

    await ctx.send(
        f"🔄 Fetching up to {limit} characters from AniList... this will take a moment."
    )

    characters = await AniListAPI.fetch_characters(limit)
    added = 0

    for ch in characters:
        name = ch["name"]
        series = ch["series"]
        img = ch["image_url"]
        favs = ch["favorites"]

        # skip if already exists (name+series match)
        if character_exists(name, series):
            continue

        # make rarity/value from favorites
        rarity = min(5, max(1, favs // 1000))
        value = max(100, rarity * 100 + favs // 10)

        insert_card(
            name=name,
            series=series,
            age="unknown",
            image_url=img,
            rarity=rarity,
            value=value
        )
        added += 1

    await ctx.send(
        f"✅ Added {added} new characters to the database."
    )

# ==================== RUN BOT ====================

if __name__ == "__main__":
    if not TOKEN:
        raise RuntimeError("DISCORD_BOT_TOKEN not found in environment. Fix your .env.")
    bot.run(TOKEN)
