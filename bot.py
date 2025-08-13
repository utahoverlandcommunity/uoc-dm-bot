import os
import sys
import asyncio
import discord
from discord.ext import commands

# --- Config ---
DM_REPEATS = 3
DM_INTERVAL_HOURS = 24  # 24 hours between DMs

# --- Token from environment ---
TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN or not TOKEN.strip():
    sys.exit("FATAL: DISCORD_TOKEN is missing. Set it in Render → Environment.")
if len(TOKEN.split(".")) != 3:
    sys.exit("FATAL: DISCORD_TOKEN format looks wrong (should have 3 dot-separated parts). Double-check you're using the Bot Token.")

# --- Intents ---
intents = discord.Intents.default()
intents.members = True            # requires 'Server Members Intent' enabled in Dev Portal
intents.message_content = True    # requires 'Message Content Intent' enabled in Dev Portal

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")

@bot.event
async def on_member_join(member: discord.Member):
    if member.bot:
        return

    dm_message = (
        f"Welcome to the server, {member.display_name}!\n\n"
        "Please reply with your **First and Last Name**, followed by your **Instagram handle**.\n"
        "Format: `John Doe, @yourinstagram`"
    )

    for attempt in range(DM_REPEATS):
        try:
            await member.send(dm_message)
            print(f"Sent DM attempt {attempt + 1} to {member} (ID {member.id})")
        except discord.Forbidden:
            print(f"Could not DM {member} (DMs are off)")
            break

        if attempt < DM_REPEATS - 1:
            await asyncio.sleep(DM_INTERVAL_HOURS * 3600)  # wait 24 hours between attempts

bot.run(TOKEN)
