import os
import re
import time
import sqlite3
import threading
import logging
import tempfile
import shutil
import requests

import telebot
from telebot import types
from flask import Flask
import yt_dlp

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_USERNAME = "@nosirxojayev"
ADMIN_ID = 8019481444  # Sizning Telegram ID raqamingiz
DB_PATH = os.getenv("DB_PATH", "bot.db")
PORT = int(os.getenv("PORT", "10000"))

MAX_FILE_SIZE = 49 * 1024 * 1024

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN sozlanmagan!")

bot = telebot.TeleBot(BOT_TOKEN, threaded=True)
app = Flask(__name__)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)

active_downloads = set()
active_lock = threading.Lock()
pending_downloads = {}
pending_lock = threading.Lock()

def connect_db():
    return sqlite3.connect(DB_PATH, timeout=20)

def setup_db():
    with connect_db() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS users (
                chat_id INTEGER PRIMARY KEY,
                lang TEXT DEFAULT 'uz',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS chats (
                chat_id INTEGER PRIMARY KEY,
                chat_type TEXT
            )
        """)

def save_user(chat_id):
    with connect_db() as con:
        con.execute("INSERT OR IGNORE INTO users(chat_id) VALUES(?)", (chat_id,))

def save_chat(chat_id, chat_type):
    with connect_db() as con:
        con.execute("INSERT OR REPLACE INTO chats(chat_id, chat_type) VALUES(?, ?)", (chat_id, chat_type))

def get_language(chat_id):
    with connect_db() as con:
        row = con.execute("SELECT lang FROM users WHERE chat_id=?", (chat_id,)).fetchone()
    return row[0] if row else "uz"

def set_language(chat_id, lang):
    with connect_db() as con:
        con.execute("UPDATE users SET lang=? WHERE chat_id=?", (lang, chat_id))

TEXT = {
    "uz": {
        "choose": "🌐 Tilni tanlang:",
        "welcome": (
            "🔥 Assalomu alaykum! @DownlanderToVideoBot botiga xush kelibsiz! "
            "Men barcha ijtimoiy tarmoqlardan video yuklovchi va musiqalarni topib beruvchi universal yordamchingizman.\n\n"
            "📥 Imkoniyatlarimiz:\n"
            "• Instagram (post, reels)\n"
            "• TikTok (suv belgisiz)\n"
            "• YouTube va boshqa tarmoqlar\n"
            "• Qo'shiq nomi, ovozli xabar yoki havola orqali musiqa qidirish\n"
            "• Videolarni MP4 formatida olish\n\n"
            "🛡 Shuningdek, botni guruhga qo'shib, kirdi-chiqdi xabarlari va reklama havolalarini avtomatik tozalashingiz mumkin.\n\n"
            "Havolani yuboring! ❤️"
        ),
        "group": "➕ Guruhga qo‘shish",
        "language": "🌐 Tilni o‘zgartirish",
        "working": "⏳ Video yuklab olinmoqda...\nIltimos, kuting.",
        "uploading": "⏳ Video yuborilmoqda...",
        "done": (
            "✅ Yuklab olindi!\n\n"
            "Yuborgan linkingiz uchun @DownlanderToVideoBot "
            "nomidan sizga rahmat! ❤️\n"
            f"👨‍💻 Admin: {ADMIN_USERNAME}"
        ),
        "promo": (
            "🤖 Guruhingizni tartibli saqlang!\n"
            "Kirdi-chiqdi xabarlari va ayrim reklama "
            "havolalarini avtomatik o‘chiradi."
        ),
        "failed": "❌ Videoni yuklab bo‘lmadi. Havolani tekshiring.",
        "youtube_failed": (
            "❌ **YouTube videoni yuklab bo'lmadi.**\n\n"
            "💡 Buning sababi YouTube o'z xavfsizlik va himoya tizimini "
            "keskin kuchaytirgani bilan bog'liq. Hozircha bu shorts yoki videoni "
            "tortib bo'lmayapti. Iltimos, boshqa havola yoki Instagram/TikTok havolasini yuborib ko'ring!"
        ),
        "too_big": "⚠️ Video juda katta (49 MB dan oshadi).",
        "choose_format": "🎬 Qaysi ko‘rinishda yuboray?",
        "protect": "🛡 Guruhni tartibli saqlash rejimi."
    },
    "ru": {
        "choose": "🌐 Выберите язык:",
        "welcome": "🔥 Здравствуйте! Добро пожаловать в @DownlanderToVideoBot!",
        "group": "➕ Добавить в группу",
        "language": "🌐 Изменить язык",
        "working": "⏳ Загрузка видео...",
        "uploading": "⏳ Отправка...",
        "done": f"✅ Загружено!\n\nСпасибо за вашу ссылку! ❤️\n👨‍💻 Admin: {ADMIN_USERNAME}",
        "promo": "🤖 Поддерживайте порядок в группе!",
        "failed": "❌ Не удалось скачать.",
        "youtube_failed": "❌ YouTube усилил защиту, не удалось скачать это видео.",
        "too_big": "⚠️ Файл слишком большой.",
        "choose_format": "🎬 Выберите формат:",
        "protect": "🛡 Защита группы."
    },
    "en": {
        "choose": "🌐 Choose your language:",
        "welcome": "🔥 Hello! Welcome to @DownlanderToVideoBot!",
        "group": "➕ Add to group",
        "language": "🌐 Change language",
        "working": "⏳ Downloading...",
        "uploading": "⏳ Sending...",
        "done": f"✅ Downloaded!\n\nThank you! ❤️\n👨‍💻 Admin: {ADMIN_USERNAME}",
        "promo": "🤖 Keep your group organized!",
        "failed": "❌ Could not download.",
        "youtube_failed": "❌ YouTube has increased security.",
        "too_big": "⚠️ File is too large.",
        "choose_format": "🎬 Choose format:",
        "protect": "🛡 Group protection."
    }
}

def language_keyboard():
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("🇺🇿 O'zbekcha", callback_data="lang_uz"),
        types.InlineKeyboardButton("🇷🇺 Русский", callback_data="lang_ru"),
        types.InlineKeyboardButton("🇬🇧 English", callback_data="lang_en")
    )
    return kb

def main_keyboard(lang):
    kb = types.InlineKeyboardMarkup(row_width=1)
    username = bot.get_me().username
    kb.add(types.InlineKeyboardButton(TEXT[lang]["group"], url=f"https://t.me/{username}?startgroup=true"))
    kb.add(types.InlineKeyboardButton(TEXT[lang]["language"], callback_data="change_language"))
    return kb

def post_download_keyboard():
    kb = types.InlineKeyboardMarkup(row_width=1)
    username = bot.get_me().username
    kb.add(types.InlineKeyboardButton("➕ Guruhga qo‘shish", url=f"https://t.me/{username}?startgroup=true"))
    return kb

def format_keyboard():
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("🎬 Video", callback_data="format_video"),
        types.InlineKeyboardButton("📁 MP4", callback_data="format_mp4")
    )
    return kb

@bot.message_handler(commands=["start"])
def start(message):
    if message.chat.type != "private":
        save_chat(message.chat.id, message.chat.type)
        return
    save_user(message.chat.id)
    lang = get_language(message.chat.id)
    bot.send_message(message.chat.id, TEXT[lang]["welcome"], reply_markup=main_keyboard(lang))

@bot.message_handler(commands=["stats"])
def stats_command(message):
    if message.from_user.id != ADMIN_ID:
        return
    with connect_db() as con:
        users_count = con.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        chats_count = con.execute("SELECT COUNT(*) FROM chats").fetchone()[0]
    bot.reply_to(message, f"📊 **Bot Statistikasi:**\n\n👤 Foydalanuvchilar: {users_count}\n👥 Guruh
