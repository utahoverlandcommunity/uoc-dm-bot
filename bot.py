import os
import sys
import asyncio
import discord
from discord.ext import commands

# --- Config ---
DM_REPEATS = 3
DM_INTERVAL_HOURS = 24  # 24 hours between onboarding DMs

# --- Required ENV VARS ---
TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = int(os.getenv("GUILD_ID", "0"))
ADMIN_LOG_CHANNEL_ID = int(os.getenv("ADMIN_LOG_CHANNEL_ID", "0"))

# Sanity checks
if not TOKEN or not TOKEN.strip():
    sys.exit("FATAL: DISCORD_TOKEN is missing. Set it in Render → Environment.")
if len(TOKEN.split(".")) != 3:
    sys.exit("FATAL: DISCORD_TOKEN format looks wrong. Use the Bot Token from the Dev Portal.")
if not GUILD_ID or not ADMIN_LOG_CHANNEL_ID:
    sys.exit("FATAL: Set GUILD_ID and ADMIN_LOG_CHANNEL_ID env vars (numeric IDs).")

# --- Intents ---
intents = discord.Intents.default()
intents.members = True            # for on_member_join
intents.message_content = True    # to read DM replies
intents.dm_messages = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)

# In-memory guard to reduce duplicate logs after restarts (not persistent)
processed_user_ids = set()

def parse_fullname_instagram(text: str):
    """
    Expect 'First Last, @instagram'
    - Must contain a comma separating name and handle.
    - Name must be at least two words.
    - Returns (full_name, handle_without_at) or (None, None).
    """
    if "," not in text:
        return None, None
    left, right = [p.strip() for p in text.split(",", 1)]
    if not left or not right:
        return None, None
    if len(left.split()) < 2:
        return None, None
    handle = right.lstrip("@").strip()
    if not handle:
        return None, None
    return left, handle

async def log_to_admin(full_name: str, handle: str, user: discord.abc.User):
    guild = bot.get_guild(GUILD_ID)
    if not guild:
        # try fetch if not cached yet
        guild = await bot.fetch_guild(GUILD_ID)
    ch = guild.get_channel(ADMIN_LOG_CHANNEL_ID) or await bot.fetch_channel(ADMIN_LOG_CHANNEL_ID)
    await ch.send(
        f"✅ **New UOC registration**\n"
        f"**First and Last Name:** {full_name}\n"
        f"**Instagram:** @{handle}\n"
        f"**Discord User:** `{user}` (ID {user.id})"
    )

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")

@bot.event
async def on_member_join(member: discord.Member):
    if member.bot or member.guild.id != GUILD_ID:
        return

    dm_message = (
        f"Welcome to UOC, {member.display_name}!\n\n"
        "Please reply with your **First and Last Name**, followed by your **Instagram handle**.\n"
        "Format example: `John Doe, @yourinstagram`\n\n"
        "_Confidential: only admins can view this._"
    )

    for attempt in range(DM_REPEATS):
        try:
            await member.send(dm_message)
            print(f"Sent DM attempt {attempt + 1} to {member} (ID {member.id})")
        except discord.Forbidden:
            print(f"Could not DM {member} (DMs are off).")
            break
        if attempt < DM_REPEATS - 1:
            await asyncio.sleep(DM_INTERVAL_HOURS * 3600)  # wait 24 hours

@bot.event
async def on_message(message: discord.Message):
    # Only process DMs from humans
    if message.author.bot or message.guild is not None:
        return
    content = (message.content or "").strip()
    if not content:
        return

    full_name, handle = parse_fullname_instagram(content)
    if not full_name:
        # Soft nudge with the exact format we accept
        try:
            await message.channel.send(
                "I didn’t catch that. Please use this format exactly:\n"
                "`John Doe, @yourinstagram`"
            )
        except discord.HTTPException:
            pass
        return

    # Avoid duplicate logs per process lifetime
    if message.author.id in processed_user_ids:
        await message.channel.send("Thanks! Your info is already recorded. 👍")
        return

    try:
        await log_to_admin(full_name, handle, message.author)
        processed_user_ids.add(message.author.id)
        await message.channel.send("Thanks! Recorded. (Admins only can see this.)")
    except discord.Forbidden:
        await message.channel.send("I couldn't log that to the admin channel. Please ping an admin.")
    except Exception as e:
        print("Admin log error:", e)
        await message.channel.send("Something went wrong logging your info. Please try again later.")

bot.run(TOKEN)
