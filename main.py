import os
import discord
from discord.ext import commands
import asyncio
from keep_alive import keep_alive

# Import the bot from GPT_WORM_V2
from GPT_WORM_V2 import bot, DISCORD_TOKEN

if __name__ == "__main__":
    keep_alive()
    if DISCORD_TOKEN:
        bot.run(DISCORD_TOKEN)
    else:
        print("❌ DISCORD_TOKEN not found in environment variables.")
      
