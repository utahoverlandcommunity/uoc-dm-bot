import discord
from discord.ext import commands, tasks
import asyncio

TOKEN = "YOUR_BOT_TOKEN"
DM_REPEATS = 3
DM_INTERVAL_HOURS = 24  # Wait 24 hours between messages

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")

@bot.event
async def on_member_join(member):
    if member.bot:
        return

    dm_message = (
        f"Welcome to the server, {member.display_name}!\n\n"
        "Please reply with your **First Name + Last Name** and **Instagram handle** "
        "(example: John Doe, @yourinstagram)."
    )

    for attempt in range(DM_REPEATS):
        try:
            await member.send(dm_message)
            print(f"Sent DM attempt {attempt+1} to {member.name}")
        except discord.Forbidden:
            print(f"Could not DM {member.name} (DMs are off)")
            break

        if attempt < DM_REPEATS - 1:
            await asyncio.sleep(DM_INTERVAL_HOURS * 3600)  # wait 24 hours

bot.run(TOKEN)
