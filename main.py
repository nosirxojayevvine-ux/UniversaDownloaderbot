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
        "welcome": "🔥 Assalomu alaykum!\n\n🤖 @DownlanderToVideoBot botiga xush kelibsiz!\n\n📥 Havolani yuboring — formatni tanlang!",
        "group": "➕ Guruhga qo‘shish",
        "language": "🌐 Tilni o‘zgartirish",
        "working": "⏳ Video yuklab olinmoqda...\nIltimos, kuting.",
        "uploading": "⏳ Video yuborilmoqda...",
        "done": "✅ Yuklab olindi!\n\n@DownlanderToVideoBot ❤️",
        "failed": "❌ Videoni yuklab bo‘lmadi. Havolani tekshiring.",
        "too_big": "⚠️ Video juda katta (49 MB dan oshadi).",
        "choose_format": "🎬 Qaysi ko‘rinishda yuboray?",
        "protect": "🛡 Guruhni tartibli saqlash rejimi."
    },
    "ru": {
        "choose": "🌐 Выберите язык:",
        "welcome": "🔥 Здравствуйте!\n\n🤖 Добро пожаловать в @DownlanderToVideoBot!\n\n📥 Отправьте ссылку на видео.",
        "group": "➕ Добавить в группу",
        "language": "🌐 Изменить язык",
        "working": "⏳ Загрузка видео...",
        "uploading": "⏳ Отправка...",
        "done": "✅ Загружено!\n\n@DownlanderToVideoBot ❤️",
        "failed": "❌ Не удалось скачать.",
        "too_big": "⚠️ Файл слишком большой (более 49 МБ).",
        "choose_format": "🎬 Выберите формат:",
        "protect": "🛡 Защита группы."
    },
    "en": {
        "choose": "🌐 Choose your language:",
        "welcome": "🔥 Hello!\n\n🤖 Welcome to @DownlanderToVideoBot!\n\n📥 Send a video link.",
        "group": "➕ Add to group",
        "language": "🌐 Change language",
        "working": "⏳ Downloading...",
        "uploading": "⏳ Sending...",
        "done": "✅ Downloaded!\n\n@DownlanderToVideoBot ❤️",
        "failed": "❌ Could not download.",
        "too_big": "⚠️ File is too large (over 49 MB).",
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

@bot.callback_query_handler(func=lambda call: call.data == "change_language")
def change_language(call):
    bot.answer_callback_query(call.id)
    bot.send_message(call.message.chat.id, "🌐 Tilni tanlang:", reply_markup=language_keyboard())

@bot.callback_query_handler(func=lambda call: call.data.startswith("lang_"))
def select_language(call):
    lang = call.data.replace("lang_", "")
    if lang not in TEXT:
        return
    save_user(call.message.chat.id)
    set_language(call.message.chat.id, lang)
    bot.answer_callback_query(call.id, "✅")
    bot.send_message(call.message.chat.id, TEXT[lang]["welcome"], reply_markup=main_keyboard(lang))

URL_RE = re.compile(r"https?://[^\s<>()]+", re.IGNORECASE)

def extract_url(text):
    match = URL_RE.search(text or "")
    if not match:
        return None
    return match.group(0).rstrip(".,!?)]}")

def download_youtube_via_api(url, workdir):
    api_url = "https://co.wuk.sh/api/json"
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    data = {"url": url, "vQuality": "720"}
    response = requests.post(api_url, json=data, headers=headers, timeout=30)
    res_json = response.json()
    
    if res_json.get("status") in ["redirect", "stream"]:
        download_link = res_json.get("url")
    elif res_json.get("status") == "picker":
        download_link = res_json.get("picker")[0].get("url")
    else:
        raise Exception("API YouTube havolasini o'qiy olmadi")
        
    file_path = os.path.join(workdir, "youtube_video.mp4")
    with requests.get(download_link, stream=True, timeout=60) as r:
        r.raise_for_status()
        with open(file_path, 'wb') as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)
    return file_path, {"title": "YouTube Video"}

def download_media(url, workdir):
    if "youtube.com" in url or "youtu.be" in url:
        return download_youtube_via_api(url, workdir)

    output_template = os.path.join(workdir, "%(title).80s-%(id)s.%(ext)s")
    options = {
        "outtmpl": output_template,
        "format": "best[ext=mp4][filesize<49M]/best[filesize<49M]/best",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "max_filesize": MAX_FILE_SIZE,
        "socket_timeout": 25,
    }
    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=True)
        path = ydl.prepare_filename(info)
        base, _ = os.path.splitext(path)
        if os.path.exists(base + ".mp4"):
            path = base + ".mp4"
    if os.path.getsize(path) > MAX_FILE_SIZE:
        raise ValueError("FILE_TOO_LARGE")
    return path, info

@bot.message_handler(func=lambda m: bool(extract_url(m.text or m.caption or "")), content_types=["text", "photo", "video", "document"])
def handle_video_link(message):
    if message.chat.type != "private":
        return
    chat_id = message.chat.id
    lang = get_language(chat_id)
    url = extract_url(message.text or message.caption or "")
    if not url:
        return

    status_msg = bot.reply_to(message, TEXT[lang]["working"])
    workdir = tempfile.mkdtemp(prefix="downloader_")
    try:
        path, info = download_media(url, workdir)
        bot.edit_message_text(TEXT[lang]["choose_format"], chat_id, status_msg.message_id, reply_markup=format_keyboard())
        pending_downloads[(chat_id, status_msg.message_id)] = {
            "path": path, "lang": lang, "reply_to": message.message_id, "workdir": workdir
        }
    except Exception:
        bot.edit_message_text(TEXT[lang]["failed"], chat_id, status_msg.message_id)
        shutil.rmtree(workdir, ignore_errors=True)

@bot.callback_query_handler(func=lambda call: call.data in ("format_video", "format_mp4"))
def send_downloaded_file(call):
    chat_id = call.message.chat.id
    key = (chat_id, call.message.message_id)
    item = pending_downloads.get(key)
    if not item:
        bot.answer_callback_query(call.id, "Muddati tugagan.", show_alert=True)
        return

    bot.answer_callback_query(call.id, "Yuborilmoqda...")
    path, lang, reply_id, workdir = item["path"], item["lang"], item["reply_to"], item["workdir"]

    try:
        bot.edit_message_text(TEXT[lang]["uploading"], chat_id, call.message.message_id)
        with open(path, "rb") as media:
            if call.data == "format_video":
                bot.send_video(chat_id, media, reply_to_message_id=reply_id, caption=TEXT[lang]["done"], timeout=120)
            else:
                bot.send_document(chat_id, media, reply_to_message_id=reply_id, caption=TEXT[lang]["done"], timeout=120)
        bot.send_message(chat_id, TEXT[lang]["promo"], reply_markup=post_download_keyboard())
        bot.edit_message_text("✅ Yuklab olindi!", chat_id, call.message.message_id)
    except Exception:
        bot.send_message(chat_id, "❌ Xatolik yuz berdi.")
    finally:
        pending_downloads.pop(key, None)
        shutil.rmtree(workdir, ignore_errors=True)

@app.route("/")
def home():
    return "Bot is running!"

@app.route("/health")
def health():
    return {"status": "ok"}

if __name__ == "__main__":
    setup_db()
    # Telegram botni alohida fonda (thread) ishga tushiramiz
    threading.Thread(target=lambda: bot.infinity_polling(skip_pending=True), daemon=True).start()
    # Flask asosiy oqimda ishlaydi va Render portini band qilib turadi
    app.run(host="0.0.0.0", port=PORT)
