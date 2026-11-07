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
    )
    return kb


# =============== START ===============

def send_welcome(chat_id, lang):
    bot.send_message(
        chat_id,
        TEXT[lang]["welcome"],
        reply_markup=main_keyboard(lang)
    )


@bot.message_handler(commands=["start"])
def start(message):
    if message.chat.type != "private":
        save_chat(message.chat.id, message.chat.type)
        return

    save_user(message.chat.id)
    lang = get_language(message.chat.id)

    if lang not in TEXT:
        bot.send_message(
            message.chat.id,
            TEXT["uz"]["choose"],
            reply_markup=language_keyboard()
        )
    else:
        send_welcome(message.chat.id, lang)


@bot.callback_query_handler(
    func=lambda call: call.data == "change_language"
)
def change_language(call):
    bot.answer_callback_query(call.id)
    bot.send_message(
        call.message.chat.id,
        "🌐 Tilni tanlang:",
        reply_markup=language_keyboard()
    )


@bot.callback_query_handler(
    func=lambda call: call.data.startswith("lang_")
)
def select_language(call):
    lang = call.data.replace("lang_", "")

    if lang not in TEXT:
        bot.answer_callback_query(call.id)
        return

    save_user(call.message.chat.id)
    set_language(call.message.chat.id, lang)

    bot.answer_callback_query(call.id, "✅")
    send_welcome(call.message.chat.id, lang)


@bot.message_handler(commands=["language"])
def language_command(message):
    if message.chat.type == "private":
        bot.send_message(
            message.chat.id,
            TEXT["uz"]["choose"],
            reply_markup=language_keyboard()
        )


# =============== ADMIN ===============

def is_admin(message):
    return (
        message.from_user is not None
        and message.from_user.id == ADMIN_ID
        and message.chat.type == "private"
    )


@bot.message_handler(commands=["stats"])
def statistics(message):
    if not is_admin(message):
        return

    with connect_db() as con:
        users = con.execute(
            "SELECT COUNT(*) FROM users"
        ).fetchone()[0]

        groups = con.execute(
            "SELECT COUNT(*) FROM chats "
            "WHERE chat_type IN ('group','supergroup')"
        ).fetchone()[0]

        channels = con.execute(
            "SELECT COUNT(*) FROM chats "
            "WHERE chat_type='channel'"
        ).fetchone()[0]

    bot.send_message(
        message.chat.id,
        f"📊 BOT STATISTIKASI\n\n"
        f"👤 Foydalanuvchilar: {users}\n"
        f"👥 Guruhlar: {groups}\n"
        f"📢 Kanallar: {channels}\n\n"
        f"🟢 Bot ishlamoqda!"
    )


@bot.message_handler(commands=["send"])
def send_command(message):
    if not is_admin(message):
        return

    prompt = bot.send_message(
        message.chat.id,
        "📨 Tarqatiladigan matn yoki rasmni yuboring.\n\n"
        "Bekor qilish: /cancel"
    )

    bot.register_next_step_handler(prompt, broadcast)


@bot.message_handler(commands=["cancel"])
def cancel(message):
    if is_admin(message):
        bot.send_message(
            message.chat.id,
            "❌ Bekor qilindi."
        )


def broadcast(message):
    if not is_admin(message):
        return

    if message.text and message.text.startswith("/cancel"):
        bot.send_message(message.chat.id, "❌ Bekor qilindi.")
        return

    with connect_db() as con:
        destinations = con.execute(
            "SELECT chat_id FROM users UNION SELECT chat_id FROM chats"
        ).fetchall()

    success = 0
    failed = 0

    bot.send_message(
        message.chat.id,
        "⏳ Xabar tarqatish boshlandi..."
    )

    for (chat_id,) in destinations:
        try:
            bot.copy_message(
                chat_id,
                message.chat.id,
                message.message_id
            )

            success += 1
            time.sleep(0.05)

        except Exception as error:
            failed += 1
            logging.warning(
                "Broadcast failed: %s",
                error
            )

    bot.send_message(
        message.chat.id,
        f"📨 TARQATISH YAKUNLANDI\n\n"
        f"✅ Muvaffaqiyatli: {success}\n"
        f"❌ Xatolik: {failed}"
    )


# =============== VIDEO YUKLASH ===============

URL_RE = re.compile(
    r"https?://[^\s<>()]+",
    re.IGNORECASE
)


def extract_url(text):
    match = URL_RE.search(text or "")
    if not match:
        return None
    return match.group(0).rstrip(".,!?)]}")


def download_youtube_via_api(url, workdir):
    """YouTube uchun maxsus Cobalt API orqali video yuklash (Render IP bloklanishini chetlab o'tadi)"""
    api_url = "https://co.wuk.sh/api/json"
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json"
    }
    data = {
        "url": url,
        "vQuality": "720"
    }
    
    response = requests.post(api_url, json=data, headers=headers, timeout=30)
    res_json = response.json()
    
    if res_json.get("status") == "redirect" or res_json.get("status") == "stream":
        download_link = res_json.get("url")
    elif res_json.get("status") == "picker":
        download_link = res_json.get("picker")[0].get("url")
    else:
        raise Exception("API YouTube havolasini o'qiy olmadi")
        
    # Videoni vaqtinchalik papkaga yuklab olish
    file_path = os.path.join(workdir, "youtube_video.mp4")
    with requests.get(download_link, stream=True, timeout=60) as r:
        r.raise_for_status()
        with open(file_path, 'wb') as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)
                
    info = {"title": "YouTube Video"}
    return file_path, info


def download_media(url, workdir):
    # Agar havola YouTube bo'lsa, maxsus API orqali tortamiz
    if "youtube.com" in url or "youtu.be" in url:
        return download_youtube_via_api(url, workdir)

    # Qolgan tarmoqlar uchun yt-dlp ishlatamiz
    output_template = os.path.join(
        workdir,
        "%(title).80s-%(id)s.%(ext)s"
    )

    options = {
        "outtmpl": output_template,
        "format": "best[ext=mp4][filesize<49M]/best[filesize<49M]/best",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "restrictfilenames": True,
        "max_filesize": MAX_FILE_SIZE,
        "socket_timeout": 25,
        "retries": 3,
        "fragment_retries": 3,
        "http_headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        }
    }

    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(
            url,
            download=True
        )

        path = ydl.prepare_filename(info)

        base, _ = os.path.splitext(path)
        mp4_path = base + ".mp4"

        if os.path.exists(mp4_path):
            path = mp4_path

        if not os.path.exists(path):
            candidates = [
                os.path.join(workdir, name)
                for name in os.listdir(workdir)
                if os.path.isfile(
                    os.path.join(workdir, name)
                )
            ]

            if not candidates:
                raise FileNotFoundError(
                    "Downloaded file not found"
                )

            path = max(
                candidates,
                key=os.path.getsize
            )

    if os.path.getsize(path) > MAX_FILE_SIZE:
        raise ValueError("FILE_TOO_LARGE")

    return path, info


def handle_video_link(message):
    chat_id = message.chat.id
    lang = get_language(chat_id)

    if lang not in TEXT:
        lang = "uz"

    url = extract_url(
        message.text or message.caption or ""
    )

    if not url:
        return

    with active_lock:
        if chat_id in active_downloads:
            bot.reply_to(
                message,
                "⏳ Bu chatda boshqa yuklash davom etmoqda. "
                "Tugashini kuting."
            )
            return

        active_downloads.add(chat_id)

    status_message = None
    workdir = tempfile.mkdtemp(
        prefix="downloader_"
    )

    try:
        status_message = bot.reply_to(
            message,
            TEXT[lang]["working"]
        )

        path, info = download_media(
            url,
            workdir
        )

        bot.edit_message_text(
            TEXT[lang]["choose_format"],
            chat_id,
            status_message.message_id,
            reply_markup=format_keyboard()
        )

        pending_downloads[
            (chat_id, status_message.message_id)
        ] = {
            "path": path,
            "lang": lang,
            "reply_to_message_id": message.message_id,
            "workdir": workdir,
            "title": info.get("title", "video")
        }

        workdir = None

    except ValueError as error:
        if status_message:
            bot.edit_message_text(
                TEXT[lang]["too_big"],
                chat_id,
                status_message.message_id
            )
        else:
            bot.reply_to(
                message,
                TEXT[lang]["too_big"]
            )

        logging.info(
            "File rejected: %s",
            error
        )

    except Exception:
        logging.exception(
            "Download failed for URL: %s",
            url
        )

        if status_message:
            bot.edit_message_text(
                TEXT[lang]["failed"],
                chat_id,
                status_message.message_id
            )
        else:
            bot.reply_to(
                message,
                TEXT[lang]["failed"]
            )

    finally:
        if workdir and os.path.isdir(workdir):
            shutil.rmtree(
                workdir,
                ignore_errors=True
            )

        with active_lock:
            active_downloads.discard(chat_id)


# =============== VIDEO / MP4 YUBORISH ===============

@bot.callback_query_handler(
    func=lambda call: call.data in (
        "format_video",
        "format_mp4"
    )
)
def send_downloaded_file(call):
    chat_id = call.message.chat.id
    key = (
        chat_id,
        call.message.message_id
    )

    with pending_lock:
        item = pending_downloads.get(key)

    if not item:
        bot.answer_callback_query(
            call.id,
            "Fayl topilmadi yoki muddati tugagan.",
            show_alert=True
        )
        return

    bot.answer_callback_query(
        call.id,
        "Yuborilmoqda..."
    )

    path = item["path"]
    lang = item["lang"]
    reply_id = item["reply_to_message_id"]

    try:
        bot.edit_message_text(
            TEXT[lang]["uploading"],
            chat_id,
            call.message.message_id
        )

        if call.data == "format_video":
            with open(path, "rb") as media:
                bot.send_video(
                    chat_id,
                    media,
                    reply_to_message_id=reply_id,
                    caption=TEXT[lang]["done"],
                    supports_streaming=True,
                    timeout=120
                )

        else:
            with open(path, "rb") as media:
                bot.send_document(
                    chat_id,
                    media,
                    reply_to_message_id=reply_id,
                    caption=TEXT[lang]["done"],
                    timeout=120
                )

        bot.send_message(
            chat_id,
            TEXT[lang]["promo"],
            reply_markup=post_download_keyboard()
        )

        bot.edit_message_text(
            "✅ Yuklab olindi!",
            chat_id,
            call.message.message_id
        )

    except Exception:
        logging.exception(
            "Telegram upload failed"
        )
        bot.send_message(
            chat_id,
            "❌ Telegram'ga yuborishda xatolik yuz berdi."
        )

    finally:
        with pending_lock:
            pending_downloads.pop(
                key,
                None
            )

        shutil.rmtree(
            item["workdir"],
            ignore_errors=True
        )


# =============== GURUH HIMOYASI ===============

@bot.callback_query_handler(
    func=lambda call: call.data == "group_protect"
)
def group_protect(call):
    bot.answer_callback_query(call.id)
    lang = get_language(call.message.chat.id)

    if lang not in TEXT:
        lang = "uz"

    bot.send_message(
        call.message.chat.id,
        TEXT[lang]["protect"]
    )


@bot.message_handler(
    func=lambda m: bool(
        extract_url(m.text or m.caption or "")
    ),
    content_types=[
        "text",
        "photo",
        "video",
        "document"
    ]
)
def video_link_router(message):
    if message.chat.type == "private":
        handle_video_link(message)


@bot.my_chat_member_handler()
def bot_membership(update):
    chat = update.chat
    status = update.new_chat_member.status

    if status in ("member", "administrator"):
        save_chat(
            chat.id,
            chat.type
        )
    elif status in ("left", "kicked"):
        with connect_db() as con:
            con.execute(
                "DELETE FROM chats WHERE chat_id=?",
                (chat.id,)
            )


@bot.message_handler(
    content_types=[
        "new_chat_members",
        "left_chat_member"
    ]
)
def delete_service_messages(message):
    try:
        bot.delete_message(
            message.chat.id,
            message.message_id
        )
    except Exception as error:
        logging.warning(
            "Could not delete service message: %s",
            error
        )


INVITE_RE = re.compile(
    r"(?:https?://)?t\.me/(?:\+|joinchat/)[A-Za-z0-9_-]+",
    re.IGNORECASE
)


@bot.message_handler(
    func=lambda m: bool(
        m.text or m.caption
    ) and bool(
        INVITE_RE.search(
            
