import asyncio
import json
import os
import re
import sqlite3
import threading
from datetime import datetime, timedelta

import requests
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    Update,
)
from telegram.constants import KeyboardButtonStyle as KBS
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# ==================== CONFIGURATION ====================


BOT_TOKEN = "8216427126:AAHuqO9WxhgesbEK6z09K6Mq4LuDawKx3tg"
ADMIN_IDS = [8478266638]

# ==================== LOAD COUNTRIES FROM JSON FILE ====================

def load_countries_db():
    try:
        with open('countries.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        print("⚠️ countries.json not found! Creating default...")
        default = {
            "Pakistan": {"code": "+92", "iso": "PK", "flag": "🇵🇰"},
            "India": {"code": "+91", "iso": "IN", "flag": "🇮🇳"},
            "Venezuela": {"code": "+58", "iso": "VE", "flag": "🇻🇪"},
            "Nigeria": {"code": "+234", "iso": "NG", "flag": "🇳🇬"},
        }
        with open('countries.json', 'w', encoding='utf-8') as f:
            json.dump(default, f, indent=2, ensure_ascii=False)
        return default

COUNTRIES_DATA = load_countries_db()

def get_country_info(country_name):
    return COUNTRIES_DATA.get(country_name, {"flag": "🏁", "code": ""})

# ==================== JOIN CHECK CONFIGURATION ====================

REQUIRED_CHANNELS = [
    "@AmirEarnings",
    "@AmirXOtp",
]

GROUP_LINKS = {
    "tech_channel": "https://t.me/Tech_with_mr_meer",
    "otp_group": "put otp group",
    "whatsapp": "put your whatsapp if you want",
}

# ==================== API CONFIGURATION ====================

API_URL = "put your panel api url"
API_TOKEN = "Put your panel api token"

# ==================== DATABASE SETUP ====================

conn = sqlite3.connect('mrisbrand_master.db', check_same_thread=False)
db_lock = threading.Lock()
c = conn.cursor()

c.execute('''CREATE TABLE IF NOT EXISTS users
             (user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT,
              joined_date TEXT, invites INTEGER DEFAULT 0, free_accounts INTEGER DEFAULT 0,
              last_active TEXT, current_number_id INTEGER DEFAULT NULL,
              current_number TEXT DEFAULT NULL, current_country TEXT DEFAULT NULL,
              current_service TEXT DEFAULT NULL, number_expiry TEXT DEFAULT NULL,
              last_menu_message_id INTEGER DEFAULT NULL, referred_by INTEGER DEFAULT NULL,
              joined_check INTEGER DEFAULT 0)''')

c.execute('''CREATE TABLE IF NOT EXISTS numbers
             (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, number TEXT,
              country TEXT, service TEXT, assigned_date TEXT, status TEXT DEFAULT 'active',
              expiry_time TEXT)''')

c.execute('''CREATE TABLE IF NOT EXISTS otps
             (id INTEGER PRIMARY KEY AUTOINCREMENT, number TEXT, otp TEXT,
              message TEXT, timestamp TEXT, forwarded INTEGER DEFAULT 0, user_id INTEGER)''')

c.execute('''CREATE TABLE IF NOT EXISTS countries
             (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, service TEXT,
              flag TEXT, active INTEGER DEFAULT 1, stock INTEGER DEFAULT 0)''')

c.execute('''CREATE TABLE IF NOT EXISTS available_numbers
             (id INTEGER PRIMARY KEY AUTOINCREMENT, country TEXT, service TEXT,
              number TEXT, used INTEGER DEFAULT 0)''')

c.execute('''CREATE TABLE IF NOT EXISTS used_numbers
             (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, number TEXT,
              country TEXT, service TEXT, assigned_date TEXT)''')

c.execute('''CREATE TABLE IF NOT EXISTS referral_settings
             (id INTEGER PRIMARY KEY AUTOINCREMENT, points_needed INTEGER DEFAULT 50)''')

c.execute('''CREATE TABLE IF NOT EXISTS completed_referrals
             (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
              completed_date TEXT, reward_given INTEGER DEFAULT 0)''')

c.execute("INSERT OR IGNORE INTO referral_settings (id, points_needed) VALUES (1, 50)")
conn.commit()

print("✅ Database setup completed")

# ==================== STATE TRACKING ====================

admin_mode = {}
admin_panel_state = {}

# ==================== HELPER ====================

def safe_url(url: str) -> str | None:
    """Return URL only if it's a valid http(s)/tg link, else None."""
    if url and isinstance(url, str) and (url.startswith("http://") or url.startswith("https://") or url.startswith("tg://")):
        return url
    return None

# ==================== KEYBOARD BUILDERS (ALL INLINE + COLORED) ====================

BTN_GET_NUMBER = "📱 Get Number"
BTN_LIVE_STOCK = "📊 Live Stock"
BTN_INVITE = "👥 Invite & Earn"
BTN_SUPPORT = "🎧 Support"
BTN_ADMIN = "👑 Admin Panel"

def bottom_menu_keyboard(user_id: int) -> ReplyKeyboardMarkup:
    rows = [
        [
            KeyboardButton(BTN_GET_NUMBER, style=KBS.PRIMARY),
            KeyboardButton(BTN_LIVE_STOCK, style=KBS.PRIMARY),
        ],
        [
            KeyboardButton(BTN_INVITE, style=KBS.SUCCESS),
            KeyboardButton(BTN_SUPPORT, style=KBS.SUCCESS),
        ],
    ]
    if user_id in ADMIN_IDS:
        rows.append([KeyboardButton(BTN_ADMIN, style=KBS.DANGER)])
    return ReplyKeyboardMarkup(
        rows, resize_keyboard=True, is_persistent=True,
        input_field_placeholder="Choose an option...")

def main_menu_keyboard(user_id: int) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton("📱 Get Number", callback_data="menu_get_number", style=KBS.PRIMARY),
            InlineKeyboardButton("📊 Live Stock", callback_data="menu_live_stock", style=KBS.PRIMARY),
        ],
        [
            InlineKeyboardButton("👥 Invite & Earn", callback_data="menu_invite", style=KBS.SUCCESS),
            InlineKeyboardButton("🎧 Support", callback_data="menu_support", style=KBS.SUCCESS),
        ],
        [
            InlineKeyboardButton("🏆 Credits", callback_data="menu_credits", style=KBS.PRIMARY),
        ],
    ]
    if user_id in ADMIN_IDS:
        rows.append([
            InlineKeyboardButton("👑 Admin Panel", callback_data="menu_admin", style=KBS.DANGER),
        ])
    return InlineKeyboardMarkup(rows)

def back_to_main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 Back to Main Menu", callback_data="back_to_menu", style=KBS.PRIMARY)],
    ])

def join_required_keyboard() -> InlineKeyboardMarkup:
    rows = []
    tech = safe_url(GROUP_LINKS.get("tech_channel"))
    otp = safe_url(GROUP_LINKS.get("otp_group"))
    wa = safe_url(GROUP_LINKS.get("whatsapp"))
    if tech:
        rows.append([InlineKeyboardButton("📢 Join Tech Channel", url=tech, style=KBS.PRIMARY)])
    if otp:
        rows.append([InlineKeyboardButton("👥 Join OTP Group", url=otp, style=KBS.PRIMARY)])
    if wa:
        rows.append([InlineKeyboardButton("📱 Join WhatsApp Channel", url=wa, style=KBS.PRIMARY)])
    rows.append([InlineKeyboardButton("✅ I've Joined All — Verify", callback_data="check_joined", style=KBS.SUCCESS)])
    return InlineKeyboardMarkup(rows)

def admin_panel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📊 Statistics", callback_data="admin_stats", style=KBS.PRIMARY),
            InlineKeyboardButton("📤 Upload Stock", callback_data="admin_upload", style=KBS.SUCCESS),
        ],
        [
            InlineKeyboardButton("🗑 Delete Stock", callback_data="admin_delete", style=KBS.DANGER),
            InlineKeyboardButton("🎁 Referrals", callback_data="admin_referrals", style=KBS.SUCCESS),
        ],
        [
            InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast", style=KBS.PRIMARY),
            InlineKeyboardButton("👥 Give Account", callback_data="admin_giveaway", style=KBS.SUCCESS),
        ],
        [
            InlineKeyboardButton("📋 View Countries", callback_data="admin_countries", style=KBS.PRIMARY),
            InlineKeyboardButton("⚙️ Settings", callback_data="admin_settings", style=KBS.PRIMARY),
        ],
        [
            InlineKeyboardButton("👥 Total Users", callback_data="admin_total_users", style=KBS.PRIMARY),
            InlineKeyboardButton("❌ Exit Admin", callback_data="admin_exit", style=KBS.DANGER),
        ],
        [
            InlineKeyboardButton("🔙 Back to Main Menu", callback_data="back_to_menu", style=KBS.PRIMARY),
        ],
    ])

def admin_back_button() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🔙 Back to Admin Panel", callback_data="admin_back", style=KBS.PRIMARY),
    ]])

def admin_cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("❌ Cancel", callback_data="admin_back", style=KBS.DANGER),
    ]])

def number_action_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton("🔄 Get Next Number", callback_data="next_number", style=KBS.SUCCESS),
            InlineKeyboardButton("🌍 Change Country", callback_data="back_to_countries", style=KBS.PRIMARY),
        ],
    ]
    otp = safe_url(GROUP_LINKS.get("otp_group"))
    if otp:
        rows.append([InlineKeyboardButton("👥 Join OTP Group", url=otp, style=KBS.PRIMARY)])
    rows.append([InlineKeyboardButton("🏠 Main Menu", callback_data="back_to_menu", style=KBS.DANGER)])
    return InlineKeyboardMarkup(rows)

def countries_keyboard(countries: list) -> InlineKeyboardMarkup:
    rows = []
    for country in countries:
        country_name = country[0]
        service = country[1]
        stock = country[2]
        country_info = get_country_info(country_name)
        flag = country_info.get("flag", "🏁")
        btn_text = f"{flag} {country_name} — {service} ({stock})"
        cb_data = f"sel|{country_name}|{service}"
        if len(cb_data.encode('utf-8')) > 64:
            cb_data = cb_data[:60]
        rows.append([InlineKeyboardButton(btn_text, callback_data=cb_data, style=KBS.SUCCESS)])
    rows.append([InlineKeyboardButton("🏠 Back to Main Menu", callback_data="back_to_menu", style=KBS.DANGER)])
    return InlineKeyboardMarkup(rows)

def stock_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Refresh Stock", callback_data="refresh_stock", style=KBS.SUCCESS)],
        [InlineKeyboardButton("🏠 Back to Main Menu", callback_data="back_to_menu", style=KBS.PRIMARY)],
    ])

def invite_keyboard(invite_link: str) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(
            "📤 Share Invite Link",
            switch_inline_query=f"Join Developer Amir Bot for free virtual numbers! {invite_link}",
            style=KBS.SUCCESS,
        )],
        [InlineKeyboardButton("👤 Contact Admin Support", url="https://t.me/Developer_Amirr", style=KBS.PRIMARY)],
        [InlineKeyboardButton("🏠 Back to Main Menu", callback_data="back_to_menu", style=KBS.DANGER)],
    ]
    return InlineKeyboardMarkup(rows)

def support_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👤 Contact Admin Support", url="https://t.me/Developer_Amirr", style=KBS.SUCCESS)],
        [InlineKeyboardButton("🏠 Back to Main Menu", callback_data="back_to_menu", style=KBS.PRIMARY)],
    ])

def credits_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏠 Back to Main Menu", callback_data="back_to_menu", style=KBS.PRIMARY)],
    ])

def settings_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("25 Invites", callback_data="admin_set_referral_25", style=KBS.PRIMARY),
            InlineKeyboardButton("50 Invites", callback_data="admin_set_referral_50", style=KBS.PRIMARY),
            InlineKeyboardButton("100 Invites", callback_data="admin_set_referral_100", style=KBS.PRIMARY),
        ],
        [InlineKeyboardButton("✏️ Custom Value", callback_data="admin_set_referral_custom", style=KBS.SUCCESS)],
        [InlineKeyboardButton("🔙 Back to Admin Panel", callback_data="admin_back", style=KBS.DANGER)],
    ])

# ==================== DATABASE HELPER FUNCTIONS ====================

def db_exec(query, params=()):
    with db_lock:
        c.execute(query, params)
        conn.commit()

def db_fetch_one(query, params=()):
    with db_lock:
        c.execute(query, params)
        return c.fetchone()

def db_fetch_all(query, params=()):
    with db_lock:
        c.execute(query, params)
        return c.fetchall()

def get_referral_points_needed():
    result = db_fetch_one("SELECT points_needed FROM referral_settings WHERE id = 1")
    return result[0] if result else 50

def update_referral_points(points):
    db_exec("UPDATE referral_settings SET points_needed = ? WHERE id = 1", (points,))

def extract_country_from_filename(filename):
    try:
        name = filename.replace('.txt', '')
        for country_name in COUNTRIES_DATA.keys():
            if country_name.lower() in name.lower():
                return country_name
        return None
    except Exception:
        return None

def extract_service_from_filename(filename):
    try:
        name = filename.replace('.txt', '').lower()
        services = ["WhatsApp", "Telegram", "Facebook", "IMO", "W-A", "T-G", "F-C", "R-K", "N-T"]
        for service in services:
            if service.lower() in name:
                return service
        return "Unknown"
    except Exception:
        return "Unknown"

def load_numbers_from_file(file_path, filename):
    try:
        country = extract_country_from_filename(filename)
        service = extract_service_from_filename(filename)

        if not country:
            return 0, "❌ Country not found in database! Please add to countries.json first."

        country_info = get_country_info(country)
        flag = country_info.get("flag", "🏁")

        with open(file_path, 'r', encoding='utf-8', errors='ignore') as file:
            numbers = file.read().strip().split('\n')

        valid_numbers = []
        for num in numbers:
            num = num.strip()
            if num:
                if not num.startswith('+'):
                    num = '+' + num
                valid_numbers.append(num)

        if not valid_numbers:
            return 0, "❌ No valid numbers found in file!"

        with db_lock:
            for number in valid_numbers:
                c.execute('''INSERT INTO available_numbers (country, service, number)
                             VALUES (?, ?, ?)''', (country, service, number))

            c.execute('''INSERT OR IGNORE INTO countries (name, service, flag, stock)
                         VALUES (?, ?, ?, 0)''', (country, service, flag))

            c.execute("SELECT stock FROM countries WHERE name = ? AND service = ?", (country, service))
            current = c.fetchone()
            current_stock = current[0] if current else 0

            c.execute('''UPDATE countries SET stock = ?, active = 1
                         WHERE name = ? AND service = ?''',
                      (current_stock + len(valid_numbers), country, service))
            conn.commit()

        return len(valid_numbers), f"✅ Added {len(valid_numbers)} {flag} {country} {service} numbers!"

    except Exception as e:
        print(f"Error loading file: {e}")
        return 0, f"❌ Error: {str(e)}"

def delete_country_stock(country, service):
    try:
        db_exec("DELETE FROM available_numbers WHERE country = ? AND service = ?", (country, service))
        db_exec("DELETE FROM countries WHERE name = ? AND service = ?", (country, service))
        return True
    except Exception as e:
        print(f"Error deleting stock: {e}")
        return False

def get_random_number_from_stock(country, service):
    try:
        with db_lock:
            c.execute('''SELECT COUNT(*) FROM available_numbers
                         WHERE country = ? AND service = ? AND used = 0''', (country, service))
            count = c.fetchone()[0]

            if count == 0:
                return None, None

            c.execute('''SELECT id, number FROM available_numbers
                         WHERE country = ? AND service = ? AND used = 0
                         ORDER BY RANDOM() LIMIT 1''', (country, service))
            result = c.fetchone()

            if result:
                number_id, number = result
                c.execute("UPDATE available_numbers SET used = 1 WHERE id = ?", (number_id,))
                c.execute(
                    "UPDATE countries SET stock = MAX(0, stock - 1) WHERE name = ? AND service = ?",
                    (country, service))
                conn.commit()
                return number_id, number
        return None, None
    except Exception as e:
        print(f"Error getting number: {e}")
        return None, None

def extract_otp_from_message(message_text):
    try:
        patterns = [r'(\d{3}-\d{3})', r'(\d{6})', r'(\d{4,8})']
        for pattern in patterns:
            match = re.search(pattern, message_text)
            if match:
                return match.group(1)
        return None
    except Exception:
        return None

def get_user_current_number(user_id):
    result = db_fetch_one(
        '''SELECT current_number, current_country, current_service, number_expiry
           FROM users WHERE user_id = ?''', (user_id,))
    if result and result[0]:
        number, country, service, expiry = result
        if expiry:
            try:
                if datetime.now() < datetime.strptime(expiry, "%Y-%m-%d %H:%M:%S"):
                    return number, country, service, expiry
            except ValueError:
                pass
    return None, None, None, None

def format_number_message(country, service, number):
    country_info = get_country_info(country)
    flag = country_info.get("flag", "🏁")
    current_time = datetime.now().strftime('%I:%M %p')
    if not number.startswith('+'):
        number = '+' + number

    message = (
        f"✅ *Your Number is Ready!*\n\n"
        f"🌍 *Country:* {flag} {country}\n"
        f"📱 *Service:* {service}\n"
        f"📞 *Number:*\n`{number}`\n\n"
        f"🕐 *Assigned at:* {current_time}\n"
        f"⏳ *Expires in:* 1 hour\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"👨‍💻 *Developer:* Amir"
    )
    return message, number_action_keyboard()

# ==================== JOIN CHECK FUNCTIONS ====================

async def check_joined_channels(bot, user_id):
    try:
        for channel in REQUIRED_CHANNELS:
            member = await bot.get_chat_member(channel, user_id)
            if member.status not in ['member', 'administrator', 'creator']:
                return False
        return True
    except Exception as e:
        print(f"Join check error for user {user_id}: {e}")
        return False

async def verify_user_access(bot, user_id):
    if user_id in ADMIN_IDS:
        return True
    if await check_joined_channels(bot, user_id):
        db_exec("UPDATE users SET joined_check = 1 WHERE user_id = ?", (user_id,))
        return True
    else:
        db_exec("UPDATE users SET joined_check = 0 WHERE user_id = ?", (user_id,))
        return False

async def send_join_required(bot, user_id):
    await bot.send_message(
        user_id,
        "⚠️ *Access Required*\n\n"
        "Please join ALL of the following to use this bot:\n\n"
        "1️⃣ Tech Channel\n"
        "2️⃣ OTP Group\n"
        "3️⃣ WhatsApp Channel\n\n"
        "✅ After joining, click *I've Joined All — Verify* below.",
        reply_markup=join_required_keyboard(),
        parse_mode='Markdown',
    )

# ==================== OTP & CLEANUP JOBS ====================

async def monitor_otp_job(context: ContextTypes.DEFAULT_TYPE):
    try:
        if "put your panel api url" in API_URL:
            return

        url = f"{API_URL}?token={API_TOKEN}"
        response = requests.get(url, timeout=15)

        if response.status_code != 200:
            return

        try:
            data = response.json()
        except Exception:
            return

        active_numbers = {
            row[0].replace('+', ''): row[1]
            for row in db_fetch_all(
                '''SELECT number, user_id FROM numbers
                   WHERE status = 'active' AND expiry_time > ?''',
                (datetime.now().strftime("%Y-%m-%d %H:%M:%S"),)
            )
        }

        if isinstance(data, list):
            for item in data:
                if isinstance(item, list) and len(item) >= 3:
                    service = item[0] if len(item) > 0 else "Unknown"
                    number = item[1] if len(item) > 1 else ""
                    message = item[2] if len(item) > 2 else ""
                    timestamp = item[3] if len(item) > 3 else datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                    number_clean = number.replace('+', '')

                    if number_clean in active_numbers:
                        user_id = active_numbers[number_clean]
                        otp = extract_otp_from_message(message)

                        if otp:
                            existing = db_fetch_one(
                                'SELECT id FROM otps WHERE number = ? AND otp = ?', (number, otp))
                            if not existing:
                                db_exec(
                                    '''INSERT INTO otps (number, otp, message, timestamp, user_id)
                                       VALUES (?, ?, ?, ?, ?)''',
                                    (number, otp, message[:200], timestamp, user_id))

                                otp_msg = (
                                    "╔═══════════════════╗\n"
                                    "    📩 *OTP RECEIVED*  \n"
                                    "╚═══════════════════╝\n\n"
                                    f"📱 *Number:* `{number}`\n"
                                    f"🔑 *OTP CODE:* `{otp}`\n"
                                    f"💬 *Service:* {service}\n"
                                    f"⏱ *Time:* {timestamp}\n"
                                    "━━━━━━━━━━━━━━━━━"
                                )
                                try:
                                    await context.bot.send_message(
                                        user_id, otp_msg, parse_mode='Markdown')
                                except Exception:
                                    pass
    except Exception as e:
        print(f"OTP Monitor Error: {e}")

async def cleanup_expired_job(context: ContextTypes.DEFAULT_TYPE):
    try:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        db_exec(
            "UPDATE numbers SET status = 'expired' WHERE expiry_time < ? AND status = 'active'",
            (now,))
        db_exec(
            '''UPDATE users SET
               current_number = NULL, current_country = NULL,
               current_service = NULL, number_expiry = NULL
               WHERE number_expiry < ?''', (now,))
    except Exception as e:
        print(f"Cleanup Error: {e}")

# ==================== NOTIFY USERS HELPER ====================

async def notify_users_about_new_numbers(bot, country, service, flag, count):
    users = db_fetch_all("SELECT user_id FROM users WHERE joined_check = 1")
    notification = (
        f"✨ *{flag} {country} — {service}* ✨\n\n"
        f"🔥 *{count} Fresh Numbers Added!*\n"
        "⚡ Speed up — grab yours now!"
    )
    for user in users:
        try:
            await bot.send_message(user[0], notification, parse_mode='Markdown')
            await asyncio.sleep(0.05)
        except Exception:
            continue

# ==================== TEXT BUILDERS ====================

def welcome_text(user_id, first_name):
    return (
        f"✨ *Welcome to Developer Amir Bot, {first_name}!* ✨\n\n"
        "🚀 _Your Premium Platform for Virtual Numbers._\n\n"
        f"🆔 *Your ID:* `{user_id}`\n"
        "✅ *You are a Verified Member!*\n\n"
        "🎮 _Tap a button below to navigate._\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "👨‍💻 *Developer:* Amir"
    )

def credits_text():
    return (
        "╔══════════════════════╗\n"
        "    🏆 *BOT CREDITS*      \n"
        "╚══════════════════════╝\n\n"
        "🤖 *Bot:* Developer Amir OTP Bot\n"
        "👨‍💻 *Developer:* Amir\n"
        "⚡ *Powered by:* python-telegram-bot\n"
        "🗄 *Database:* SQLite\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "_All rights reserved © Developer Amir_"
    )

def stock_text():
    data = db_fetch_all(
        "SELECT name, service, stock FROM countries WHERE active = 1 ORDER BY name")
    if not data:
        return "📊 *CURRENT LIVE STOCK*\n━━━━━━━━━━━━━━━━━━━━\n\n❌ No stock available."
    text = "📊 *CURRENT LIVE STOCK*\n━━━━━━━━━━━━━━━━━━━━\n\n"
    for item in data:
        country_info = get_country_info(item[0])
        flag = country_info.get("flag", "🏁")
        stock_bar = "🟢" if item[2] > 0 else "🔴"
        text += f"{stock_bar} {flag} *{item[0]}* — {item[1]}: `{item[2]}`\n"
    text += f"\n🕒 *Updated:* `{datetime.now().strftime('%H:%M:%S | %d %B %Y')}`"
    return text

# ==================== /start COMMAND ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username
    first_name = update.effective_user.first_name or "User"

    print(f"📩 /start from user {user_id} ({first_name})")

    ref_id = None
    if context.args:
        try:
            ref_id = int(context.args[0])
        except Exception:
            ref_id = None

    db_exec(
        '''INSERT OR IGNORE INTO users
           (user_id, username, first_name, joined_date, last_active, referred_by)
           VALUES (?, ?, ?, ?, ?, ?)''',
        (user_id, username, first_name,
         datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
         datetime.now().strftime("%Y-%m-%d %H:%M:%S"), ref_id))
    db_exec("UPDATE users SET last_active = ? WHERE user_id = ?",
            (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), user_id))

    if ref_id and ref_id != user_id:
        db_exec("UPDATE users SET invites = invites + 1 WHERE user_id = ?", (ref_id,))
        result = db_fetch_one("SELECT invites FROM users WHERE user_id = ?", (ref_id,))
        if result:
            invites = result[0]
            points_needed = get_referral_points_needed()
            if invites % points_needed == 0:
                db_exec(
                    "UPDATE users SET free_accounts = free_accounts + 1 WHERE user_id = ?",
                    (ref_id,))
                db_exec(
                    '''INSERT INTO completed_referrals (user_id, completed_date, reward_given)
                       VALUES (?, ?, ?)''',
                    (ref_id, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), 1))
                try:
                    await context.bot.send_message(
                        ref_id,
                        f"🎉 *Congratulations!*\n\n"
                        f"You've completed *{invites} invites* and earned *1 free account!* 🎁",
                        parse_mode='Markdown')
                except Exception:
                    pass

    if not await verify_user_access(context.bot, user_id):
        await send_join_required(context.bot, user_id)
        return

    # ONE welcome message only — bottom keyboard attached, no extra panel
    await update.message.reply_text(
        welcome_text(user_id, first_name),
        reply_markup=bottom_menu_keyboard(user_id),
        parse_mode='Markdown',
    )

# ==================== MAIN MENU CALLBACK HANDLERS ====================

async def show_main_menu(query, user_id, first_name):
    try:
        await query.edit_message_text(
            welcome_text(user_id, first_name),
            reply_markup=main_menu_keyboard(user_id),
            parse_mode='Markdown')
    except Exception:
        try:
            await query.message.reply_text(
                welcome_text(user_id, first_name),
                reply_markup=main_menu_keyboard(user_id),
                parse_mode='Markdown')
        except Exception:
            pass

async def show_get_number(query, context, user_id):
    db_exec("UPDATE users SET last_active = ? WHERE user_id = ?",
            (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), user_id))

    number, country, service, expiry = get_user_current_number(user_id)
    if number:
        msg, kb = format_number_message(country, service, number)
        try:
            await query.edit_message_text(
                f"📱 *You already have an active number:*\n\n{msg}",
                reply_markup=kb,
                parse_mode='Markdown')
        except Exception:
            await context.bot.send_message(
                user_id,
                f"📱 *You already have an active number:*\n\n{msg}",
                reply_markup=kb,
                parse_mode='Markdown')
        return

    countries = db_fetch_all(
        "SELECT name, service, stock FROM countries WHERE active = 1 AND stock > 0 ORDER BY name")

    if not countries:
        try:
            await query.edit_message_text(
                "❌ *No numbers available at the moment.*\n\n"
                "Please check back later or contact admin.",
                reply_markup=back_to_main_keyboard(),
                parse_mode='Markdown')
        except Exception:
            pass
        return

    try:
        await query.edit_message_text(
            "📲 *Select a Country & Service:*\n\n"
            "Choose from the list below to get your virtual number.",
            reply_markup=countries_keyboard(countries),
            parse_mode='Markdown')
    except Exception:
        pass

async def show_live_stock(query):
    try:
        await query.edit_message_text(
            stock_text(), reply_markup=stock_keyboard(), parse_mode='Markdown')
    except Exception:
        pass

async def show_invite_earn(query, context, user_id):
    result = db_fetch_one(
        "SELECT invites, free_accounts FROM users WHERE user_id = ?", (user_id,))
    invites = result[0] if result else 0
    free_accounts = result[1] if result else 0
    points_needed = get_referral_points_needed()
    bot_me = await context.bot.get_me()
    invite_link = f"https://t.me/{bot_me.username}?start={user_id}"
    remaining = points_needed - (invites % points_needed) if invites % points_needed != 0 else 0

    text = (
        "👥 *INVITE & EARN SYSTEM*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📊 *Your Invites:* `{invites}`\n"
        f"🎁 *Free Accounts Earned:* `{free_accounts}`\n"
        f"🎯 *Invites to next reward:* `{remaining}`\n\n"
        f"🔗 *Your Invite Link:*\n`{invite_link}`\n\n"
        f"💡 *{points_needed} Invites = 1 Free Account!*\n\n"
        "Share your link and earn premium virtual numbers for free!\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "👨‍💻 *Developer:* Amir"
    )
    try:
        await query.edit_message_text(
            text,
            reply_markup=invite_keyboard(invite_link),
            parse_mode='Markdown',
            disable_web_page_preview=True)
    except Exception:
        pass

async def show_support(query):
    try:
        await query.edit_message_text(
            "🎧 *CONTACT SUPPORT*\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "For any issues, questions, or requests — contact admin directly.\n\n"
            "👨‍💻 *Developer:* Amir",
            reply_markup=support_keyboard(),
            parse_mode='Markdown')
    except Exception:
        pass

async def show_credits(query):
    try:
        await query.edit_message_text(
            credits_text(), reply_markup=credits_keyboard(), parse_mode='Markdown')
    except Exception:
        pass

async def show_admin_panel_menu(query, user_id):
    if user_id not in ADMIN_IDS:
        await query.answer("❌ Unauthorized!", show_alert=True)
        return
    admin_mode[user_id] = True
    admin_panel_state[user_id] = "main"
    try:
        await query.edit_message_text(
            "🛡 *ADMIN PANEL*\n\n👨‍💻 *Developer:* Amir\n\nSelect an action below:",
            reply_markup=admin_panel_keyboard(),
            parse_mode='Markdown')
    except Exception:
        pass

async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    first_name = query.from_user.first_name or "User"
    data = query.data

    if not await verify_user_access(context.bot, user_id):
        await query.answer("❌ Please join all channels first!", show_alert=True)
        await send_join_required(context.bot, user_id)
        return

    await query.answer()
    action = data[len("menu_"):]

    if action == "get_number":
        await show_get_number(query, context, user_id)
    elif action == "live_stock":
        await show_live_stock(query)
    elif action == "invite":
        await show_invite_earn(query, context, user_id)
    elif action == "support":
        await show_support(query)
    elif action == "credits":
        await show_credits(query)
    elif action == "admin":
        await show_admin_panel_menu(query, user_id)

async def back_to_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    first_name = query.from_user.first_name or "User"
    await query.answer()
    await show_main_menu(query, user_id, first_name)

# ==================== CALLBACK QUERY HANDLERS — NUMBER FLOW ====================

async def check_joined_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    first_name = query.from_user.first_name or "User"

    await query.answer()

    if await verify_user_access(context.bot, user_id):
        try:
            await query.delete_message()
        except Exception:
            pass
        await context.bot.send_message(
            user_id,
            f"✅ *Verification Successful!*\n\n"
            f"Welcome to *Developer Amir Bot!*\n"
            f"🆔 Your ID: `{user_id}`\n\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"👨‍💻 *Developer:* Amir",
            reply_markup=bottom_menu_keyboard(user_id),
            parse_mode='Markdown')
    else:
        await query.answer(
            "❌ You haven't joined all channels yet! Please join all and try again.",
            show_alert=True)

async def refresh_stock_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id

    if not await verify_user_access(context.bot, user_id):
        await query.answer("❌ Access denied! Please join channels.", show_alert=True)
        return

    await query.answer("🔄 Refreshed!")
    try:
        await query.edit_message_text(
            stock_text(), reply_markup=stock_keyboard(), parse_mode='Markdown')
    except Exception:
        pass

async def select_country_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id

    if not await verify_user_access(context.bot, user_id):
        await query.answer("❌ Access denied! Please join channels.", show_alert=True)
        return

    await query.answer("⏳ Allocating your number...")

    try:
        parts = query.data.split('|', 2)
        if len(parts) < 3:
            await query.answer("❌ Invalid selection. Please try again.", show_alert=True)
            return
        country = parts[1]
        service = parts[2]
    except Exception:
        await query.answer("❌ Error parsing selection. Please try again.", show_alert=True)
        return

    stock_result = db_fetch_one(
        "SELECT stock FROM countries WHERE name = ? AND service = ? AND active = 1",
        (country, service))

    if not stock_result or stock_result[0] <= 0:
        await query.answer("❌ No numbers left for this service! Try another.", show_alert=True)
        countries = db_fetch_all(
            "SELECT name, service, stock FROM countries WHERE active = 1 AND stock > 0 ORDER BY name")
        if countries:
            try:
                await query.edit_message_text(
                    "📲 *Select a Country & Service:*\n\nChoose from the list below.",
                    reply_markup=countries_keyboard(countries),
                    parse_mode='Markdown')
            except Exception:
                pass
        else:
            try:
                await query.edit_message_text(
                    "❌ No numbers available at the moment.",
                    reply_markup=back_to_main_keyboard())
            except Exception:
                pass
        return

    num_id, number = get_random_number_from_stock(country, service)
    if not number:
        await query.answer("❌ Failed to allocate number! Please try again.", show_alert=True)
        return

    expiry = (datetime.now() + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    db_exec(
        '''INSERT INTO numbers (user_id, number, country, service, assigned_date, expiry_time)
           VALUES (?, ?, ?, ?, ?, ?)''',
        (user_id, number, country, service, now_str, expiry))

    db_exec(
        '''UPDATE users SET
           current_number = ?, current_country = ?, current_service = ?, number_expiry = ?
           WHERE user_id = ?''',
        (number, country, service, expiry, user_id))

    msg, kb = format_number_message(country, service, number)
    try:
        await query.edit_message_text(msg, reply_markup=kb, parse_mode='Markdown')
    except Exception as e:
        print(f"Error editing message: {e}")
        await context.bot.send_message(user_id, msg, reply_markup=kb, parse_mode='Markdown')

async def next_number_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id

    if not await verify_user_access(context.bot, user_id):
        await query.answer("❌ Access denied! Please join channels.", show_alert=True)
        return

    await query.answer("⏳ Getting next number...")

    result = db_fetch_one(
        "SELECT current_country, current_service FROM users WHERE user_id = ?", (user_id,))

    if not result or not result[0]:
        countries = db_fetch_all(
            "SELECT name, service, stock FROM countries WHERE active = 1 AND stock > 0 ORDER BY name")
        if countries:
            try:
                await query.edit_message_text(
                    "📲 *Select a Country & Service:*",
                    reply_markup=countries_keyboard(countries),
                    parse_mode='Markdown')
            except Exception:
                pass
        else:
            try:
                await query.edit_message_text(
                    "❌ No numbers available at the moment.",
                    reply_markup=back_to_main_keyboard())
            except Exception:
                pass
        return

    country, service = result

    stock_result = db_fetch_one(
        "SELECT stock FROM countries WHERE name = ? AND service = ? AND active = 1",
        (country, service))

    if not stock_result or stock_result[0] <= 0:
        await query.answer(f"❌ No more {country} {service} numbers!", show_alert=True)
        countries = db_fetch_all(
            "SELECT name, service, stock FROM countries WHERE active = 1 AND stock > 0 ORDER BY name")
        if countries:
            try:
                await query.edit_message_text(
                    "📲 *Select a Country & Service:*",
                    reply_markup=countries_keyboard(countries),
                    parse_mode='Markdown')
            except Exception:
                pass
        else:
            try:
                await query.edit_message_text(
                    "❌ No numbers available at the moment.",
                    reply_markup=back_to_main_keyboard())
            except Exception:
                pass
        return

    num_id, number = get_random_number_from_stock(country, service)
    if not number:
        await query.answer("❌ Failed to get number!", show_alert=True)
        return

    expiry = (datetime.now() + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    db_exec(
        '''INSERT INTO numbers (user_id, number, country, service, assigned_date, expiry_time)
           VALUES (?, ?, ?, ?, ?, ?)''',
        (user_id, number, country, service, now_str, expiry))
    db_exec(
        '''UPDATE users SET current_number = ?, current_country = ?,
           current_service = ?, number_expiry = ? WHERE user_id = ?''',
        (number, country, service, expiry, user_id))

    msg, kb = format_number_message(country, service, number)
    try:
        await query.edit_message_text(msg, reply_markup=kb, parse_mode='Markdown')
    except Exception as e:
        print(f"Error editing message: {e}")
        await context.bot.send_message(user_id, msg, reply_markup=kb, parse_mode='Markdown')

async def back_to_countries_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id

    if not await verify_user_access(context.bot, user_id):
        await query.answer("❌ Access denied! Please join channels.", show_alert=True)
        return

    await query.answer()

    db_exec(
        '''UPDATE users SET current_number = NULL, current_country = NULL,
           current_service = NULL, number_expiry = NULL WHERE user_id = ?''',
        (user_id,))

    countries = db_fetch_all(
        "SELECT name, service, stock FROM countries WHERE active = 1 AND stock > 0 ORDER BY name")
    if countries:
        try:
            await query.edit_message_text(
                "📲 *Select a Country & Service:*\n\nChoose from the list below.",
                reply_markup=countries_keyboard(countries),
                parse_mode='Markdown')
        except Exception:
            pass
    else:
        try:
            await query.edit_message_text(
                "❌ No numbers available at the moment.",
                reply_markup=back_to_main_keyboard())
        except Exception:
            pass

# ==================== /credits COMMAND ====================

async def credits_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        credits_text(), reply_markup=credits_keyboard(), parse_mode='Markdown')

# ==================== ADMIN SECTION ====================

async def enter_admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in ADMIN_IDS:
        admin_mode[user_id] = True
        admin_panel_state[user_id] = "main"
        await update.message.reply_text(
            "🛡 *ADMIN PANEL*\n\n👨‍💻 *Developer:* Amir\n\nSelect an action below:",
            reply_markup=admin_panel_keyboard(),
            parse_mode='Markdown')
    else:
        await update.message.reply_text("❌ Unauthorized access!")

async def exit_admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in admin_mode:
        admin_mode.pop(user_id, None)
        admin_panel_state.pop(user_id, None)
        first_name = update.effective_user.first_name or "User"
        await update.message.reply_text(
            "✅ Admin mode deactivated!",
            reply_markup=main_menu_keyboard(user_id))
    else:
        await update.message.reply_text("❌ You're not in admin mode!")

async def show_admin_stats(query, user_id):
    total_users = db_fetch_one("SELECT COUNT(*) FROM users")[0]
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
    active_users = db_fetch_one(
        "SELECT COUNT(*) FROM users WHERE last_active > ?", (yesterday,))[0]
    active_numbers = db_fetch_one(
        "SELECT COUNT(*) FROM numbers WHERE status = 'active'")[0]
    total_stock = db_fetch_one("SELECT SUM(stock) FROM countries")[0] or 0
    available_numbers = db_fetch_one(
        "SELECT COUNT(*) FROM available_numbers WHERE used = 0")[0]
    total_invites = db_fetch_one("SELECT SUM(invites) FROM users")[0] or 0
    active_countries = db_fetch_one(
        "SELECT COUNT(*) FROM countries WHERE active = 1")[0]
    points_needed = get_referral_points_needed()

    text = (
        "╔══════════════════════╗\n"
        "    📊 *BOT STATISTICS*  \n"
        "╚══════════════════════╝\n"
        "👨‍💻 *Developer:* Amir\n\n"
        "*👥 USERS*\n"
        f"• Total Users: `{total_users}`\n"
        f"• Active (24h): `{active_users}`\n"
        f"• Inactive: `{total_users - active_users}`\n\n"
        "*📱 NUMBERS*\n"
        f"• Active: `{active_numbers}`\n"
        f"• Total Stock: `{total_stock}`\n"
        f"• Available: `{available_numbers}`\n\n"
        "*🤝 REFERRALS*\n"
        f"• Total Invites: `{total_invites}`\n"
        f"• Points for Reward: `{points_needed}`\n\n"
        "*🌍 COUNTRIES*\n"
        f"• Active Services: `{active_countries}`\n\n"
        f"🕐 `{datetime.now().strftime('%I:%M %p | %d %b %Y')}`"
    )

    countries = db_fetch_all(
        "SELECT name, service, stock FROM countries WHERE active = 1 ORDER BY name")
    if countries:
        text += "\n\n*📦 STOCK DETAILS:*\n"
        for country in countries:
            country_info = get_country_info(country[0])
            flag = country_info.get("flag", "🏁")
            stock_bar = "🟢" if country[2] > 0 else "🔴"
            text += f"{stock_bar} {flag} {country[0]} — {country[1]}: `{country[2]}`\n"

    try:
        await query.edit_message_text(text, reply_markup=admin_back_button(), parse_mode='Markdown')
    except Exception:
        pass

async def show_delete_options(query, user_id):
    countries = db_fetch_all(
        "SELECT name, service, stock FROM countries WHERE active = 1 ORDER BY name")

    if not countries:
        try:
            await query.edit_message_text(
                "❌ No countries to delete!", reply_markup=admin_back_button())
        except Exception:
            pass
        return

    rows = []
    for country in countries:
        country_info = get_country_info(country[0])
        flag = country_info.get("flag", "🏁")
        btn_text = f"🗑 {flag} {country[0]} — {country[1]} (Stock: {country[2]})"
        cb_data = f"admin_del|{country[0]}|{country[1]}"
        rows.append([InlineKeyboardButton(btn_text, callback_data=cb_data, style=KBS.DANGER)])
    rows.append([InlineKeyboardButton("🔙 Back to Admin Panel", callback_data="admin_back", style=KBS.PRIMARY)])

    try:
        await query.edit_message_text(
            "*🗑 DELETE STOCK*\n\nSelect a country/service to delete all its numbers:",
            reply_markup=InlineKeyboardMarkup(rows),
            parse_mode='Markdown')
    except Exception:
        pass

async def show_referrals_admin(query, user_id):
    qualified_users = db_fetch_all(
        '''SELECT user_id, username, first_name, invites, free_accounts
           FROM users WHERE invites > 0 ORDER BY invites DESC LIMIT 20''')

    text = "*🎁 TOP REFERRALS*\n\n"
    if qualified_users:
        for idx, user in enumerate(qualified_users, 1):
            username = user[1] or f"User_{user[0]}"
            text += f"{idx}. `{user[0]}` | @{username}\n"
            text += f"   Invites: `{user[3]}` | Free Accounts: `{user[4]}`\n\n"
    else:
        text += "No users with invites yet."

    try:
        await query.edit_message_text(text, reply_markup=admin_back_button(), parse_mode='Markdown')
    except Exception:
        pass

async def show_settings_panel(query, user_id):
    points_needed = get_referral_points_needed()
    text = (
        "⚙️ *SETTINGS*\n\n"
        "*Referral System Configuration:*\n"
        f"• Current setting: `{points_needed}` invites = 1 free account\n\n"
        "*Choose a new value:*"
    )
    try:
        await query.edit_message_text(
            text, reply_markup=settings_keyboard(), parse_mode='Markdown')
    except Exception:
        pass

async def show_total_users(query, user_id):
    count = db_fetch_one("SELECT COUNT(*) FROM users")[0]
    text = f"👤 *Total Bot Users:* `{count}`\n\n🕐 `{datetime.now().strftime('%I:%M %p | %d %b %Y')}`"
    try:
        await query.edit_message_text(text, reply_markup=admin_back_button(), parse_mode='Markdown')
    except Exception:
        pass

async def show_countries_admin(query, user_id):
    countries = db_fetch_all("SELECT name, service, stock, active FROM countries ORDER BY name")
    text = "*📋 ALL COUNTRIES & SERVICES*\n\n"
    if not countries:
        text += "No countries configured yet."
    for country in countries:
        country_info = get_country_info(country[0])
        flag = country_info.get("flag", "🏁")
        status = "✅ Active" if country[3] else "❌ Inactive"
        text += f"• {flag} *{country[0]}* — {country[1]}: `{country[2]}` ({status})\n"
    try:
        await query.edit_message_text(text, reply_markup=admin_back_button(), parse_mode='Markdown')
    except Exception:
        pass

async def request_upload(query, user_id):
    admin_panel_state[user_id] = "waiting_file"
    text = (
        "*📤 UPLOAD STOCK*\n\n"
        "Send a `.txt` file with phone numbers.\n\n"
        "*File Format Requirements:*\n"
        "• Filename must contain country name (from countries.json)\n"
        "• Filename must contain service name\n"
        "• One number per line\n\n"
        "*Filename Examples:*\n"
        "• `pakistan_whatsapp.txt`\n"
        "• `india_telegram.txt`\n"
        "• `venezuela_imo.txt`\n\n"
        "*Supported Services:* WhatsApp, Telegram, Facebook, IMO\n"
        "*Note:* Numbers without `+` prefix are fixed automatically."
    )
    try:
        await query.edit_message_text(
            text, reply_markup=admin_cancel_keyboard(), parse_mode='Markdown')
    except Exception:
        pass

async def request_broadcast(query, user_id):
    admin_panel_state[user_id] = "waiting_broadcast"
    try:
        await query.edit_message_text(
            "*📢 BROADCAST MESSAGE*\n\n"
            "Send the message you want to broadcast to ALL users.\n"
            "Supports Markdown formatting.",
            reply_markup=admin_cancel_keyboard(),
            parse_mode='Markdown')
    except Exception:
        pass

async def request_giveaway(query, user_id):
    admin_panel_state[user_id] = "waiting_giveaway"
    try:
        await query.edit_message_text(
            "*👥 GIVE FREE ACCOUNT*\n\n"
            "Send: `user_id count`\n"
            "Example: `123456789 5`\n\n"
            "This will give the user the specified number of free accounts.",
            reply_markup=admin_cancel_keyboard(),
            parse_mode='Markdown')
    except Exception:
        pass

async def exit_admin_callback_query(query, user_id, bot):
    admin_mode.pop(user_id, None)
    admin_panel_state.pop(user_id, None)
    first_name = query.from_user.first_name or "User"
    try:
        await query.edit_message_text(
            welcome_text(user_id, first_name),
            reply_markup=main_menu_keyboard(user_id),
            parse_mode='Markdown')
    except Exception:
        await bot.send_message(
            user_id, "🏠 Returned to main menu.",
            reply_markup=main_menu_keyboard(user_id))

async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id

    # Auto-elevate to admin if user is admin
    if user_id in ADMIN_IDS and user_id not in admin_mode:
        admin_mode[user_id] = True
        admin_panel_state[user_id] = "main"

    if user_id not in admin_mode:
        await query.answer("❌ Admin mode required! Use the Admin Panel button.", show_alert=True)
        return

    await query.answer()
    data = query.data

    if data.startswith("admin_del|"):
        parts = data.split('|', 2)
        if len(parts) == 3:
            country = parts[1]
            service = parts[2]
            if delete_country_stock(country, service):
                await query.answer(f"✅ {country} — {service} deleted successfully!")
            else:
                await query.answer(f"❌ Error deleting {country} — {service}!", show_alert=True)
            await show_delete_options(query, user_id)
        return

    action = data[len("admin_"):]

    if action == "stats":
        await show_admin_stats(query, user_id)
    elif action == "upload":
        await request_upload(query, user_id)
    elif action == "delete":
        await show_delete_options(query, user_id)
    elif action == "referrals":
        await show_referrals_admin(query, user_id)
    elif action == "broadcast":
        await request_broadcast(query, user_id)
    elif action == "giveaway":
        await request_giveaway(query, user_id)
    elif action == "countries":
        await show_countries_admin(query, user_id)
    elif action == "settings":
        await show_settings_panel(query, user_id)
    elif action == "total_users":
        await show_total_users(query, user_id)
    elif action == "exit":
        await exit_admin_callback_query(query, user_id, context.bot)
    elif action == "back":
        admin_panel_state[user_id] = "main"
        try:
            await query.edit_message_text(
                "🛡 *ADMIN PANEL*\n\n👨‍💻 *Developer:* Amir\n\nSelect an action below:",
                reply_markup=admin_panel_keyboard(),
                parse_mode='Markdown')
        except Exception:
            pass
    elif action.startswith("set_referral_"):
        value = action[len("set_referral_"):]
        if value == "custom":
            admin_panel_state[user_id] = "waiting_referral_value"
            try:
                await query.edit_message_text(
                    "✏️ *Custom Referral Value*\n\n"
                    "Enter the number of invites needed to earn 1 free account:\n"
                    "_(Must be a positive number)_",
                    reply_markup=admin_cancel_keyboard(),
                    parse_mode='Markdown')
            except Exception:
                pass
        else:
            try:
                points = int(value)
                update_referral_points(points)
                await query.answer(f"✅ Referral points set to {points}")
                await show_settings_panel(query, user_id)
            except ValueError:
                await query.answer("❌ Invalid value!", show_alert=True)

# ==================== MESSAGE HANDLERS FOR ADMIN STATES ====================

async def handle_admin_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    state = admin_panel_state.get(user_id)

    if user_id not in admin_mode:
        return False

    if state == "waiting_referral_value":
        try:
            points = int(update.message.text.strip())
            if points < 1:
                await update.message.reply_text("❌ Value must be at least 1!")
                return True
            update_referral_points(points)
            admin_panel_state[user_id] = "main"
            await update.message.reply_text(
                f"✅ Referral points updated to *{points}* invites per free account!",
                parse_mode='Markdown')
            await update.message.reply_text(
                "🛡 *ADMIN PANEL*\n\n👨‍💻 *Developer:* Amir",
                reply_markup=admin_panel_keyboard(),
                parse_mode='Markdown')
        except ValueError:
            await update.message.reply_text("❌ Please enter a valid number!")
        return True

    elif state == "waiting_broadcast":
        users = db_fetch_all("SELECT user_id FROM users")
        sent_count = 0
        failed_count = 0
        for user in users:
            try:
                await context.bot.send_message(
                    user[0], update.message.text, parse_mode='Markdown')
                sent_count += 1
                await asyncio.sleep(0.05)
            except Exception:
                failed_count += 1
                continue
        admin_panel_state[user_id] = "main"
        await update.message.reply_text(
            f"✅ *Broadcast Complete!*\n\n"
            f"✔️ Sent: `{sent_count}`\n"
            f"❌ Failed: `{failed_count}`",
            parse_mode='Markdown')
        await update.message.reply_text(
            "🛡 *ADMIN PANEL*\n\n👨‍💻 *Developer:* Amir",
            reply_markup=admin_panel_keyboard(),
            parse_mode='Markdown')
        return True

    elif state == "waiting_giveaway":
        try:
            parts = update.message.text.strip().split()
            target_id = int(parts[0])
            count = int(parts[1]) if len(parts) > 1 else 1

            existing = db_fetch_one("SELECT user_id FROM users WHERE user_id = ?", (target_id,))
            if not existing:
                await update.message.reply_text(
                    "❌ User not found in database!\n"
                    "The user must have started the bot at least once.")
                return True

            db_exec(
                "UPDATE users SET free_accounts = free_accounts + ? WHERE user_id = ?",
                (count, target_id))

            try:
                await context.bot.send_message(
                    target_id,
                    f"🎁 *You received {count} free account(s) from admin!*\n\n"
                    f"Enjoy your premium virtual numbers!",
                    parse_mode='Markdown')
            except Exception:
                pass

            admin_panel_state[user_id] = "main"
            await update.message.reply_text(
                f"✅ Successfully given *{count}* free account(s) to user `{target_id}`",
                parse_mode='Markdown')
            await update.message.reply_text(
                "🛡 *ADMIN PANEL*\n\n👨‍💻 *Developer:* Amir",
                reply_markup=admin_panel_keyboard(),
                parse_mode='Markdown')
        except (ValueError, IndexError):
            await update.message.reply_text(
                "❌ Invalid format!\n\n"
                "Usage: `user_id count`\n"
                "Example: `123456789 5`",
                parse_mode='Markdown')
        return True

    return False

# ==================== DOCUMENT/FILE HANDLER ====================

async def handle_file_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if user_id not in admin_mode or admin_panel_state.get(user_id) != "waiting_file":
        return

    try:
        document = update.message.document
        file_name = document.file_name

        if not file_name.endswith('.txt'):
            await update.message.reply_text(
                "❌ Please upload a `.txt` file!\n\nOnly .txt files are supported.",
                parse_mode='Markdown')
            return

        file = await context.bot.get_file(document.file_id)
        os.makedirs("uploads", exist_ok=True)
        file_path = f"uploads/{file_name}"
        await file.download_to_drive(file_path)

        count, result_msg = load_numbers_from_file(file_path, file_name)

        if count > 0:
            country = extract_country_from_filename(file_name)
            service = extract_service_from_filename(file_name)
            if country:
                country_info = get_country_info(country)
                flag = country_info.get("flag", "🏁")
                await notify_users_about_new_numbers(
                    context.bot, country, service, flag, count)

        admin_panel_state[user_id] = "main"
        await update.message.reply_text(
            result_msg,
            reply_markup=admin_back_button(),
            parse_mode='Markdown')

    except Exception as e:
        print(f"File upload error: {e}")
        await update.message.reply_text(
            f"❌ Error processing file: `{str(e)}`",
            parse_mode='Markdown')
        admin_panel_state[user_id] = "main"

# ==================== BOTTOM MENU TEXT ROUTERS ====================

async def send_get_number_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    db_exec("UPDATE users SET last_active = ? WHERE user_id = ?",
            (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), user_id))

    number, country, service, expiry = get_user_current_number(user_id)
    if number:
        msg, kb = format_number_message(country, service, number)
        await update.message.reply_text(
            f"📱 *You already have an active number:*\n\n{msg}",
            reply_markup=kb, parse_mode='Markdown')
        return

    countries = db_fetch_all(
        "SELECT name, service, stock FROM countries WHERE active = 1 AND stock > 0 ORDER BY name")
    if not countries:
        await update.message.reply_text(
            "❌ *No numbers available at the moment.*",
            reply_markup=back_to_main_keyboard(), parse_mode='Markdown')
        return

    await update.message.reply_text(
        "📲 *Select a Country & Service:*\n\nChoose from the list below to get your virtual number.",
        reply_markup=countries_keyboard(countries), parse_mode='Markdown')

async def send_live_stock_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        stock_text(), reply_markup=stock_keyboard(), parse_mode='Markdown')

async def send_invite_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    result = db_fetch_one(
        "SELECT invites, free_accounts FROM users WHERE user_id = ?", (user_id,))
    invites = result[0] if result else 0
    free_accounts = result[1] if result else 0
    points_needed = get_referral_points_needed()
    bot_me = await context.bot.get_me()
    invite_link = f"https://t.me/{bot_me.username}?start={user_id}"
    remaining = points_needed - (invites % points_needed) if invites % points_needed != 0 else 0

    text = (
        "👥 *INVITE & EARN SYSTEM*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📊 *Your Invites:* `{invites}`\n"
        f"🎁 *Free Accounts Earned:* `{free_accounts}`\n"
        f"🎯 *Invites to next reward:* `{remaining}`\n\n"
        f"🔗 *Your Invite Link:*\n`{invite_link}`\n\n"
        f"💡 *{points_needed} Invites = 1 Free Account!*\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "👨‍💻 *Developer:* Amir"
    )
    await update.message.reply_text(
        text, reply_markup=invite_keyboard(invite_link),
        parse_mode='Markdown', disable_web_page_preview=True)

async def send_support_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎧 *CONTACT SUPPORT*\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "For any issues, questions, or requests — contact admin directly.\n\n"
        "👨‍💻 *Developer:* Amir",
        reply_markup=support_keyboard(), parse_mode='Markdown')

async def send_admin_panel_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ Unauthorized!")
        return
    admin_mode[user_id] = True
    admin_panel_state[user_id] = "main"
    await update.message.reply_text(
        "🛡 *ADMIN PANEL*\n\n👨‍💻 *Developer:* Amir\n\nSelect an action below:",
        reply_markup=admin_panel_keyboard(), parse_mode='Markdown')

# ==================== GENERIC TEXT HANDLER ====================

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    # Admin state input (broadcast/giveaway/custom value) takes priority
    handled = await handle_admin_text(update, context)
    if handled:
        return

    user_id = update.effective_user.id
    text = update.message.text.strip()

    # Bottom menu buttons require join verification (admin auto-passes)
    if text in (BTN_GET_NUMBER, BTN_LIVE_STOCK, BTN_INVITE, BTN_SUPPORT, BTN_ADMIN):
        if not await verify_user_access(context.bot, user_id):
            await send_join_required(context.bot, user_id)
            return

    if text == BTN_GET_NUMBER:
        await send_get_number_panel(update, context)
    elif text == BTN_LIVE_STOCK:
        await send_live_stock_panel(update, context)
    elif text == BTN_INVITE:
        await send_invite_panel(update, context)
    elif text == BTN_SUPPORT:
        await send_support_panel(update, context)
    elif text == BTN_ADMIN:
        await send_admin_panel_msg(update, context)

# ==================== ERROR HANDLER ====================

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    print(f"Update caused error: {context.error}")

# ==================== MAIN ====================

def main():
    print("🔥 Developer Amir Bot STARTING...")
    print("👨‍💻 Developer: Amir")

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    # Command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("credits", credits_command))
    application.add_handler(CommandHandler("enteradmin", enter_admin_command))
    application.add_handler(CommandHandler("exitadmin", exit_admin_command))

    # Callback query handlers — order matters (more specific patterns first)
    application.add_handler(
        CallbackQueryHandler(check_joined_callback, pattern="^check_joined$"))
    application.add_handler(
        CallbackQueryHandler(refresh_stock_callback, pattern="^refresh_stock$"))
    application.add_handler(
        CallbackQueryHandler(select_country_callback, pattern=r"^sel\|"))
    application.add_handler(
        CallbackQueryHandler(next_number_callback, pattern="^next_number$"))
    application.add_handler(
        CallbackQueryHandler(back_to_countries_callback, pattern="^back_to_countries$"))
    application.add_handler(
        CallbackQueryHandler(back_to_menu_callback, pattern="^back_to_menu$"))
    application.add_handler(
        CallbackQueryHandler(menu_callback, pattern="^menu_"))
    application.add_handler(
        CallbackQueryHandler(admin_callback, pattern=r"^admin_del\|"))
    application.add_handler(
        CallbackQueryHandler(admin_callback, pattern="^admin_"))

    # Message handlers
    application.add_handler(MessageHandler(filters.Document.ALL, handle_file_upload))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    # Error handler
    application.add_error_handler(error_handler)

    # Job queue
    job_queue = application.job_queue
    if job_queue:
        job_queue.run_repeating(monitor_otp_job, interval=5, first=5)
        job_queue.run_repeating(cleanup_expired_job, interval=60, first=60)

    print(f"✅ Admin IDs: {ADMIN_IDS}")
    print(f"✅ Referral Points Needed: {get_referral_points_needed()}")
    print(f"✅ Loaded {len(COUNTRIES_DATA)} countries from JSON file")
    print("✅ Join Check Active")
    print("✅ Premium Inline UI — All Buttons Colored")
    print("🔄 Starting polling...")

    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
