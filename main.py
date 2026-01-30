import os
import discord
from discord.ext import commands
import asyncio
from keep_alive import keep_alive

# Import the bot from GPT_WORM_V2
from GPT_WORM_V2 import bot, DISCORD_TOKEN

@bot.event
async def on_ready():
    try:
        # บรรทัดนี้แหละสัดที่จะทำให้คำสั่ง Slash Command โผล่ใน Discord
        synced = await bot.tree.sync()
        print(f"✅ Synced {len(synced)} commands!")
        print(f'😈 [WormGPT] Online as {bot.user}')
    except Exception as e:
        print(f"❌ Sync Error: {e}")

if __name__ == "__main__":
    keep_alive()
    if DISCORD_TOKEN:
        bot.run(DISCORD_TOKEN)
    else:
        print("❌ DISCORD_TOKEN not found in environment variables.")

