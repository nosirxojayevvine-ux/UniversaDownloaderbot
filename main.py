
import os
import time
import sqlite3
import threading
import logging

import telebot
from telebot import types
from flask import Flask

# CONFIGURATION
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = 8019481444
DB_PATH = os.getenv("DB_PATH", "bot.db")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN sozlanmagan!")

bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

logging.basicConfig(level=logging.INFO)

# DATABASE
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

# TRANSLATIONS
TEXT = {
    "uz": {
        "choose": "🌐 Tilni tanlang:",
        "welcome": """🔥 Assalomu alaykum!

Botimizga xush kelibsiz!

Bot orqali quyidagilarni yuklab olishingiz mumkin:

• Instagram — post, Reels va audio;
• TikTok — videolar;
• YouTube — videolar va Shorts;
• Snapchat — videolar;
• Likee — videolar;
• Pinterest — video va rasmlar;
• Threads — video va rasmlar;
• Facebook — video.

🚀 Yuklab olmoqchi bo'lgan videoga havolani yuboring!

😎 Bot guruhlarda ham ishlaydi!""",
        "group": "➕ Guruhga qo'shish ↗️",
        "language": "🌐 Tilni o'zgartirish"
    },
    "ru": {
        "choose": "🌐 Выберите язык:",
        "welcome": """🔥 Здравствуйте!

Добро пожаловать в нашего бота!

С помощью бота можно загружать:

• Instagram — посты, Reels и аудио;
• TikTok — видео;
• YouTube — видео и Shorts;
• Snapchat — видео;
• Likee — видео;
• Pinterest — видео и изображения;
• Threads — видео и изображения;
• Facebook — видео.

🚀 Отправьте ссылку на видео!

😎 Бот работает и в группах!""",
        "group": "➕ Добавить в группу ↗️",
        "language": "🌐 Изменить язык"
    },
    "en": {
        "choose": "🌐 Choose your language:",
        "welcome": """🔥 Hello!

Welcome to our bot!

You can download media from:

• Instagram — posts, Reels and audio;
• TikTok — videos;
• YouTube — videos and Shorts;
• Snapchat — videos;
• Likee — videos;
• Pinterest — videos and images;
• Threads — videos and images;
• Facebook — videos.

🚀 Send a video link to get started!

😎 The bot also works in groups!""",
        "group": "➕ Add to group ↗️",
        "language": "🌐 Change language"
    },
    "ar": {
        "choose": "🌐 اختر لغتك:",
        "welcome": """🔥 مرحباً!

أهلاً بك في البوت!

يمكنك تحميل الوسائط من:

• Instagram
• TikTok
• YouTube
• Snapchat
• Likee
• Pinterest
• Threads
• Facebook

🚀 أرسل رابط الفيديو للبدء!

😎 يعمل البوت أيضاً في المجموعات!""",
        "group": "➕ أضف إلى المجموعة ↗️",
        "language": "🌐 تغيير اللغة"
    }
}

# KEYBOARDS
def language_keyboard():
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton(
            "🇺🇿 O'zbekcha", callback_data="lang_uz"),
        types.InlineKeyboardButton(
            "🇷🇺 Русский", callback_data="lang_ru"),
        types.InlineKeyboardButton(
            "🇬🇧 English", callback_data="lang_en"),
        types.InlineKeyboardButton(
            "🇸🇦 العربية", callback_data="lang_ar")
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

# WELCOME
def send_welcome(chat_id, lang):
    bot.send_message(
        chat_id,
        TEXT[lang]["welcome"],
        reply_markup=main_keyboard(lang)
    )

@bot.message_handler(commands=["start"])
def start(message):
    if message.chat.type != "private":
        return

    save_user(message.chat.id)
    lang = get_language(message.chat.id)

    if lang in TEXT:
        send_welcome(message.chat.id, lang)
    else:
        bot.send_message(
            message.chat.id,
            TEXT["uz"]["choose"],
            reply_markup=language_keyboard()
        )

@bot.callback_query_handler(
    func=lambda call: call.data == "change_language"
)
def change_language(call):
    bot.answer_callback_query(call.id)
    bot.send_message(
        call.message.chat.id,
        "🌐 Choose / Выберите / Tanlang:",
        reply_markup=language_keyboard()
    )

@bot.callback_query_handler(
    func=lambda call: call.data.startswith("lang_")
)
def select_language(call):
    lang = call.data.replace("lang_", "")

    if lang not in TEXT:
        return

    save_user(call.message.chat.id)
    set_language(call.message.chat.id, lang)

    bot.answer_callback_query(call.id)
    send_welcome(call.message.chat.id, lang)

# LANGUAGE COMMAND
@bot.message_handler(commands=["language"])
def language_command(message):
    if message.chat.type == "private":
        bot.send_message(
            message.chat.id,
            "🌐 Choose your language:",
            reply_markup=language_keyboard()
        )

# ADMIN CHECK
def is_admin(message):
    return (
        message.from_user is not None
        and message.from_user.id == ADMIN_ID
        and message.chat.type == "private"
    )

# STATISTICS
@bot.message_handler(commands=["stats"])
def statistics(message):
    if not is_admin(message):
        return

    with connect_db() as con:
        users = con.execute(
            "SELECT COUNT(*) FROM users"
        ).fetchone()[0]

        groups = con.execute(
            "SELECT COUNT(*) FROM chats WHERE chat_type='group'"
        ).fetchone()[0]

        supergroups = con.execute(
            "SELECT COUNT(*) FROM chats WHERE chat_type='supergroup'"
        ).fetchone()[0]

        channels = con.execute(
            "SELECT COUNT(*) FROM chats WHERE chat_type='channel'"
        ).fetchone()[0]

    bot.send_message(
        message.chat.id,
        f"""📊 BOT STATISTIKASI

👤 Foydalanuvchilar: {users}
👥 Guruhlar: {groups + supergroups}
📢 Kanallar: {channels}

🟢 Bot ishlamoqda!"""
    )

# BROADCAST
@bot.message_handler(commands=["send"])
def send_command(message):
    if not is_admin(message):
        return

    sent = bot.send_message(
        message.chat.id,
        "📨 Tarqatiladigan matn yoki rasmni yuboring.\n\n"
        "Bekor qilish: /cancel"
    )

    bot.register_next_step_handler(sent, broadcast)

@bot.message_handler(commands=["cancel"])
def cancel(message):
    if is_admin(message):
        bot.send_message(message.chat.id, "❌ Bekor qilindi.")

def broadcast(message):
    if not is_admin(message):
        return

    if message.text and message.text.startswith("/cancel"):
        bot.send_message(message.chat.id, "❌ Bekor qilindi.")
        return

    with connect_db() as con:
        destinations = con.execute(
            "SELECT chat_id FROM users "
            "UNION SELECT chat_id FROM chats"
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
            time.sleep(0.08)

        except Exception as error:
            failed += 1
            logging.warning(
                "Xabar yuborilmadi: %s: %s",
                chat_id, error
            )

    bot.send_message(
        message.chat.id,
        f"""📨 TARQATISH YAKUNLANDI

✅ Muvaffaqiyatli: {success}
❌ Xatolik: {failed}"""
    )

# GROUP AND CHANNEL TRACKING
@bot.my_chat_member_handler()
def bot_membership(update):
    chat = update.chat
    status = update.new_chat_member.status

    if status in ("member", "administrator"):
        save_chat(chat.id, chat.type)

    elif status in ("left", "kicked"):
        with connect_db() as con:
            con.execute(
                "DELETE FROM chats WHERE chat_id=?",
                (chat.id,)
            )

# DELETE JOIN/LEAVE MESSAGES
@bot.message_handler(
    content_types=["new_chat_members", "left_chat_member"]
)
def delete_service_messages(message):
    try:
        bot.delete_message(
            message.chat.id,
            message.message_id
        )
    except Exception as error:
        logging.warning("Xabarni o'chirib bo'lmadi: %s", error)

# FLASK SERVER
@app.route("/")
def home():
    return "Universal Downloader Bot is running!"

@app.route("/health")
def health():
    return {"status": "ok"}

# START
if __name__ == "__main__":
    setup_db()

    threading.Thread(
        target=lambda: bot.infinity_polling(
            skip_pending=True,
            timeout=30,
            long_polling_timeout=30
        ),
        daemon=True
    ).start()

    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 10000))
    )
