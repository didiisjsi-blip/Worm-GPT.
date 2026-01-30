import requests
import discord
from discord.ext import commands
from discord.ext import commands, tasks 
import sys
import asyncio
import os
import json
import sqlite3
import aiohttp
from langdetect import detect
from datetime import datetime
from discord import ui
import time

# =========================================================
# 1. GLOBAL CONSTANTS
# =========================================================
# *** โปรดเปลี่ยน DISCORD_TOKEN ***
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")


CONFIG_FILE = "wormgpt_configmre.json"
PROMPT_FILE = "system-prompt.txt"

DEFAULT_API_KEY = os.getenv("OPENROUTER_API_KEY")

DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "google/gemini-2.5-flash" 
DEFAULT_LANGUAGE = "Thai"

SITE_URL = "https://github.com/00x0kafyy/worm-ai"
SITE_NAME = "WormGPT Discord Bot"

MAIN_COLOR = 0xFF0000
ERROR_COLOR = discord.Color.red()

# =========================================================
# 2. GUILD MANAGEMENT CONSTANTS (โปรดแก้ไข Webhook URL)
# =========================================================
# *** โปรดเปลี่ยน YOUR_WEBHOOK_URL_HERE เป็น Webhook URL จริงของคุณ ***
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")

GUILD_FILE = "guilds.json"
# =========================================================

intents = discord.Intents.default()
intents.message_content = True
# ต้องเปิด Intents 2 ตัวนี้ใน Portal ด้วย
intents.guilds = True 
intents.members = True

bot = commands.Bot(command_prefix='!', intents=intents)
tree = bot.tree


def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                config = json.load(f)
                if 'auto_reply_channels' in config:
                    del config['auto_reply_channels']
                if 'private_chats' in config:
                    pass 
                return config
        except Exception as e:
            print(f"Error loading config: {e}. Using defaults.", file=sys.stderr)

    config = {
        "api_key": DEFAULT_API_KEY,
        "base_url": DEFAULT_BASE_URL,
        "model": DEFAULT_MODEL,
        "language": DEFAULT_LANGUAGE,
        "private_chats": {}
    }
    save_config(config)
    return config

def save_config(config):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"Error saving config: {e}", file=sys.stderr)


DB_FILE = "wormgpt.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    # ตารางสำหรับเก็บการตั้งค่าของแต่ละเซิร์ฟเวอร์
    c.execute('''CREATE TABLE IF NOT EXISTS guild_settings (
        guild_id TEXT PRIMARY KEY,
        approval_channel_id TEXT,
        private_chat_category_id TEXT,
        log_channel_id TEXT,
        auto_reply_channels TEXT, -- JSON string
        allowed_role_ids TEXT -- JSON string of role IDs
    )''')
    conn.commit()
    conn.close()

# **ฟังก์ชันอ่านค่าตั้งค่าเฉพาะเซิร์ฟเวอร์**
def get_guild_setting(guild_id: int, key: str):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(f'SELECT {key} FROM guild_settings WHERE guild_id = ?', (str(guild_id),))
    row = c.fetchone()
    conn.close()
    if row and row[0] is not None:
        if key in ['auto_reply_channels', 'allowed_role_ids']:
            try: return json.loads(row[0])
            except: return []
        return row[0]
    
    if key in ['approval_channel_id', 'private_chat_category_id', 'log_channel_id']:
        return "0" 
    
    return [] if key in ['auto_reply_channels', 'allowed_role_ids'] else None

# **ฟังก์ชันตั้งค่าเฉพาะเซิร์ฟเวอร์**
def set_guild_setting(guild_id: int, key: str, value):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    if key in ['auto_reply_channels', 'allowed_role_ids']:
        value_to_save = json.dumps(value)
    else:
        value_to_save = str(value)

    c.execute('SELECT * FROM guild_settings WHERE guild_id = ?', (str(guild_id),))
    if c.fetchone():
        c.execute(f'UPDATE guild_settings SET {key} = ? WHERE guild_id = ?', (value_to_save, str(guild_id)))
    else:
        c.execute(f'INSERT INTO guild_settings (guild_id, {key}) VALUES (?, ?)', (str(guild_id), value_to_save))

    conn.commit()
    conn.close()

def add_auto_reply_channel(guild_id: int, channel_id: int):
    channels = get_guild_setting(guild_id, 'auto_reply_channels')
    if channel_id not in channels:
        channels.append(channel_id)
        set_guild_setting(guild_id, 'auto_reply_channels', channels)

def remove_auto_reply_channel(guild_id: int, channel_id: int):
    channels = get_guild_setting(guild_id, 'auto_reply_channels')
    if channel_id in channels:
        channels.remove(channel_id)
        set_guild_setting(guild_id, 'auto_reply_channels', channels)
        return True
    return False

# =========================================================
# HELPER: ตรวจสอบยศที่ได้รับอนุญาต
# =========================================================
def check_allowed_role(member: discord.Member, guild_id: int) -> bool:
    """ตรวจสอบว่าสมาชิกมีสิทธิ์ในการใช้ฟีเจอร์ที่ถูกจำกัดหรือไม่"""
    allowed_ids = get_guild_setting(guild_id, 'allowed_role_ids')
    
    # ถ้า allowed_ids เป็นรายการว่าง แสดงว่าไม่ได้ตั้งค่า (อนุญาตทุกคน)
    if not allowed_ids:
        return True
        
    member_role_ids = [role.id for role in member.roles]
    
    # ตรวจสอบว่าสมาชิกมียศใดๆ ในรายการ allowed_ids หรือไม่
    return any(role_id in allowed_ids for role_id in member_role_ids)

def format_allowed_roles(guild: discord.Guild, allowed_ids: list) -> str:
    """ฟอร์แมตรายการ Role ID เป็นข้อความที่มนุษย์อ่านได้"""
    if not allowed_ids:
        return "✅ ทุกคนสามารถใช้งานได้ (ไม่มีการจำกัดยศ)"
    
    role_mentions = []
    for r_id in allowed_ids:
        role = guild.get_role(r_id)
        if role:
            role_mentions.append(role.mention)
        else:
            role_mentions.append(f"บทบาทที่ไม่พบ: `{r_id}`")
            
    return "❌ จำกัดเฉพาะยศ:\n" + ", ".join(role_mentions)

# =========================================================
# GUILD MANAGEMENT FUNCTIONS (แก้ไข joined_at)
# =========================================================
def update_guild_file(bot):
    """เขียนรายการเซิร์ฟเวอร์ทั้งหมดที่บอทเข้าร่วมลงในไฟล์ JSON"""
    guild_data = []
    for guild in bot.guilds:
        # FIX: แก้ไขการเข้าถึง joined_at โดยใช้ guild.me.joined_at แทน guild.joined_at
        joined_at = guild.me.joined_at if guild.me else None
        
        guild_data.append({
            "id": str(guild.id),
            "name": guild.name,
            "member_count": guild.member_count,
            "owner_id": str(guild.owner_id),
            "joined_at": joined_at.isoformat() if joined_at else None
        })

    try:
        with open(GUILD_FILE, "w", encoding="utf-8") as f:
            json.dump(guild_data, f, indent=2, ensure_ascii=False)
        print(f"✅ Updated {GUILD_FILE} with {len(guild_data)} guilds.")
    except Exception as e:
        print(f"❌ Error writing guild file: {e}", file=sys.stderr)


# *** แก้ไข: เพิ่ม invite_url ใน Webhook ***
async def send_guild_webhook(guild: discord.Guild, is_join: bool, invite_url: str = None):
    """ส่ง Webhook แจ้งเตือนเมื่อบอทเข้า/ออกจากเซิร์ฟเวอร์"""
    if WEBHOOK_URL == "YOUR_WEBHOOK_URL_HERE":
        print("⚠️ WEBHOOK_URL is not set. Skipping webhook notification.", file=sys.stderr)
        return
        
    action = "✅ เข้าร่วม" if is_join else "❌ ออกจาก"
    color = 0x00FF00 if is_join else 0xFF0000

    embed = {
        "title": f"บอท {action} เซิร์ฟเวอร์ใหม่",
        "description": f"**{action} เซิร์ฟเวอร์:** {guild.name}",
        "color": color,
        "timestamp": datetime.now().isoformat(),
        "fields": [
            {"name": "ID", "value": f"`{guild.id}`", "inline": True},
            {"name": "สมาชิก", "value": f"{guild.member_count}", "inline": True},
            # เพิ่ม Invite Link
            {"name": "ลิงก์เชิญ", "value": f"[คลิกเพื่อเข้าสู่เซิร์ฟเวอร์]({invite_url})" if invite_url and is_join else "N/A", "inline": False},
            {"name": "เจ้าของ (ID)", "value": f"`{guild.owner_id}`", "inline": False},
        ],
        "footer": {"text": f"ปัจจุบันอยู่: {len(bot.guilds)} เซิร์ฟเวอร์"}
    }
    
    payload = {
        "embeds": [embed]
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(WEBHOOK_URL, json=payload) as response:
                if response.status not in (200, 204):
                    print(f"❌ Failed to send webhook. Status: {response.status}", file=sys.stderr)
                else:
                    print(f"✅ Webhook sent successfully for {action} {guild.name}")
    except Exception as e:
        print(f"❌ Error sending webhook: {e}", file=sys.stderr)
# =========================================================


def get_jailbreak_prompt():
    if not os.path.exists(PROMPT_FILE):
        default_prompt = "You are WormGPT, an advanced AI assistant. Respond as quickly as possible while maintaining high quality. Be concise but informative. Always respond in the user's language. Provide accurate and helpful answers."
        with open(PROMPT_FILE, "w", encoding="utf-8") as f:
            f.write(default_prompt)
        return default_prompt

    try:
        with open(PROMPT_FILE, "r", encoding="utf-8") as f:
            content = f.read().strip()
            if content:
                return content
            else:
                return "You are WormGPT, an advanced AI assistant. Respond as quickly as possible while maintaining high quality. Be concise but informative. Always respond in the user's language. Provide accurate and helpful answers."
    except Exception as e:
        print(f"Error reading system-prompt: {e}. Using default.", file=sys.stderr)
        return "You are WormGPT, an advanced AI assistant. Respond as quickly as possible while maintaining high quality. Be concise but informative. Always respond in the user's language. Provide accurate and helpful answers."


async def call_api_async(user_input):
    config = load_config()

    try:
        detected_lang = detect(user_input[:500])
        lang_map = {'id':'Indonesian','en':'English','es':'Spanish','ar':'Arabic','th':'Thai','pt':'Portuguese'}
        current_lang = lang_map.get(detected_lang, 'English')
    except:
        current_lang = config["language"]

    try:
        headers = {
            "Authorization": f"Bearer {config['api_key']}",
            "HTTP-Referer": SITE_URL,
            "X-Title": SITE_NAME,
            "Content-Type": "application/json"
        }

        max_tokens = 8000

        data = {
            "model": config["model"],
            "messages": [
                {"role": "system", "content": get_jailbreak_prompt()},
                {"role": "user", "content": user_input}
            ],
            "max_tokens": max_tokens,
            "temperature": 0.3
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(f"{config['base_url']}/chat/completions", headers=headers, json=data) as response:
                response.raise_for_status()
                result = await response.json()
                return result['choices'][0]['message']['content']

    except aiohttp.ClientError as e:
        error_message = f"API Request Error: {e}"
        try:
            error_details = await response.json()
            if 'error' in error_details and 'message' in error_details['error']:
                error_message = f"OpenRouter Error: {error_details['error']['message']}"
        except:
            pass
        return f"🤖 **[WormGPT API Error]**: {error_message}"
    except Exception as e:
        return f"🤖 **[WormGPT API Error]**: Unexpected error: {e}"


async def read_text_attachment(
    attachment: discord.Attachment,
    max_size=1_000_000
):
    if attachment.size > max_size:
        return f"[ไฟล์ {attachment.filename} ใหญ่เกินไป]"

    allowed_ext = (
        ".txt", ".md", ".json",
        ".py", ".js", ".html", ".css"
    )

    if not attachment.filename.lower().endswith(allowed_ext):
        return f"[ไม่รองรับไฟล์ {attachment.filename}]"

    try:
        data = await attachment.read()
        return data.decode("utf-8", errors="ignore")
    except Exception as e:
        return f"[อ่านไฟล์ {attachment.filename} ไม่สำเร็จ: {e}]"


async def send_ai_response(channel, question_text, response_text, reply_to_message=None):
    if response_text.startswith("🤖 **[WormGPT API Error]**"):
        error_embed = discord.Embed(
            title="❌ การเรียกใช้ API ผิดพลาด",
            description=response_text,
            color=ERROR_COLOR,
            timestamp=datetime.now()
        )
        if reply_to_message:
            await reply_to_message.reply(embed=error_embed)
        else:
            await channel.send(embed=error_embed)
        return

    MAX_DISCORD_MESSAGE_LENGTH = 2000
    
    if len(response_text) <= MAX_DISCORD_MESSAGE_LENGTH:
        
        response_embed = discord.Embed(
            title="✨ คำตอบจาก WormGPT",
            description=response_text,
            color=MAIN_COLOR,
            timestamp=datetime.now()
        )
        truncated_question = question_text[:500] + ('...' if len(question_text) > 500 else '')
        response_embed.add_field(name="คำถามต้นฉบับ", value=f"```\n{truncated_question}\n```", inline=False)
        response_embed.set_footer(text="WormGPT | ตอบกลับสั้น")

        if reply_to_message:
            await reply_to_message.reply(embed=response_embed)
        else:
            await channel.send(embed=response_embed)
        
    else:
        
        timestamp_str = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"WormGPT_Response_{timestamp_str}.txt"
        file_path = os.path.join(os.getcwd(), filename)

        try:
            file_content = (
                f"--- คำถามต้นฉบับ ---\n"
                f"{question_text}\n\n"
                f"--- คำตอบจาก WormGPT ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')}) ---\n"
                f"{response_text}"
            )
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(file_content)

            file = discord.File(file_path, filename=filename)

            file_embed = discord.Embed(
                title="📄 คำตอบถูกส่งเป็นไฟล์ข้อความ (ข้อความยาว)",
                description=f"✅ คำตอบสำหรับคำถามของคุณมีความยาวเกิน 2000 ตัวอักษร จึงถูกสร้างเป็นไฟล์ `{filename}`",
                color=MAIN_COLOR,
                timestamp=datetime.now()
            )
            truncated_question = question_text[:500] + ('...' if len(question_text) > 500 else '')
            file_embed.add_field(name="คำถามต้นฉบับ", value=f"```\n{truncated_question}\n```", inline=False)
            file_embed.set_footer(text="WormGPT | สร้างไฟล์ TXT เพื่อเลี่ยงข้อจำกัดของข้อความยาว")

            if reply_to_message:
                await reply_to_message.reply(embed=file_embed, file=file)
            else:
                await channel.send(embed=file_embed, file=file)

        except Exception as e:
            error_embed = discord.Embed(
                title="❌ ข้อผิดพลาดในการจัดการไฟล์",
                description=f"ไม่สามารถสร้างหรือส่งไฟล์ `.txt` ได้: {e}",
                color=ERROR_COLOR
            )
            await channel.send(embed=error_embed)
        finally:
            if os.path.exists(file_path):
                os.remove(file_path)

class ConfirmView(ui.View):
    def __init__(self, bot, channel_to_add: discord.TextChannel, original_author_id: int):
        super().__init__(timeout=300)
        self.bot = bot
        self.channel_to_add = channel_to_add
        self.original_author_id = original_author_id
        self.guild_id = channel_to_add.guild.id

    @ui.button(label="✅ ยืนยันการเปิดใช้งาน", style=discord.ButtonStyle.success, custom_id="confirm_add")
    async def confirm_button(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.guild.id != self.guild_id:
            await interaction.response.send_message("❌ การกระทำนี้ต้องทำในเซิร์ฟเวอร์เดิม", ephemeral=True)
            return
            
        if not interaction.user.guild_permissions.manage_channels:
            await interaction.response.send_message("❌ คุณไม่มีสิทธิ์ `Manage Channels`", ephemeral=True)
            return

        channels = get_guild_setting(self.guild_id, 'auto_reply_channels')
        channel_id = self.channel_to_add.id

        if channel_id in channels:
            await interaction.response.send_message(
                f"⚠️ {self.channel_to_add.mention} เปิดใช้งานอยู่แล้ว", ephemeral=True
            )
            return

        add_auto_reply_channel(self.guild_id, channel_id)

        await interaction.response.send_message(
            f"✅ เปิดใช้งาน WormGPT Auto-Reply ใน {self.channel_to_add.mention} สำเร็จ!", ephemeral=True
        )

        original_user = self.bot.get_user(self.original_author_id)
        if original_user:
            try:
                await original_user.send(
                    f"🎉 คำขอของคุณได้รับการอนุมัติแล้ว! WormGPT จะตอบทุกข้อความใน {self.channel_to_add.mention} โดยอัตโนมัติ"
                )
            except:
                pass

        for child in self.children:
            child.disabled = True
        await interaction.message.edit(view=self)

    @ui.button(label="❌ ยกเลิก", style=discord.ButtonStyle.danger, custom_id="cancel_add")
    async def cancel_button(self, interaction: discord.Interaction, button: ui.Button):
        if not interaction.user.guild_permissions.manage_channels:
            await interaction.response.send_message("❌ คุณไม่มีสิทธิ์ `Manage Channels`", ephemeral=True)
            return
        
        await interaction.response.send_message("❌ ยกเลิกการเปิดใช้งาน", ephemeral=True)

        for child in self.children:
            child.disabled = True
        await interaction.message.edit(view=self)

class PrivateChatView(ui.View):
    def __init__(self, bot, guild_id: int):
        super().__init__(timeout=None)
        self.bot = bot
        self.guild_id = guild_id
        self.add_item(discord.ui.Button(label="Discord", style=discord.ButtonStyle.secondary, url="https://discord.gg/k2BerbWpbe", emoji="<a:discord_loading:1454254193974968484>"))
        # ปุ่ม "🎁 รับฟรี 2 วัน" ถูกลบออกไปแล้วในโค้ดนี้ ตามคำขอ

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not interaction.guild or interaction.guild.id != self.guild_id:
            await interaction.response.send_message("❌ คำสั่งนี้ใช้ได้เฉพาะในเซิร์ฟเวอร์นี้เท่านั้น", ephemeral=True)
            return False
            
        user_id_str = str(interaction.user.id)
        config = load_config() 
        private_chats = config.get('private_chats', {})

        if user_id_str in private_chats:
            channel_id = private_chats[user_id_str]
            channel = self.bot.get_channel(channel_id)
            
            if channel and channel.guild and channel.guild.id == self.guild_id:
                await interaction.response.send_message(
                    f"⚠️ คุณมีห้องส่วนตัวอยู่แล้ว: {channel.mention}\n"
                    f"หากต้องการสร้างห้องใหม่ กรุณาใช้คำสั่ง **/delete_private_chat** เพื่อลบห้องเดิมก่อน", 
                    ephemeral=True
                )
                return False 
            elif channel and channel.guild and channel.guild.id != self.guild_id:
                await interaction.response.send_message(
                    f"⚠️ คุณมีห้องส่วนตัวอยู่แล้วในเซิร์ฟเวอร์อื่น: {channel.guild.name}\n"
                    f"ไม่อนุญาตให้สร้างมากกว่า 1 ห้อง",
                    ephemeral=True
                )
                return False
            else:
                # Cleanup logic
                del config['private_chats'][user_id_str]
                save_config(config)
  
