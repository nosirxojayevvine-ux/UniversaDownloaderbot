import os
import re
import time
import sqlite3
import threading
import logging
import tempfile
import shutil

import telebot
from telebot import types
from flask import Flask
import yt_dlp

# =============== SOZLAMALAR ===============

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "8019481444"))
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


# =============== DATABASE ===============

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
        con.execute(
            "INSERT OR IGNORE INTO users(chat_id) VALUES(?)",
            (chat_id,)
        )


def save_chat(chat_id, chat_type):
    with connect_db() as con:
        con.execute(
            "INSERT OR REPLACE INTO chats(chat_id, chat_type) VALUES(?, ?)",
            (chat_id, chat_type)
        )


def get_language(chat_id):
    with connect_db() as con:
        row = con.execute(
            "SELECT lang FROM users WHERE chat_id=?",
            (chat_id,)
        ).fetchone()

    return row[0] if row else "uz"


def set_language(chat_id, lang):
    with connect_db() as con:
        con.execute(
            "UPDATE users SET lang=? WHERE chat_id=?",
            (lang, chat_id)
        )


# =============== MATNLAR ===============

TEXT = {
    "uz": {
        "choose": "🌐 Tilni tanlang:",

        "welcome": (
            "🔥 Assalomu alaykum!\n\n"
            "🤖 @DownlanderToVideoBot botiga xush kelibsiz!\n\n"
            "📥 Ochiq va yuklab olishga ruxsat berilgan "
            "havolalarni yuboring.\n\n"
            "🚀 Havolani yuboring — formatni tanlang!"
        ),

        "group": "➕ Guruhga qo‘shish",
        "language": "🌐 Tilni o‘zgartirish",

        "working": "⏳ Video/MP4 yuklab olinmoqda...\nIltimos, kuting.",

        "uploading": "⏳ Video/MP4 yuborilmoqda...",

        "done": (
            "✅ Yuklab olindi!\n\n"
            "Yuborgan linkingiz uchun @DownlanderToVideoBot "
            "nomidan sizga rahmat! ❤️"
        ),

        "promo": (
            "🤖 Guruhingizni tartibli saqlang!\n"
            "Kirdi-chiqdi xabarlari va ayrim reklama "
            "havolalarini avtomatik o‘chiradi."
        ),

        "failed": (
            "❌ Videoni yuklab bo‘lmadi.\n"
            "Havolani tekshiring yoki boshqa havola yuboring."
        ),

        "too_big": (
            "⚠️ Video Telegram orqali yuborish uchun "
            "juda katta (49 MB dan oshadi)."
        ),

        "choose_format": "🎬 Qaysi ko‘rinishda yuboray?",

        "protect": (
            "🛡 Guruhni tartibli saqlash\n\n"
            "• A'zolar kirgandagi xizmat xabarlarini o‘chiradi.\n"
            "• A'zolar chiqib ketgandagi xizmat xabarlarini o‘chiradi.\n"
            "• Ayrim Telegram taklif havolalarini o‘chiradi.\n\n"
            "⚙️ Botga guruhda xabarlarni o‘chirish huquqini bering."
        )
    },

    "ru": {
        "choose": "🌐 Выберите язык:",
        "welcome": (
            "🔥 Здравствуйте!\n\n"
            "🤖 Добро пожаловать в @DownlanderToVideoBot!\n\n"
            "📥 Отправьте открытую ссылку на видео."
        ),
        "group": "➕ Добавить в группу",
        "language": "🌐 Изменить язык",
        "working": "⏳ Видео/MP4 загружается...",
        "uploading": "⏳ Отправка видео/MP4...",
        "done": "✅ Загружено!\n\nСпасибо за вашу ссылку от имени @DownlanderToVideoBot! ❤️",
        "promo": "🤖 Поддерживайте порядок в группе! Бот удаляет сообщения о входе/выходе и некоторые рекламные ссылки.",
        "failed": "❌ Не удалось скачать видео. Проверьте ссылку.",
        "too_big": "⚠️ Файл слишком большой (более 49 МБ).",
        "choose_format": "🎬 Выберите формат отправки:",
        "protect": "🛡 Бот удаляет служебные сообщения о входе/выходе и некоторые ссылки-приглашения. Дайте боту право удалять сообщения."
    },

    "en": {
        "choose": "🌐 Choose your language:",
        "welcome": (
            "🔥 Hello!\n\n"
            "🤖 Welcome to @DownlanderToVideoBot!\n\n"
            "📥 Send a public video link."
        ),
        "group": "➕ Add to group",
        "language": "🌐 Change language",
        "working": "⏳ Video/MP4 is downloading...",
        "uploading": "⏳ Sending video/MP4...",
        "done": "✅ Downloaded!\n\nThank you for your link from @DownlanderToVideoBot! ❤️",
        "promo": "🤖 Keep your group organized! The bot removes join/leave messages and some promotional links.",
        "failed": "❌ Could not download this video. Check the link.",
        "too_big": "⚠️ File is too large (over 49 MB).",
        "choose_format": "🎬 Choose the sending format:",
        "protect": "🛡 The bot removes join/leave service messages and some invite links. Give it permission to delete messages."
    },

    "ar": {
        "choose": "🌐 اختر لغتك:",
        "welcome": "🔥 مرحباً!\n\n🤖 أهلاً بك في @DownlanderToVideoBot!\n\n📥 أرسل رابط فيديو عام.",
        "group": "➕ أضف إلى المجموعة",
        "language": "🌐 تغيير اللغة",
        "working": "⏳ جارٍ تنزيل الفيديو...",
        "uploading": "⏳ جارٍ إرسال الفيديو...",
        "done": "✅ تم التنزيل!\n\nشكراً على الرابط من @DownlanderToVideoBot! ❤️",
        "promo": "🤖 حافظ على تنظيم مجموعتك! يحذف البوت رسائل الدخول والخروج وبعض الروابط الإعلانية.",
        "failed": "❌ تعذر تنزيل الفيديو. تحقق من الرابط.",
        "too_big": "⚠️ الملف كبير جداً (أكثر من 49 ميغابايت).",
        "choose_format": "🎬 اختر طريقة الإرسال:",
        "protect": "🛡 يحذف البوت رسائل الدخول والخروج وبعض روابط الدعوة. امنحه صلاحية حذف الرسائل."
    }
}


# =============== TUGMALAR ===============

def language_keyboard():
    kb = types.InlineKeyboardMarkup(row_width=2)

    kb.add(
        types.InlineKeyboardButton("🇺🇿 O'zbekcha", callback_data="lang_uz"),
        types.InlineKeyboardButton("🇷🇺 Русский", callback_data="lang_ru"),
        types.InlineKeyboardButton("🇬🇧 English", callback_data="lang_en"),
        types.InlineKeyboardButton("🇸🇦 العربية", callback_data="lang_ar")
    )

    return kb


def main_keyboard(lang):
    kb = types.InlineKeyboardMarkup(row_width=1)

    username = bot.get_me().username

    kb.add(
        types.InlineKeyboardButton(
            TEXT[lang]["group"],
            url=f"https://t.me/{username}?startgroup=true"
        )
    )

    kb.add(
        types.InlineKeyboardButton(
            TEXT[lang]["language"],
            callback_data="change_language"
        )
    )

    return kb


def post_download_keyboard():
    kb = types.InlineKeyboardMarkup(row_width=1)

    username = bot.get_me().username

    kb.add(
        types.InlineKeyboardButton(
            "➕ Guruhga qo‘shish",
            url=f"https://t.me/{username}?startgroup=true"
        )
    )

    return kb


def format_keyboard():
    kb = types.InlineKeyboardMarkup(row_width=2)

    kb.add(
        types.InlineKeyboardButton(
            "🎬 Video",
            callback_data="format_video"
        ),
        types.InlineKeyboardButton(
            "📁 MP4",
            callback_data="format_mp4"
        )
    
