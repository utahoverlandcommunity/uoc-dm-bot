import os
import asyncio
import sqlite3
from datetime import datetime, timedelta

import discord
from discord.ext import commands, tasks

TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = int(os.getenv("GUILD_ID", "0"))
ADMIN_LOG_CHANNEL_ID = int(os.getenv("ADMIN_LOG_CHANNEL_ID", "0"))

# NUDGE CONFIG (silent)
NUDGE_BATCH_SIZE = int(os.getenv("NUDGE_BATCH_SIZE", "10"))
NUDGE_INTERVAL_MIN = int(os.getenv("NUDGE_INTERVAL_MIN", "240"))
MAX_DM_ATTEMPTS = int(os.getenv("MAX_DM_ATTEMPTS", "3"))
DM_COOLDOWN_DAYS = float(os.getenv("DM_COOLDOWN_DAYS", "2"))

# Allow DB path override for cloud persistent disks
DB_PATH = os.getenv("DB_PATH", "uoc_reg.db")

intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.dm_messages = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS registrations (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            instagram TEXT,
            created_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS outreach (
            user_id INTEGER PRIMARY KEY,
            last_dm_at TEXT,
            attempts INTEGER DEFAULT 0,
            dm_blocked INTEGER DEFAULT 0,
            opt_out INTEGER DEFAULT 0
        )
    """)
    return conn

def is_registered(user_id: int) -> bool:
    conn = db()
    return conn.execute("SELECT 1 FROM registrations WHERE user_id=?", (user_id,)).fetchone() is not None

def save_registration(user: discord.abc.User, first_name: str, instagram: str):
    conn = db()
    conn.execute(
        "REPLACE INTO registrations(user_id, username, first_name, instagram, created_at) VALUES (?,?,?,?,?)",
        (user.id, str(user), first_name.strip(), instagram.strip().lstrip('@'), datetime.utcnow().isoformat())
    )
    conn.commit()

def mark_outreach(user_id: int, *, blocked=False, bump_attempt=False):
    conn = db()
    row = conn.execute("SELECT attempts FROM outreach WHERE user_id=?", (user_id,)).fetchone()
    attempts = (row[0] if row else 0) + (1 if bump_attempt else 0)
    conn.execute("""
        INSERT INTO outreach(user_id, last_dm_at, attempts, dm_blocked)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            last_dm_at=excluded.last_dm_at,
            attempts=excluded.attempts,
            dm_blocked=MAX(outreach.dm_blocked, excluded.dm_blocked)
    """, (user_id, datetime.utcnow().isoformat(), attempts, 1 if blocked else 0))
    conn.commit()

def set_opt_out(user_id: int):
    conn = db()
    conn.execute("""
        INSERT INTO outreach(user_id, opt_out) VALUES (?,1)
        ON CONFLICT(user_id) DO UPDATE SET opt_out=1
    """, (user_id,))
    conn.commit()

def get_outreach_state(user_id: int):
    conn = db()
    row = conn.execute("SELECT last_dm_at, attempts, dm_blocked, opt_out FROM outreach WHERE user_id=?", (user_id,)).fetchone()
    if not row:
        return None
    last = datetime.fromisoformat(row[0]) if row[0] else None
    return {"last_dm_at": last, "attempts": row[1], "dm_blocked": bool(row[2]), "opt_out": bool(row[3])}

async def log_to_admin(guild: discord.Guild, content: str):
    ch = guild.get_channel(ADMIN_LOG_CHANNEL_ID) or await bot.fetch_channel(ADMIN_LOG_CHANNEL_ID)
    await ch.send(content)

async def ask_via_dm(member: discord.Member) -> bool:
    if is_registered(member.id):
        return True

    state = get_outreach_state(member.id) or {}
    if state.get("opt_out") or state.get("dm_blocked"):
        return False
    if state.get("attempts", 0) >= MAX_DM_ATTEMPTS:
        return False
    last = state.get("last_dm_at")
    if last and (datetime.utcnow() - last) < timedelta(days=DM_COOLDOWN_DAYS):
        return False

    try:
        dm = await member.create_dm()
        prompt = (
            "Welcome to UOC! Quick private check-in.\n"
            "What’s your **first name** and **Instagram handle**?\n"
            "Reply like: `Carson, @soln_official`\n\n"
            "_Confidential: only admins can view this._\n"
            "Prefer not to share? Reply `opt out` and I’ll stop asking."
        )
        await dm.send(prompt)

        def check(m: discord.Message):
            return m.author.id == member.id and m.channel == dm

        msg = await bot.wait_for("message", check=check, timeout=120)
        text = msg.content.strip()

        if text.lower() in {"opt out", "opt-out", "no", "no thanks"}:
            set_opt_out(member.id)
            await dm.send("No problem—I won’t ask again.")
            return False

        if "," in text:
            first, ig = [p.strip() for p in text.split(",", 1)]
        else:
            parts = text.split()
            first = parts[0] if parts else ""
            ig = parts[1] if len(parts) > 1 else ""

        if not first or not ig:
            await dm.send("I need both a first name **and** Instagram. If you change your mind later, just DM me again.")
            mark_outreach(member.id, bump_attempt=True)
            return False

        save_registration(member, first, ig)
        await dm.send("Thanks! Recorded. (Admins only can see this.)")
        await log_to_admin(member.guild, f"✅ **New UOC registration**\nUser: `{member}` (ID {member.id})\nFirst: **{first}**\nInstagram: **@{ig.lstrip('@')}**")
        return True

    except (discord.Forbidden, discord.HTTPException, asyncio.TimeoutError):
        mark_outreach(member.id, blocked=True, bump_attempt=True)
        return False

@bot.event
async def on_ready():
    if not nudge_missing.is_running():
        nudge_missing.start()
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")

@bot.event
async def on_member_join(member: discord.Member):
    if member.bot or member.guild.id != GUILD_ID:
        return
    await ask_via_dm(member)

@tasks.loop(minutes=NUDGE_INTERVAL_MIN)
async def nudge_missing():
    guild = bot.get_guild(GUILD_ID)
    if not guild:
        return
    sent = 0
    for m in guild.members:
        if sent >= NUDGE_BATCH_SIZE:
            break
        if m.bot or is_registered(m.id):
            continue
        state = get_outreach_state(m.id) or {}
        if state.get("opt_out") or state.get("dm_blocked") or state.get("attempts", 0) >= MAX_DM_ATTEMPTS:
            continue
        last = state.get("last_dm_at")
        if last and (datetime.utcnow() - last) < timedelta(days=DM_COOLDOWN_DAYS):
            continue
        await ask_via_dm(m)
        sent += 1
        await asyncio.sleep(1.2)

if __name__ == "__main__":
    if not TOKEN or not GUILD_ID or not ADMIN_LOG_CHANNEL_ID:
        raise SystemExit("Set DISCORD_TOKEN, GUILD_ID, ADMIN_LOG_CHANNEL_ID env vars.")
    bot.run(TOKEN)
