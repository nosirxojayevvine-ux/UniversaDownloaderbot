
import os
import re
import time
import uuid
import sqlite3
import logging
import tempfile
import threading
import shutil

import telebot
from telebot import types
from flask import Flask
import yt_dlp

# =============== SOZLAMALAR ===============

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = 8019481444
ADMIN_USERNAME = "@nosirxojayev"

DB_PATH = os.getenv("DB_PATH", "bot.db")
PORT = int(os.getenv("PORT", "10000"))

# Hajmni Render Environment Variables orqali ham o'zgartirish mumkin
MAX_FILE_SIZE_MB = int(os.getenv("MAX_FILE_SIZE_MB", "2000"))
MAX_FILE_SIZE = MAX_FILE_SIZE_MB * 1024 * 1024

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN sozlanmagan!")

bot = telebot.TeleBot(BOT_TOKEN, threaded=True)
app = Flask(__name__)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)

URL_RE = re.compile(r"https?://[^\s<>()]+", re.I)

pending_downloads = {}
pending_lock = threading.Lock()

# =============== MA'LUMOTLAR BAZASI ===============

def connect_db():
    return sqlite3.connect(DB_PATH, timeout=30)

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

# =============== TILLAR ===============

TEXT = {
    "uz": {
        "welcome": (
            "🔥 @DownlanderToVideoBot\n\n"
            "Barcha qo‘llab-quvvatlanadigan ijtimoiy "
            "tarmoqlardan video yuklab oling!\n\n"
            "🛡 QO‘SHIMCHA IMKONIYATLAR:\n\n"
            "👤 Guruhga kirish-chiqish xabarlarini o‘chiradi.\n"
            "📢 Guruhdagi havolali reklamalarni o‘chiradi.\n"
            "📥 Videolarni yuklab beradi.\n\n"
            "👇 Botni guruhingizga qo‘shing!"
        ),
        "group": "➕ Guruhga qo‘shish",
        "language": "🌐 Tilni o‘zgartirish",
        "choose": "🌐 Tilni tanlang:",
        "format": "🎬 Qaysi ko‘rinishda yuboray?",
        "working": "⏳ Video yuklab olinmoqda...",
        "uploading": "⏳ Video yuborilmoqda...",
        "done": (
            "✅ Yuklab olindi!\n\n"
            "Yuborgan linkingiz uchun "
            "@DownlanderToVideoBot nomidan sizga "
            "katta rahmat! ❤️\n\n"
            "🎉 Videolaringiz doimo sifatli bo‘lsin!\n\n"
            "🤖 Guruhingizni tartibli saqlang!"
        ),
        "failed": "❌ Videoni yuklab bo‘lmadi. Havolani tekshiring.",
        "big": "⚠️ Video belgilangan hajm chegarasidan katta.",
        "expired": "❌ Havola eskirgan. Qaytadan yuboring.",
        "promo": "🤖 Guruhingizni tartibli saqlang!"
    },

    "ru": {
        "welcome": (
            "🔥 @DownlanderToVideoBot\n\n"
            "Загружайте видео с поддерживаемых платформ!\n\n"
            "🛡 ДОПОЛНИТЕЛЬНЫЕ ФУНКЦИИ:\n\n"
            "👤 Удаляет уведомления о входе и выходе.\n"
            "📢 Удаляет сообщения со ссылками.\n"
            "📥 Загружает видео.\n\n"
            "👇 Добавьте бота в группу!"
        ),
        "group": "➕ Добавить в группу",
        "language": "🌐 Изменить язык",
        "choose": "🌐 Выберите язык:",
        "format": "🎬 Выберите формат:",
        "working": "⏳ Загрузка видео...",
        "uploading": "⏳ Отправка видео...",
        "done": (
            "✅ Загружено!\n\n"
            "Спасибо за вашу ссылку от "
            "@DownlanderToVideoBot! ❤️\n\n"
            "🤖 Пусть в вашей группе будет порядок!"
        ),
        "failed": "❌ Не удалось скачать видео.",
        "big": "⚠️ Файл слишком большой.",
        "expired": "❌ Ссылка устарела. Отправьте её снова.",
        "promo": "🤖 Порядок в вашей группе!"
    },

    "en": {
        "welcome": (
            "🔥 @DownlanderToVideoBot\n\n"
            "Download videos from supported platforms!\n\n"
            "🛡 EXTRA FEATURES:\n\n"
            "👤 Deletes join and leave notifications.\n"
            "📢 Deletes messages containing links.\n"
            "📥 Downloads videos.\n\n"
            "👇 Add the bot to your group!"
        ),
        "group": "➕ Add to group",
        "language": "🌐 Change language",
        "choose": "🌐 Choose language:",
        "format": "🎬 Choose format:",
        "working": "⏳ Downloading video...",
        "uploading": "⏳ Sending video...",
        "done": (
            "✅ Downloaded!\n\n"
            "Thank you for your link from "
            "@DownlanderToVideoBot! ❤️\n\n"
            "🤖 Keep your group organized!"
        ),
        "failed": "❌ Download failed.",
        "big": "⚠️ File is too large.",
        "expired": "❌ Link expired. Send it again.",
        "promo": "🤖 Keep your group organized!"
    }
}

# =============== TUGMALAR ===============

def bot_username():
    return bot.get_me().username

def main_keyboard(lang):
    kb = types.InlineKeyboardMarkup(row_width=1)

    kb.add(types.InlineKeyboardButton(
        TEXT[lang]["group"],
        url=f"https://t.me/{bot_username()}?startgroup=true"
    ))

    kb.add(types.InlineKeyboardButton(
        TEXT[lang]["language"],
        callback_data="change_language"
    ))

    return kb

def post_keyboard():
    kb = types.InlineKeyboardMarkup(row_width=1)

    kb.add(types.InlineKeyboardButton(
        "➕ Guruhga qo‘shish",
        url=f"https://t.me/{bot_username()}?startgroup=true"
    ))

    return kb

def language_keyboard():
    kb = types.InlineKeyboardMarkup(row_width=2)

    kb.add(
        types.InlineKeyboardButton(
            "🇺🇿 O‘zbekcha", callback_data="lang_uz"
        ),
        types.InlineKeyboardButton(
            "🇷🇺 Русский", callback_data="lang_ru"
        ),
        types.InlineKeyboardButton(
            "🇬🇧 English", callback_data="lang_en"
        )
    )

    return kb

def format_keyboard():
    kb = types.InlineKeyboardMarkup(row_width=2)

    kb.add(
        types.InlineKeyboardButton(
            "🎬 Video", callback_data="format_video"
        ),
        types.InlineKeyboardButton(
            "📁 MP4", callback_data="format_mp4"
        )
    )

    return kb

# =============== START ===============

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

# =============== TIL O'ZGARTIRISH ===============

@bot.callback_query_handler(
    func=lambda c: c.data == "change_language"
)
def change_language(call):
    bot.answer_callback_query(call.id)

    bot.send_message(
        call.message.chat.id,
        "🌐 Tilni tanlang:",
        reply_markup=language_keyboard()
    )

@bot.callback_query_handler(
    func=lambda c: c.data.startswith("lang_")
)
def select_language(call):
    lang = call.data.replace("lang_", "")

    if lang not in TEXT:
        bot.answer_callback_query(call.id)
        return

    save_user(call.from_user.id)
    set_language(call.from_user.id, lang)

    bot.answer_callback_query(call.id, "✅")

    bot.send_message(
        call.message.chat.id,
        TEXT[lang]["welcome"],
        reply_markup=main_keyboard(lang)
    )

# =============== ADMIN STATISTIKA ===============

@bot.message_handler(commands=["stats"])
def stats_command(message):
    if not message.from_user or message.from_user.id != ADMIN_ID:
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
        f"📊 BOT STATISTIKASI\n\n"
        f"👤 Foydalanuvchilar: {users}\n"
        f"👥 Guruhlar: {chats}"
    )

# =============== ADMIN XABAR YUBORISH ===============

@bot.message_handler(commands=["send"])
def send_broadcast(message):
    if not message.from_user or message.from_user.id != ADMIN_ID:
        return

    text_to_send = message.text.partition(" ")[2].strip()

    if not text_to_send:
        bot.reply_to(
            message,
            "⚠️ Xabar matnini kiriting.\n\n"
            "Misol: /send Assalomu alaykum!"
        )
        return

    with connect_db() as con:
        users = con.execute(
            "SELECT chat_id FROM users"
        ).fetchall()

    success = 0
    failed = 0

    for user in users:
        try:
            bot.send_message(user[0], text_to_send)
            success += 1
            time.sleep(0.05)
        except Exception:
            failed += 1

    bot.reply_to(
        message,
        f"✅ Yuborildi: {success}\n"
        f"❌ Xato: {failed}"
    )

# =============== HAVOLANI ANIQLASH ===============

def extract_url(text):
    match = URL_RE.search(text or "")

    if not match:
        return None

    return match.group(0).rstrip(".,!?)]}")

# =============== VIDEO YUKLASH ===============

def download_video(url, workdir):
    options = {
        "outtmpl": os.path.join(
            workdir, "%(title).80s.%(ext)s"
        ),

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
            candidates = []

            for name in os.listdir(workdir):
                full_path = os.path.join(workdir, name)

                if os.path.isfile(full_path):
                    if name.lower().endswith(
                        (".mp4", ".mkv", ".webm", ".mov")
                    ):
                        candidates.append(full_path)

            if not candidates:
                raise Exception("Video fayl topilmadi")

            path = max(candidates, key=os.path.getsize)

    return path

# =============== FORMAT TANLASH ===============

@bot.callback_query_handler(
    func=lambda c: c.data in ["format_video", "format_mp4"]
)
def choose_format(call):
    user_id = call.from_user.id

    with pending_lock:
        data = pending_downloads.pop(user_id, None)

    bot.answer_callback_query(call.id)

    if not data:
        bot.send_message(
            call.message.chat.id,
            TEXT.get(
                get_language(user_id), TEXT["uz"]
            )["expired"]
        )
        return

    if time.time() - data["created"] > 600:
        bot.send_message(
            call.message.chat.id,
            TEXT[get_language(user_id)]["expired"]
        )
        return

    as_video = call.data == "format_video"

    threading.Thread(
        target=process_download,
        args=(call.message.chat.id, data["url"], as_video),
        daemon=True
    ).start()

# =============== YUKLAB OLISH JARAYONI ===============

def process_download(chat_id, url, as_video=True):
    lang = get_language(chat_id)

    status = bot.send_message(
        chat_id,
        TEXT[lang]["working"]
    )

    workdir = tempfile.mkdtemp(prefix="downloader_")

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
                    timeout=300
                )
            else:
                bot.send_document(
                    chat_id,
                    file,
                    timeout=300
                )

        bot.send_message(
            chat_id,
            TEXT[lang]["done"],
            reply_markup=post_keyboard()
        )

        try:
            bot.delete_message(
                chat_id,
                status.message_id
            )
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
            pass

    finally:
        shutil.rmtree(workdir, ignore_errors=True)

# =============== FOYDALANUVCHI HAVOLASI ===============

@bot.message_handler(
    content_types=["text"],
    func=lambda m: m.chat.type == "private"
)
def handle_link(message):
    url = extract_url(message.text)

    if not url:
        return

    save_user(message.chat.id)

    with pending_lock:
        pending_downloads[message.from_user.id] = {
            "url": url,
            "created": time.time()
        }

    bot.send_message(
        message.chat.id,
        TEXT[get_language(message.chat.id)]["format"],
        reply_markup=format_keyboard()
    )

# =============== GURUHGA KIRISH-CHIQISH ===============

@bot.message_handler(
    content_types=["new_chat_members", "left_chat_member"]
)
def group_events(message):
    try:
        bot.delete_message(
            message.chat.id,
            message.message_id
        )
    except Exception as e:
        logging.warning("Service message delete error: %s", e)

    save_chat(message.chat.id, message.chat.type)

# =============== GURUH REKLAMALARINI O'CHIRISH ===============

@bot.message_handler(
    content_types=[
        "text",
        "photo",
        "video",
        "document",
        "animation",
        "audio",
        "voice"
    ],
    func=lambda m: m.chat.type in ["group", "supergroup"]
)
def delete_ads(message):
    save_chat(message.chat.id, message.chat.type)

    # Adminlarning xabarlariga tegmaymiz
    if message.from_user:
        if message.from_user.id == ADMIN_ID:
            return

        try:
            member = bot.get_chat_member(
                message.chat.id,
                message.from_user.id
            )

            if member.status in ["administrator", "creator"]:
                return
        except Exception:
            pass

    text = (message.text or "") + " " + (message.caption or "")

    # Havolali xabarlarni reklama sifatida o'chirish
    if extract_url(text):
        try:
            bot.delete_message(
                message.chat.id,
                message.message_id
            )
        except Exception as e:
            logging.warning("Ad delete error: %s", e)

# =============== FLASK SERVER ===============

@app.route("/")
def home():
    return "DownlanderToVideoBot is running!"

@app.route("/health")
def health():
    return "OK", 200

def run_flask():
    app.run(
        host="0.0.0.0",
        port=PORT,
        use_reloader=False
    )

# =============== BOTNI ISHGA TUSHIRISH ===============

if __name__ == "__main__":

    threading.Thread(
        target=run_flask,
        daemon=True
    ).start()

    logging.info("DownlanderToVideoBot ishga tushdi!")

    bot.infinity_polling(
        skip_pending=True,
        timeout=30,
        long_polling_timeout=30
    )
