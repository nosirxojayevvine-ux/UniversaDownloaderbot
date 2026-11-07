
import os
import re
import time
import sqlite3
import logging
import tempfile
import threading
import shutil

import telebot
from telebot import types
from flask import Flask
import yt_dlp

# ================= SETTINGS =================

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = 8019481444
ADMIN_USERNAME = "@nosirxojayev"

DB_PATH = os.getenv("DB_PATH", "bot.db")
PORT = int(os.getenv("PORT", "10000"))

# Telegram va hosting limitlariga bog'liq
MAX_FILE_SIZE = 1024 * 1024 * 1024

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN sozlanmagan!")

bot = telebot.TeleBot(BOT_TOKEN, threaded=True)
app = Flask(__name__)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)

URL_RE = re.compile(r"https?://[^\s]+", re.I)
pending_downloads = {}
lock = threading.Lock()

# ================= DATABASE =================

def connect_db():
    return sqlite3.connect(DB_PATH, timeout=30)

def setup_db():
    with connect_db() as con:
        con.execute("""
        CREATE TABLE IF NOT EXISTS users(
            chat_id INTEGER PRIMARY KEY,
            lang TEXT DEFAULT 'uz'
        )
        """)
        con.execute("""
        CREATE TABLE IF NOT EXISTS chats(
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
            "INSERT OR REPLACE INTO chats VALUES(?,?)",
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

setup_db()

# ================= TEXTS =================

TEXT = {
    "uz": {
        "welcome": "🔥 Universal video yuklovchi bot!\n\nVideo havolasini yuboring.",
        "working": "⏳ Video yuklab olinmoqda...",
        "uploading": "⏳ Video yuborilmoqda...",
        "done": "✅ Yuklab olindi!\n\nYuborgan havolangiz uchun rahmat! ❤️",
        "failed": "❌ Videoni yuklab bo‘lmadi.",
        "big": "⚠️ Video hajmi juda katta.",
        "choose": "🎬 Qaysi formatda yuboray?",
        "group": "➕ Guruhga qo‘shish",
        "language": "🌐 Tilni o‘zgartirish",
        "promo": "🤖 Guruhingizni tartibli saqlang!",
    },
    "ru": {
        "welcome": "🔥 Универсальный загрузчик видео!\n\nОтправьте ссылку.",
        "working": "⏳ Загрузка видео...",
        "uploading": "⏳ Отправка видео...",
        "done": "✅ Готово! Спасибо за ссылку! ❤️",
        "failed": "❌ Не удалось скачать видео.",
        "big": "⚠️ Файл слишком большой.",
        "choose": "🎬 Выберите формат:",
        "group": "➕ Добавить в группу",
        "language": "🌐 Изменить язык",
        "promo": "🤖 Порядок в вашей группе!",
    },
    "en": {
        "welcome": "🔥 Universal video downloader!\n\nSend a video link.",
        "working": "⏳ Downloading video...",
        "uploading": "⏳ Sending video...",
        "done": "✅ Downloaded! Thank you! ❤️",
        "failed": "❌ Download failed.",
        "big": "⚠️ File is too large.",
        "choose": "🎬 Choose format:",
        "group": "➕ Add to group",
        "language": "🌐 Change language",
        "promo": "🤖 Keep your group organized!",
    }
}

# ================= KEYBOARDS =================

def language_keyboard():
    kb = types.InlineKeyboardMarkup()
    kb.add(
        types.InlineKeyboardButton("🇺🇿 O‘zbekcha", callback_data="lang_uz"),
        types.InlineKeyboardButton("🇷🇺 Русский", callback_data="lang_ru"),
        types.InlineKeyboardButton("🇬🇧 English", callback_data="lang_en")
    )
    return kb

def main_keyboard(lang):
    kb = types.InlineKeyboardMarkup()
    username = bot.get_me().username

    kb.add(types.InlineKeyboardButton(
        TEXT[lang]["group"],
        url=f"https://t.me/{username}?startgroup=true"
    ))
    kb.add(types.InlineKeyboardButton(
        TEXT[lang]["language"],
        callback_data="change_language"
    ))
    return kb

def format_keyboard():
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("🎬 Video", callback_data="format_video"),
        types.InlineKeyboardButton("📁 MP4", callback_data="format_mp4")
    )
    return kb

def post_keyboard():
    kb = types.InlineKeyboardMarkup()
    username = bot.get_me().username
    kb.add(types.InlineKeyboardButton(
        "➕ Guruhga qo‘shish",
        url=f"https://t.me/{username}?startgroup=true"
    ))
    return kb

# ================= START =================

@bot.message_handler(commands=["start"])
def start(message):
    if message.chat.type != "private":
        save_chat(message.chat.id, message.chat.type)
        return

    save_user(message.chat.id)
    lang = get_language(message.chat.id)

    bot.send_message(
        message.chat.id,
        TEXT[lang]["welcome"],
        reply_markup=main_keyboard(lang)
    )

# ================= LANGUAGE =================

@bot.callback_query_handler(func=lambda c: c.data == "change_language")
def change_language(call):
    bot.answer_callback_query(call.id)
    bot.send_message(
        call.message.chat.id,
        "🌐 Tilni tanlang:",
        reply_markup=language_keyboard()
    )

@bot.callback_query_handler(func=lambda c: c.data.startswith("lang_"))
def select_language(call):
    lang = call.data.replace("lang_", "")

    if lang not in TEXT:
        return

    save_user(call.message.chat.id)
    set_language(call.message.chat.id, lang)

    bot.answer_callback_query(call.id, "✅")
    bot.send_message(
        call.message.chat.id,
        TEXT[lang]["welcome"],
        reply_markup=main_keyboard(lang)
    )

# ================= ADMIN STATS =================

@bot.message_handler(commands=["stats"])
def stats_command(message):
    if message.from_user.id != ADMIN_ID:
        return

    with connect_db() as con:
        users = con.execute(
            "SELECT COUNT(*) FROM users"
        ).fetchone()[0]

        chats = con.execute(
            "SELECT COUNT(*) FROM chats"
        ).fetchone()[0]

    bot.reply_to(
        message,
        f"📊 Bot statistikasi\n\n"
        f"👤 Foydalanuvchilar: {users}\n"
        f"👥 Guruhlar: {chats}"
    )

# ================= ADMIN SEND =================

@bot.message_handler(commands=["send"])
def send_broadcast(message):
    if message.from_user.id != ADMIN_ID:
        return

    text = message.text.replace("/send", "", 1).strip()

    if not text:
        bot.reply_to(message, "Matn kiriting: /send Salom!")
        return

    with connect_db() as con:
        users = con.execute(
            "SELECT chat_id FROM users"
        ).fetchall()

    success = 0
    failed = 0

    for user in users:
        try:
            bot.send_message(user[0], text)
            success += 1
            time.sleep(0.05)
        except Exception:
            failed += 1

    bot.reply_to(
        message,
        f"✅ Yuborildi: {success}\n❌ Xato: {failed}"
    )

# ================= URL =================

def extract_url(text):
    match = URL_RE.search(text or "")
    if not match:
        return None

    return match.group(0).rstrip(".,!?)]}")

# ================= DOWNLOAD =================

def download_video(url, workdir):
    options = {
        "outtmpl": os.path.join(workdir, "%(title).80s.%(ext)s"),
        "format": "best[ext=mp4]/best",
        "merge_output_format": "mp4",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": 30,
        "retries": 3,
        "fragment_retries": 3,
        "max_filesize": MAX_FILE_SIZE,
    }

    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=True)
        path = ydl.prepare_filename(info)

        if not os.path.exists(path):
            base = os.path.splitext(path)[0]
            mp4_path = base + ".mp4"
            if os.path.exists(mp4_path):
                path = mp4_path

        if not os.path.exists(path):
            files = [
                os.path.join(workdir, f)
                for f in os.listdir(workdir)
                if os.path.isfile(os.path.join(workdir, f))
            ]
            if not files:
                raise Exception("Fayl topilmadi")
            path = max(files, key=os.path.getsize)

    return path

# ================= FORMAT CALLBACK =================

@bot.callback_query_handler(
    func=lambda c: c.data in ["format_video", "format_mp4"]
)
def choose_format(call):
    bot.answer_callback_query(call.id)

    user_id = call.from_user.id

    with lock:
        data = pending_downloads.pop(user_id, None)

    if not data:
        bot.send_message(
            call.message.chat.id,
            "❌ Havola muddati tugagan. Qaytadan yuboring."
        )
        return

    url = data["url"]
    process_download(
        call.message.chat.id,
        url,
        call.data == "format_video"
    )

# ================= PROCESS =================

def process_download(chat_id, url, as_video=True):
    lang = get_language(chat_id)

    status = bot.send_message(
        chat_id,
        TEXT[lang]["working"]
    )

    workdir = tempfile.mkdtemp(prefix="video_")

    try:
        path = download_video(url, workdir)

        size = os.path.getsize(path)

        if size > MAX_FILE_SIZE:
            bot.edit_message_text(
                TEXT[lang]["big"],
                chat_id,
                status.message_id
            )
            return

        bot.edit_message_text(
            TEXT[lang]["uploading"],
            chat_id,
            status.message_id
        )

        with open(path, "rb") as file:
            if as_video:
                bot.send_video(
                    chat_id,
                    file,
                    supports_streaming=True,
                    reply_markup=post_keyboard(),
                    timeout=300
                )
            else:
                bot.send_document(
                    chat_id,
                    file,
                    reply_markup=post_keyboard(),
                    timeout=300
                )

        bot.send_message(
            chat_id,
            TEXT[lang]["done"] +
            "\n\n" + TEXT[lang]["promo"]
        )

        try:
            bot.delete_message(chat_id, status.message_id)
        except Exception:
            pass

    except Exception as e:
        logging.exception("Download error: %s", e)

        try:
            bot.edit_message_text(
                TEXT[lang]["failed"],
                chat_id,
                status.message_id
            )
        except Exception:
            bot.send_message(chat_id, TEXT[lang]["failed"])

    finally:
        shutil.rmtree(workdir, ignore_errors=True)

# ================= LINK HANDLER =================

@bot.message_handler(
    content_types=["text"],
    func=lambda m: m.chat.type == "private"
)
def handle_link(message):
    url = extract_url(message.text)

    if not url:
        return

    save_user(message.chat.id)

    with lock:
        pending_downloads[message.from_user.id] = {
            "url": url,
            "created": time.time()
        }

    bot.send_message(
        message.chat.id,
        TEXT[get_language(message.chat.id)]["choose"],
        reply_markup=format_keyboard()
    )

# ================= GROUP JOIN/LEAVE =================

@bot.message_handler(
    content_types=["new_chat_members", "left_chat_member"]
)
def group_events(message):
    try:
        if message.new_chat_members or message.left_chat_member:
            bot.delete_message(
                message.chat.id,
                message.message_id
            )
    except Exception:
        pass

    save_chat(message.chat.id, message.chat.type)

# ================= FLASK =================

@app.route("/")
def home():
    return "Bot is running!"

@app.route("/health")
def health():
    return "OK", 200

def run_flask():
    app.run(
        host="0.0.0.0",
        port=PORT,
        use_reloader=False
    )

# ================= RUN =================

if __name__ == "__main__":
    threading.Thread(
        target=run_flask,
        daemon=True
    ).start()

    logging.info("Bot ishga tushdi!")

    bot.infinity_polling(
        skip_pending=True,
        timeout=30,
        long_polling_timeout=30
    )
