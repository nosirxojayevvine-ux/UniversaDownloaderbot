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
ADMIN_ID = 8019481444
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

pending_downloads = {}

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
        "welcome": "🔥 Barcha ijtimoiy tarmoqlardan video yuklovchi va musiqalarni topib beruvchi universal bot. Havolani yuboring! ❤️",
        "group": "➕ Guruhga qo‘shish",
        "language": "🌐 Tilni o‘zgartirish",
        "working": "⏳ Video yuklab olinmoqda...",
        "uploading": "⏳ Video yuborilmoqda...",
        "done": f"✅ Yuklab olindi!\n\nAdmin: {ADMIN_USERNAME}",
        "promo": "🤖 Guruhingizni tartibli saqlang!",
        "failed": "❌ Videoni yuklab bo‘lmadi.",
        "youtube_failed": "❌ YouTube videoni yuklab bo'lmadi.",
        "too_big": "⚠️ Video juda katta.",
        "choose_format": "🎬 Qaysi ko‘rinishda yuboray?",
        "protect": "🛡 Guruhni himoya qilish."
    },
    "ru": {
        "choose": "🌐 Выберите язык:",
        "welcome": "🔥 Универсальный бот для скачивания видео. Отправьте ссылку! ❤️",
        "group": "➕ Добавить в группу",
        "language": "🌐 Изменить язык",
        "working": "⏳ Загрузка...",
        "uploading": "⏳ Отправка...",
        "done": f"✅ Загружено!\nAdmin: {ADMIN_USERNAME}",
        "promo": "🤖 Порядок в группе!",
        "failed": "❌ Не удалось скачать.",
        "youtube_failed": "❌ Ошибка YouTube.",
        "too_big": "⚠️ Файл большой.",
        "choose_format": "🎬 Формат:",
        "protect": "🛡 Защита."
    },
    "en": {
        "choose": "🌐 Choose language:",
        "welcome": "🔥 Universal video downloader bot. Send link! ❤️",
        "group": "➕ Add to group",
        "language": "🌐 Change language",
        "working": "⏳ Downloading...",
        "uploading": "⏳ Sending...",
        "done": f"✅ Downloaded!\nAdmin: {ADMIN_USERNAME}",
        "promo": "🤖 Keep order!",
        "failed": "❌ Failed.",
        "youtube_failed": "❌ YouTube error.",
        "too_big": "⚠️ Too large.",
        "choose_format": "🎬 Format:",
        "protect": "🛡 Protect."
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
    kb.add(types.InlineKeyboardButton(TEXT[lang]["language"], callback_data="change_
