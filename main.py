import os, re, sqlite3, asyncio, threading
from datetime import datetime, date
from typing import Tuple, Dict

from flask import Flask
from dotenv import load_dotenv
import yt_dlp

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    BotCommand,
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton,
    FSInputFile, CallbackQuery, Message, ErrorEvent
)
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
BOT_USERNAME = os.getenv("BOT_USERNAME", "YourBot")
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "NWSxALFA")
ADMIN_IDS = [int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]

PORT = int(os.getenv("PORT", "8081"))
MAX_PARALLEL_DOWNLOADS = int(os.getenv("MAX_PARALLEL_DOWNLOADS", "3"))
DAILY_LIMIT_FREE = int(os.getenv("DAILY_LIMIT_FREE", "30"))
MAX_TG_FILE_MB = int(os.getenv("MAX_TG_FILE_MB", "50"))

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN .env faylida topilmadi!")

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

DB = "bot.db"
TEMP_DIR = "temp"
DOWNLOAD_DIR = "downloads"
os.makedirs(TEMP_DIR, exist_ok=True)
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

app = Flask(__name__)

@app.route("/")
def home():
    return "ALFA Media Bot V5 ishlayapti ✅"

@app.route("/health")
def health():
    return {"status": "ok", "time": datetime.now().isoformat(), "bot": BOT_USERNAME}

def run_flask():
    try:
        app.run(host="0.0.0.0", port=PORT, threaded=True)
    except OSError as e:
        print(f"Flask port muammo: {e}")

class AdminState(StatesGroup):
    add_channel = State()
    broadcast = State()
    ban_user = State()
    unban_user = State()
    find_user = State()

BTN_LINK = "🔗 Link yuborish"
BTN_ADMIN = "👑 Admin"
BTN_BACK = "🏠 Bosh menyu"

TEXT_START = (
    "👋 Assalomu alaykum!\n\n"
    "🎬 YouTube, Instagram, TikTok, Facebook va boshqa linklardan video/audio yuklab beraman.\n\n"
    "🔗 Link yuboring yoki pastdagi <b>Link yuborish</b> tugmasini bosing.\n\n"
    "Formatlar:\n"
    "🎬 MP4 Video\n"
    "🎵 MP3 Ovoz"
)

TEXT_NOT_SUB = "❌ Botdan foydalanish uchun quyidagi kanallarga obuna bo‘ling:"
TEXT_SUB_OK = "✅ Obuna tasdiqlandi! Endi botdan foydalanishingiz mumkin."
TEXT_SEND_URL = "🔗 Video yoki musiqa linkini yuboring:"
TEXT_CHOOSE_FORMAT = "⬇️ Qaysi formatda yuklaymiz?"
TEXT_DOWNLOADING = "⏳ Yuklanmoqda, iltimos kuting..."
TEXT_BIG_FILE = "❌ Fayl juda katta. Telegram orqali yuborib bo‘lmadi."
TEXT_ERROR = "❌ Xatolik yuz berdi. Qaytadan urinib ko‘ring."
TEXT_BANNED = "❌ Siz botdan bloklangansiz."
TEXT_LIMIT_END = "❌ Kunlik limit tugadi. Ertaga qayta urinib ko‘ring."

HELP_TEXT = (
    "📌 <b>Foydalanuvchi buyruqlari</b>\n\n"
    "/start — botni ishga tushirish\n"
    "/help — yordam\n"
    "/link — link yuborish\n"
    "/cancel — bekor qilish\n\n"
    "Shunchaki YouTube, Instagram, TikTok yoki Facebook link yuborsangiz ham bo‘ladi."
)

ADMIN_HELP_TEXT = (
    "👑 <b>Admin buyruqlari</b>\n\n"
    "/admin — admin panel\n"
    "/stats — statistika\n"
    "/channels — majburiy kanallar ro‘yxati\n"
    "/add_channel — kanal qo‘shish\n"
    "/remove_channel — kanal o‘chirish\n"
    "/broadcast — hammaga xabar yuborish\n"
    "/find_user — user ma’lumotini topish\n"
    "/ban — userni bloklash\n"
    "/unban — blokdan chiqarish\n"
    "/cleanup — vaqtinchalik fayllarni tozalash\n\n"
    "📌 Foydalanuvchi buyruqlari:\n"
    "/start, /help, /link, /cancel"
)

def db():
    con = sqlite3.connect(DB, timeout=30)
    con.row_factory = sqlite3.Row
    return con

def col_exists(cur, table, col):
    cur.execute(f"PRAGMA table_info({table})")
    return col in [r[1] for r in cur.fetchall()]

def add_col(cur, table, col, typ):
    if not col_exists(cur, table, col):
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")

def init_db():
    con = db()
    cur = con.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA synchronous=NORMAL")
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users(
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        full_name TEXT,
        downloads INTEGER DEFAULT 0,
        joined_at TEXT
    )
    """)
    add_col(cur, "users", "last_active", "TEXT")
    add_col(cur, "users", "is_banned", "INTEGER DEFAULT 0")
    add_col(cur, "users", "today_count", "INTEGER DEFAULT 0")
    add_col(cur, "users", "today_date", "TEXT")
    add_col(cur, "users", "is_premium", "INTEGER DEFAULT 0")
    cur.execute("""
    CREATE TABLE IF NOT EXISTS channels(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        title TEXT
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS downloads_log(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        mode TEXT,
        source TEXT,
        title TEXT,
        created_at TEXT
    )
    """)
    con.commit()
    con.close()

def add_user(user):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    con = db()
    cur = con.cursor()
    cur.execute("""
    INSERT OR IGNORE INTO users(user_id, username, full_name, joined_at, last_active, today_date)
    VALUES (?, ?, ?, ?, ?, ?)
    """, (user.id, user.username or "", user.full_name or "", now, now, date.today().isoformat()))
    cur.execute("UPDATE users SET username=?, full_name=?, last_active=? WHERE user_id=?",
                (user.username or "", user.full_name or "", now, user.id))
    con.commit()
    con.close()

def get_user(user_id: int):
    con = db()
    row = con.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
    con.close()
    return row

def is_banned(user_id: int) -> bool:
    row = get_user(user_id)
    return bool(row and row["is_banned"])

def set_ban(user_id: int, banned: bool):
    con = db()
    con.execute("UPDATE users SET is_banned=? WHERE user_id=?", (1 if banned else 0, user_id))
    con.commit()
    con.close()

def normalize_channel(username: str) -> str:
    username = re.sub(r"https?://t\.me/", "", username)
    username = username.replace("@", "").strip().split("/")[0]
    return username

def add_channel(username: str, title: str = None):
    username = normalize_channel(username)
    if username:
        con = db()
        con.execute("INSERT OR IGNORE INTO channels(username, title) VALUES (?, ?)", (username, title or username))
        con.commit()
        con.close()

def remove_channel(username: str):
    con = db()
    con.execute("DELETE FROM channels WHERE username=?", (normalize_channel(username),))
    con.commit()
    con.close()

def get_channels():
    con = db()
    rows = con.execute("SELECT username, title FROM channels ORDER BY id").fetchall()
    con.close()
    return [(r["username"], r["title"]) for r in rows]

def get_all_users():
    con = db()
    rows = con.execute("SELECT user_id FROM users WHERE is_banned=0").fetchall()
    con.close()
    return [r["user_id"] for r in rows]

def inc_download(user_id: int, mode: str, source: str, title: str):
    con = db()
    cur = con.cursor()
    cur.execute("UPDATE users SET downloads=downloads+1 WHERE user_id=?", (user_id,))
    cur.execute("""
    INSERT INTO downloads_log(user_id, mode, source, title, created_at)
    VALUES (?, ?, ?, ?, ?)
    """, (user_id, mode, source, title[:150], datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    con.commit()
    con.close()

def daily_ok(user_id: int) -> bool:
    row = get_user(user_id)
    if not row or user_id in ADMIN_IDS or row["is_premium"]:
        return True
    today = date.today().isoformat()
    con = db()
    cur = con.cursor()
    if row["today_date"] != today:
        cur.execute("UPDATE users SET today_date=?, today_count=1 WHERE user_id=?", (today, user_id))
        con.commit()
        con.close()
        return True
    if row["today_count"] >= DAILY_LIMIT_FREE:
        con.close()
        return False
    cur.execute("UPDATE users SET today_count=today_count+1 WHERE user_id=?", (user_id,))
    con.commit()
    con.close()
    return True

def stats():
    con = db()
    cur = con.cursor()
    users = cur.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
    downloads = cur.execute("SELECT SUM(downloads) s FROM users").fetchone()["s"] or 0
    channels = cur.execute("SELECT COUNT(*) c FROM channels").fetchone()["c"]
    banned = cur.execute("SELECT COUNT(*) c FROM users WHERE is_banned=1").fetchone()["c"]
    logs = cur.execute("SELECT COUNT(*) c FROM downloads_log").fetchone()["c"]
    con.close()
    return users, downloads, channels, banned, logs, len(os.listdir(TEMP_DIR))

def user_keyboard(user_id: int):
    rows = [[KeyboardButton(text=BTN_LINK)]]
    if user_id in ADMIN_IDS:
        rows.append([KeyboardButton(text=BTN_ADMIN)])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)

def admin_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📊 Statistika"), KeyboardButton(text="📋 Kanallar")],
            [KeyboardButton(text="➕ Kanal qo‘shish"), KeyboardButton(text="➖ Kanal o‘chirish")],
            [KeyboardButton(text="📢 Broadcast"), KeyboardButton(text="🔎 User topish")],
            [KeyboardButton(text="🚫 Ban"), KeyboardButton(text="✅ Unban")],
            [KeyboardButton(text="🧹 Tozalash"), KeyboardButton(text=BTN_BACK)],
        ],
        resize_keyboard=True
    )

def check_menu():
    rows = []
    for username, title in get_channels():
        rows.append([InlineKeyboardButton(text=f"🔔 {title}", url=f"https://t.me/{username}")])
    rows.append([InlineKeyboardButton(text="✅ Tekshirish", callback_data="check_sub")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def format_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎬 MP4 Video", callback_data="fmt_video")],
        [InlineKeyboardButton(text="🎵 MP3 Ovoz", callback_data="fmt_audio")],
        [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="cancel")]
    ])

def channel_delete_menu():
    channels = get_channels()
    rows = [[InlineKeyboardButton(text=f"❌ @{u}", callback_data=f"del_channel_{u}")] for u, _ in channels]
    rows.append([InlineKeyboardButton(text="⬅️ Orqaga", callback_data="admin_back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

async def is_subscribed(user_id: int) -> bool:
    channels = get_channels()
    if not channels:
        return True
    for username, _ in channels:
        try:
            member = await bot.get_chat_member(f"@{username}", user_id)
            if member.status in ("left", "kicked"):
                return False
        except Exception:
            return False
    return True

async def require_sub_message(message: Message) -> bool:
    if await is_subscribed(message.from_user.id):
        return True
    await message.answer(TEXT_NOT_SUB, reply_markup=check_menu())
    return False

async def require_sub_callback(call: CallbackQuery) -> bool:
    if await is_subscribed(call.from_user.id):
        return True
    await call.message.answer(TEXT_NOT_SUB, reply_markup=check_menu())
    await call.answer()
    return False

URL_RE = re.compile(r"https?://[^\s]+")
user_links: Dict[int, str] = {}
download_lock = asyncio.Semaphore(MAX_PARALLEL_DOWNLOADS)

def is_url(text: str) -> bool:
    return bool(URL_RE.search(text or ""))

def ydl_options(user_id: int, mode: str):
    unique = f"{user_id}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
    out = os.path.join(TEMP_DIR, f"{unique}_%(title).45s.%(ext)s")
    common = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "retries": 3,
        "fragment_retries": 3,
        "socket_timeout": 25,
        "geo_bypass": True,
        "concurrent_fragment_downloads": 8,
        "http_chunk_size": 10485760,
        "cachedir": False,
        "windowsfilenames": True,
        "outtmpl": out,
    }
    if mode == "audio":
        return {
            **common,
            "format": "bestaudio[ext=m4a]/bestaudio/best",
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "128",
            }],
        }
    return {
        **common,
        "format": "best[height<=720][ext=mp4]/best[height<=720]/best",
        "merge_output_format": "mp4",
    }

async def run_blocking(fn):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, fn)

async def download_media(url: str, user_id: int, mode: str) -> Tuple[str, str]:
    opts = ydl_options(user_id, mode)
    def run():
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get("title", "Media")
            filename = ydl.prepare_filename(info)
            if mode == "audio":
                filename = os.path.splitext(filename)[0] + ".mp3"
            else:
                if not os.path.exists(filename):
                    base = os.path.splitext(filename)[0]
                    for ext in (".mp4", ".webm", ".mkv"):
                        if os.path.exists(base + ext):
                            filename = base + ext
                            break
            return filename, title
    async with download_lock:
        return await run_blocking(run)

def safe_remove(path: str):
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except Exception:
        pass

def cleanup_temp(max_age=3600):
    now = datetime.now().timestamp()
    for folder in (TEMP_DIR, DOWNLOAD_DIR):
        os.makedirs(folder, exist_ok=True)
        for name in os.listdir(folder):
            path = os.path.join(folder, name)
            try:
                if os.path.isfile(path) and now - os.path.getmtime(path) > max_age:
                    os.remove(path)
            except Exception:
                pass

async def process_download(message: Message, user_id: int, mode: str):
    if not daily_ok(user_id):
        await message.answer(TEXT_LIMIT_END)
        return
    url = user_links.get(user_id)
    if not url:
        await message.answer(TEXT_SEND_URL)
        return
    status = await message.answer(TEXT_DOWNLOADING)
    try:
        path, title = await download_media(url, user_id, mode)
        if not os.path.exists(path):
            raise RuntimeError("Fayl topilmadi.")
        if os.path.getsize(path) > MAX_TG_FILE_MB * 1024 * 1024:
            safe_remove(path)
            await status.edit_text(TEXT_BIG_FILE)
            return
        await status.delete()
        if mode == "video":
            await message.answer_video(FSInputFile(path), caption=f"✅ {title[:100]}", supports_streaming=True, reply_markup=user_keyboard(user_id))
            log_mode = "video"
        else:
            await message.answer_audio(FSInputFile(path), caption=f"✅ {title[:100]}", reply_markup=user_keyboard(user_id))
            log_mode = "audio"
        inc_download(user_id, log_mode, url, title)
        safe_remove(path)
    except Exception as e:
        await status.edit_text(f"{TEXT_ERROR}\n\n<code>{str(e)[:300]}</code>")

async def set_commands():
    user_cmds = [
        BotCommand(command="start", description="Botni ishga tushirish"),
        BotCommand(command="help", description="Yordam va buyruqlar"),
        BotCommand(command="link", description="Link yuborish"),
        BotCommand(command="cancel", description="Bekor qilish"),
    ]
    await bot.set_my_commands(user_cmds)

@dp.message(CommandStart())
async def start(message: Message):
    add_user(message.from_user)
    user_id = message.from_user.id
    if is_banned(user_id):
        await message.answer(TEXT_BANNED)
        return
    if not await require_sub_message(message):
        return
    await message.answer(TEXT_START, reply_markup=user_keyboard(user_id))

@dp.message(Command("help"))
async def help_command(message: Message):
    add_user(message.from_user)
    if not await require_sub_message(message):
        return
    text = ADMIN_HELP_TEXT if message.from_user.id in ADMIN_IDS else HELP_TEXT
    await message.answer(text, reply_markup=user_keyboard(message.from_user.id))

@dp.message(Command("link"))
async def link_command(message: Message):
    add_user(message.from_user)
    if not await require_sub_message(message):
        return
    await message.answer(TEXT_SEND_URL, reply_markup=user_keyboard(message.from_user.id))

@dp.message(Command("cancel"))
async def cancel_command(message: Message, state: FSMContext):
    await state.clear()
    user_links.pop(message.from_user.id, None)
    await message.answer("❌ Bekor qilindi", reply_markup=user_keyboard(message.from_user.id))

@dp.message(Command("admin"))
async def admin_command(message: Message):
    add_user(message.from_user)
    if not await require_sub_message(message):
        return
    if message.from_user.id not in ADMIN_IDS:
        return
    await message.answer("👑 Admin panel", reply_markup=admin_keyboard())

@dp.message(Command("stats"))
async def stats_command(message: Message):
    add_user(message.from_user)
    if message.from_user.id not in ADMIN_IDS:
        return
    if not await require_sub_message(message):
        return
    users, downloads, channels, banned_count, logs, temp = stats()
    await message.answer(
        f"📊 <b>Statistika</b>\n\n"
        f"👥 Users: {users}\n"
        f"📥 Yuklamalar: {downloads}\n"
        f"📢 Kanallar: {channels}\n"
        f"🚫 Ban: {banned_count}\n"
        f"🧾 Loglar: {logs}\n"
        f"📁 Temp: {temp}",
        reply_markup=admin_keyboard()
    )

@dp.message(Command("channels"))
async def channels_command(message: Message):
    add_user(message.from_user)
    if message.from_user.id not in ADMIN_IDS:
        return
    if not await require_sub_message(message):
        return
    channels = get_channels()
    if not channels:
        await message.answer("📋 Kanallar yo‘q", reply_markup=admin_keyboard())
    else:
        msg = "📋 <b>Majburiy kanallar</b>\n\n"
        for i, (u, t) in enumerate(channels, 1):
            msg += f"{i}. @{u} — {t}\n"
        await message.answer(msg, reply_markup=admin_keyboard())

@dp.message(Command("add_channel"))
async def add_channel_command(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    if not await require_sub_message(message):
        return
    await state.set_state(AdminState.add_channel)
    await message.answer("➕ Kanal username yuboring:\nMasalan: @NWS_ALFA_07")

@dp.message(Command("remove_channel"))
async def remove_channel_command(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    if not await require_sub_message(message):
        return
    if not get_channels():
        await message.answer("📋 O‘chirish uchun kanal yo‘q", reply_markup=admin_keyboard())
    else:
        await message.answer("➖ O‘chiriladigan kanalni tanlang:", reply_markup=channel_delete_menu())

@dp.message(Command("broadcast"))
async def broadcast_command(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    if not await require_sub_message(message):
        return
    await state.set_state(AdminState.broadcast)
    await message.answer("📢 Yuboriladigan xabar matnini yozing:")

@dp.message(Command("find_user"))
async def find_user_command(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    await state.set_state(AdminState.find_user)
    await message.answer("🔎 User ID yuboring:")

@dp.message(Command("ban"))
async def ban_command(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    await state.set_state(AdminState.ban_user)
    await message.answer("🚫 Ban qilinadigan user ID yuboring:")

@dp.message(Command("unban"))
async def unban_command(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    await state.set_state(AdminState.unban_user)
    await message.answer("✅ Bandan chiqariladigan user ID yuboring:")

@dp.message(Command("cleanup"))
async def cleanup_command(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    cleanup_temp(max_age=0)
    await message.answer("🧹 Temp fayllar tozalandi", reply_markup=admin_keyboard())

@dp.callback_query(F.data == "check_sub")
async def check_sub(call: CallbackQuery):
    add_user(call.from_user)
    if await is_subscribed(call.from_user.id):
        await call.message.answer(TEXT_SUB_OK, reply_markup=user_keyboard(call.from_user.id))
    else:
        await call.message.answer(TEXT_NOT_SUB, reply_markup=check_menu())
    await call.answer()

@dp.callback_query(F.data.in_(["fmt_video", "fmt_audio"]))
async def choose_format(call: CallbackQuery):
    add_user(call.from_user)
    if is_banned(call.from_user.id):
        await call.message.answer(TEXT_BANNED)
        await call.answer()
        return
    if not await require_sub_callback(call):
        return
    mode = {"fmt_video": "video", "fmt_audio": "audio"}[call.data]
    await call.answer()
    await process_download(call.message, call.from_user.id, mode)

@dp.callback_query(F.data == "cancel")
async def cancel(call: CallbackQuery):
    user_links.pop(call.from_user.id, None)
    await call.message.answer("❌ Bekor qilindi", reply_markup=user_keyboard(call.from_user.id))
    await call.answer()

@dp.callback_query(F.data == "admin_back")
async def admin_back(call: CallbackQuery):
    if call.from_user.id in ADMIN_IDS:
        await call.message.answer("👑 Admin panel", reply_markup=admin_keyboard())
    await call.answer()

@dp.callback_query(F.data.startswith("del_channel_"))
async def delete_channel_callback(call: CallbackQuery):
    if call.from_user.id not in ADMIN_IDS:
        await call.answer()
        return
    if not await require_sub_callback(call):
        return
    username = call.data.replace("del_channel_", "")
    remove_channel(username)
    await call.message.answer(f"✅ @{username} o‘chirildi", reply_markup=admin_keyboard())
    await call.answer()

@dp.message(AdminState.add_channel)
async def add_channel_state(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    if not await require_sub_message(message):
        await state.clear()
        return
    username = normalize_channel(message.text)
    add_channel(username)
    await state.clear()
    await message.answer(f"✅ Kanal qo‘shildi: @{username}", reply_markup=admin_keyboard())

@dp.message(AdminState.broadcast)
async def broadcast_state(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    if not await require_sub_message(message):
        await state.clear()
        return
    status = await message.answer("⏳ Broadcast yuborilmoqda...")
    ok, fail = 0, 0
    for user_id in get_all_users():
        try:
            await bot.send_message(user_id, message.text, reply_markup=user_keyboard(user_id))
            ok += 1
            await asyncio.sleep(0.05)
        except Exception:
            fail += 1
    await state.clear()
    await status.edit_text(f"📢 Broadcast tugadi:\n\n✅ Yuborildi: {ok}\n❌ Xato: {fail}")

@dp.message(AdminState.ban_user)
async def ban_state(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    try:
        user_id = int(message.text.strip())
        set_ban(user_id, True)
        await message.answer(f"🚫 User ban qilindi: <code>{user_id}</code>", reply_markup=admin_keyboard())
    except Exception:
        await message.answer("❌ ID noto‘g‘ri", reply_markup=admin_keyboard())
    await state.clear()

@dp.message(AdminState.unban_user)
async def unban_state(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    try:
        user_id = int(message.text.strip())
        set_ban(user_id, False)
        await message.answer(f"✅ User bandan chiqarildi: <code>{user_id}</code>", reply_markup=admin_keyboard())
    except Exception:
        await message.answer("❌ ID noto‘g‘ri", reply_markup=admin_keyboard())
    await state.clear()

@dp.message(AdminState.find_user)
async def find_user_state(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    try:
        user_id = int(message.text.strip())
        row = get_user(user_id)
        if not row:
            await message.answer("❌ User topilmadi", reply_markup=admin_keyboard())
        else:
            await message.answer(
                f"🔎 <b>User ma’lumotlari</b>\n\n"
                f"🆔 ID: <code>{row['user_id']}</code>\n"
                f"👤 Ism: {row['full_name']}\n"
                f"🔗 Username: @{row['username'] or 'none'}\n"
                f"📥 Yuklamalar: {row['downloads']}\n"
                f"🚫 Ban: {row['is_banned']}\n"
                f"📅 Kirgan: {row['joined_at']}\n"
                f"🕒 Oxirgi aktiv: {row['last_active']}",
                reply_markup=admin_keyboard()
            )
    except Exception:
        await message.answer("❌ ID noto‘g‘ri", reply_markup=admin_keyboard())
    await state.clear()

@dp.message(F.text)
async def text_handler(message: Message, state: FSMContext):
    add_user(message.from_user)
    user_id = message.from_user.id
    text = message.text.strip()
    if is_banned(user_id):
        await message.answer(TEXT_BANNED)
        return
    if not await require_sub_message(message):
        return

    if user_id in ADMIN_IDS:
        if text == BTN_ADMIN:
            await message.answer("👑 Admin panel", reply_markup=admin_keyboard()); return
        if text == BTN_BACK:
            await state.clear(); await message.answer(TEXT_START, reply_markup=user_keyboard(user_id)); return
        if text == "📊 Statistika":
            await stats_command(message); return
        if text == "📋 Kanallar":
            await channels_command(message); return
        if text == "➕ Kanal qo‘shish":
            await add_channel_command(message, state); return
        if text == "➖ Kanal o‘chirish":
            await remove_channel_command(message); return
        if text == "📢 Broadcast":
            await broadcast_command(message, state); return
        if text == "🚫 Ban":
            await ban_command(message, state); return
        if text == "✅ Unban":
            await unban_command(message, state); return
        if text == "🔎 User topish":
            await find_user_command(message, state); return
        if text == "🧹 Tozalash":
            await cleanup_command(message); return

    if text == BTN_LINK:
        await message.answer(TEXT_SEND_URL, reply_markup=user_keyboard(user_id)); return

    if is_url(text):
        user_links[user_id] = text
        await message.answer(TEXT_CHOOSE_FORMAT, reply_markup=format_menu()); return

    await message.answer(
        "🔗 Iltimos, video/audio link yuboring.\n\nMasalan: YouTube, Instagram, TikTok, Facebook link.",
        reply_markup=user_keyboard(user_id)
    )

@dp.errors()
async def error_handler(event: ErrorEvent):
    print("ERROR:", repr(event.exception))
    return True

async def periodic_cleanup():
    while True:
        await asyncio.sleep(1800)
        cleanup_temp()

async def main():
    init_db()
    add_channel("NWS_ALFA_07", "Kanal 1")
    add_channel("ALFA_BONUS_NEWS", "Kanal 2")

    await set_commands()

    threading.Thread(target=run_flask, daemon=True).start()
    asyncio.create_task(periodic_cleanup())

    print("=" * 60)
    print("🤖 ALFA Media Bot V5 COMMANDS ishga tushdi ✅")
    print(f"👑 Adminlar: {ADMIN_IDS}")
    print(f"📢 Kanallar: {len(get_channels())}")
    print("=" * 60)

    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
