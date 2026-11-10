import telebot
from telebot import types
import sqlite3
import random
import os
import json
from datetime import datetime
import logging
import hmac
import hashlib
import time
import urllib.parse
import threading
from flask import Flask, request, jsonify, send_from_directory
from waitress import serve

logging.basicConfig(level=logging.INFO)

# ================== تنظیمات ==================
TOKEN = os.getenv("BOT_TOKEN", "").strip()
if not TOKEN:
    raise RuntimeError("متغیر BOT_TOKEN در Railway تنظیم نشده است")
ADMIN_IDS = [int(x.strip()) for x in os.getenv("ADMIN_IDS", "9158813748").split(",") if x.strip().isdigit()]
CONFIG_IMAGE_PATH = "photo_5771850719550967090_y.jpg"
YOUR_PRIVATE_ID = int(os.getenv("OWNER_CHAT_ID", "9158813748"))
MINI_APP_URL = os.getenv("MINI_APP_URL", "").strip().rstrip("/")

bot = telebot.TeleBot(TOKEN, parse_mode="HTML")

# ================== دیتابیس ==================
DATABASE_PATH = os.getenv("DATABASE_PATH", "sales.db")
os.makedirs(os.path.dirname(DATABASE_PATH) or ".", exist_ok=True)
conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
cur = conn.cursor()
cur.execute("""
CREATE TABLE IF NOT EXISTS invoices (
    invoice TEXT PRIMARY KEY,
    user_id INTEGER,
    amount INTEGER,
    status TEXT,
    receipt_sent INTEGER,
    wait_message_id INTEGER,
    created_at TEXT,
    service TEXT,
    receipt_file_id TEXT,
    sent_to_owner INTEGER DEFAULT 0
)
""")
conn.commit()

# ================== محصولات و کاربران ==================
cur.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    first_name TEXT,
    username TEXT,
    created_at TEXT
)
""")
cur.execute("""
CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    service TEXT NOT NULL,
    title TEXT NOT NULL,
    price INTEGER NOT NULL,
    icon TEXT DEFAULT "🛍️",
    sticker_file_id TEXT,
    active INTEGER DEFAULT 1,
    stock INTEGER DEFAULT -1
)
""")
conn.commit()
# سازگاری با دیتابیس‌های قدیمی
try:
    cur.execute("ALTER TABLE products ADD COLUMN stock INTEGER DEFAULT -1")
    conn.commit()
except sqlite3.OperationalError:
    pass
cur.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
cur.execute("CREATE TABLE IF NOT EXISTS coupons (code TEXT PRIMARY KEY, discount_percent INTEGER NOT NULL, active INTEGER DEFAULT 1)")
for _key, _value in (("card_number", "6219861857908213"), ("card_owner", "ایمان اعظمی")):
    cur.execute("INSERT OR IGNORE INTO settings(key,value) VALUES (?,?)", (_key, _value))
conn.commit()

DEFAULT_PRODUCTS = [
    ("config", "🥇 ویژه | 1 ماه", 99000, "🥇"),
    ("config", "🥇 ویژه | 3 ماه", 199000, "🥇"),
    ("config", "🥇 ویژه | 6 ماه", 299000, "🥇"),
    ("premium", "💎 پرمیوم | 1 ماهه", 850000, "💎"),
    ("premium", "💎 پرمیوم | 3 ماهه", 2250000, "💎"),
    ("premium", "💎 پرمیوم | 6 ماهه", 2900000, "💎"),
    ("premium", "💎 پرمیوم | 12 ماهه", 5200000, "💎"),
    ("self", "🤖 فعالسازی با آیدی", 120000, "🤖"),
    ("self", "🤖 فعالسازی با ورود به حساب", 95000, "🤖"),
    ("virtual", "🥇 کشور فیجی", 300000, "🥇"),
    ("virtual", "🥈 کشور آمریکا", 95000, "🥈"),
    ("stars", "⭐️ 50 استارز", 180000, "⭐️"),
    ("stars", "⭐️ 75 استارز", 240000, "⭐️"),
    ("stars", "⭐️ 100 استارز", 320000, "⭐️"),
    ("stars", "⭐️ 150 استارز", 455000, "⭐️"),
    ("stars", "⭐️ 250 استارز", 770000, "⭐️"),
    ("stars", "⭐️ 500 استارز", 1500000, "⭐️"),
    ("gift_15", "🎁 گیفت 15 ⭐", 45000, "🌹"),
    ("gift_25", "🎁 گیفت 25 ⭐", 72000, "🌷"),
    ("gift_50", "🎁 گیفت 50 ⭐", 145000, "🌸"),
    ("gift_100", "🎁 گیفت 100 ⭐", 290000, "💐"),
]
if cur.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 0:
    cur.executemany(
        "INSERT INTO products(service,title,price,icon) VALUES (?,?,?,?)",
        DEFAULT_PRODUCTS
    )
    conn.commit()

ADMIN_STATE = {}

def register_user(user):
    try:
        cur.execute(
            "INSERT OR REPLACE INTO users(user_id,first_name,username,created_at) VALUES (?,?,?,COALESCE((SELECT created_at FROM users WHERE user_id=?),?))",
            (user.id, user.first_name or "", user.username or "", user.id, datetime.now().isoformat())
        )
        conn.commit()
    except Exception as e:
        logging.error("ثبت کاربر: %s", e)

def service_title(service):
    return {
        "config": "🔥 کانفیگ اختصاصی",
        "premium": "💎 پرمیوم",
        "self": "🤖 سلف و تبچی",
        "virtual": "♻️ شماره مجازی",
        "stars": "💫 استارز",
        "gift": "🎁 گیفت استارزی",
        "gift_15": "🎁 گیفت استارزی",
        "gift_25": "🎁 گیفت استارزی",
        "gift_50": "🎁 گیفت استارزی",
        "gift_100": "🎁 گیفت استارزی",
    }.get(service, service)

def product_keyboard(service):
    rows = []
    products = cur.execute(
        "SELECT id,title,price,icon FROM products WHERE service=? AND active=1 ORDER BY id",
        (service,)
    ).fetchall()
    for pid, title, price, icon in products:
        rows.append([_button(
            "{} {} | {:,} تومان".format(icon or "🛍️", title, price),
            callback_data="prod_{}".format(pid), style="success"
        )])
    return _inline_keyboard(rows)

def show_products(chat_id, service):
    if service == "config":
        bot.send_message(chat_id, get_setting("config_text", CONFIG_TEXT))
    products = cur.execute(
        "SELECT id FROM products WHERE service=? AND active=1 LIMIT 1", (service,)
    ).fetchone()
    if not products:
        bot.send_message(chat_id, "❌ فعلاً محصولی برای این بخش ثبت نشده است.")
        return
    bot.send_message(
        chat_id,
        "لطفاً سرویس مورد نظر را انتخاب کنید ⚡️👇\n\n<b>{}</b>".format(service_title(service)),
        reply_markup=product_keyboard(service)
    )

# تنظیمات قابل ویرایش پنل

def get_setting(key, default=""):
    row = cur.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row[0] if row else default

def set_setting(key, value):
    cur.execute("INSERT INTO settings(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))
    conn.commit()

def admin_keyboard():
    # پنل مدیریت: سبز؛ عملیات مخرب/ریستور در زیرمنوها قرمز مشخص می‌شود.
    labels = [
        ("🛍 مدیریت محصولات", "adm_products"), ("➕ افزودن محصول", "adm_add"),
        ("📢 پیام همگانی", "adm_broadcast"), ("📊 آمار کاربران", "adm_stats"),
        ("👥 فهرست کاربران", "adm_users"), ("💳 تنظیمات کارت", "adm_card"),
        ("🎟 کد تخفیف", "adm_coupon"), ("💾 بکاپ دیتابیس", "adm_backup"),
        ("♻️ ریستور دیتابیس", "adm_restore"), ("✏️ ویرایش متن‌ها", "adm_texts"),
    ]
    buttons = [_button(label, callback_data=data, style="success") for label, data in labels]
    return _inline_keyboard([buttons[i:i+2] for i in range(0, len(buttons), 2)])

# ================== ارسال خودکار به شما ==================
def send_receipt_to_owner_automatically(file_id, invoice, user_id, amount, service):
    try:
        user_info = ""
        try:
            user_chat = bot.get_chat(user_id)
            first = user_chat.first_name or ""
            last = user_chat.last_name or ""
            username = user_chat.username
            
            user_info = (first + " " + last).strip()
            if username:
                user_info += " (@{})".format(username)
        except:
            user_info = "ID: {}".format(user_id)
        
        now = datetime.now()
        date_time = now.strftime("%Y/%m/%d %H:%M")
        date = now.strftime("%Y/%m/%d")
        time = now.strftime("%H:%M")
        
        amount_toman = amount
        
        service_names = {
            "config": "کانفیگ اختصاصی",
            "premium": "پرمیوم",
            "self": "سلف و تبچی",
            "virtual": "شماره مجازی",
            "stars": "استارز",
            "gift": "گیفت استارزی",
            "gift_15": "گیفت 15 ستاره",
            "gift_25": "گیفت 25 ستاره",
            "gift_50": "گیفت 50 ستاره",
            "gift_100": "گیفت 100 ستاره"
        }
        
        service_fa = service_names.get(service, service)
        
        caption = (
            "📋 <b>رسید تایید شده</b>\n"
            "⏰ {}\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "💳 <b>فاکتور:</b> {}\n"
            "👤 <b>خریدار:</b> {}\n"
            "🆔 <b>آیدی:</b> {}\n"
            "💰 <b>مبلغ:</b> {:,} تومان\n"
            "📦 <b>سرویس:</b> {}\n"
            "📅 <b>تاریخ:</b> {}\n"
            "🕐 <b>ساعت:</b> {}\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "✅ ارسال خودکار"
        ).format(date_time, invoice, user_info, user_id, amount_toman, service_fa, date, time)
        
        bot.send_photo(YOUR_PRIVATE_ID, file_id, caption=caption)
        logging.info("✅ رسید {} به مالک ارسال شد".format(invoice))
        return True
        
    except Exception as e:
        logging.error("❌ خطا در ارسال خودکار: {}".format(e))
        
        try:
            bot.send_message(
                YOUR_PRIVATE_ID,
                "📋 <b>رسید تایید شده</b>\n"
                "⏰ {}\n"
                "━━━━━━━━━━━━━━━━\n"
                "💳 فاکتور: {}\n"
                "👤 کاربر: {}\n"
                "💰 مبلغ: {:,} تومان\n"
                "📦 سرویس: {}\n"
                "⚠️ ارسال عکس با خطا مواجه شد".format(
                    datetime.now().strftime('%Y/%m/%d %H:%M'),
                    invoice, user_id, amount//10, service
                )
            )
            return True
        except Exception as e2:
            logging.error("❌ خطا در ارسال متن: {}".format(e2))
            return False

# ================== کیبوردها و رنگ دکمه‌ها (Telegram Bot API 9.4+) ==================
# برای سازگاری با نسخه‌های قدیمی pyTelegramBotAPI، استایل‌ها به شکل دیکشنری خام
# به Bot API فرستاده می‌شوند؛ رنگ‌ها توسط کلاینت‌های جدید تلگرام نمایش داده می‌شوند.
def _button(text, callback_data=None, url=None, style=None):
    item = {"text": text}
    if callback_data is not None:
        item["callback_data"] = callback_data
    if url is not None:
        item["url"] = url
    if style in ("primary", "success", "danger"):
        item["style"] = style
    return item

def _inline_keyboard(rows):
    # pyTelegramBotAPI 4.26 expects reply_markup as a JSON string or
    # JsonSerializable object; passing a raw dict is form-encoded with
    # Python single quotes and Telegram rejects it (400 Bad Request).
    return json.dumps({"inline_keyboard": rows}, ensure_ascii=False)

def main_keyboard():
    # منوی خدمات به‌صورت کیبورد اصلی تلگرام (ReplyKeyboard) زیر پیام خوش‌آمد نمایش داده می‌شود.
    # رنگ پس‌زمینه ReplyKeyboardButton را خود تلگرام/تم کاربر تعیین می‌کند.
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2, one_time_keyboard=False)
    if MINI_APP_URL:
        kb.row(types.KeyboardButton("🛍️ ورود به فروشگاه", web_app=types.WebAppInfo(url=MINI_APP_URL)))
    kb.row("🤖 سلف و تبچی")
    kb.row("♻️ شماره مجازی", "🎁 گیفت استارزی")
    kb.row("🔥 کانفیگ اختصاصی", "💎 پرمیوم")
    kb.row("💫 استازر", "☎️ پشتیبانی")
    return kb

invoice_keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
invoice_keyboard.add("لغو", "منوی اصلی")

# کیبوردهای انتخاب محصول برای مشتری با رنگ آبی (primary)
plan_keyboard = _inline_keyboard([
    [_button("🥇 ویژه | 1 ماه | 99.000 تومان", callback_data="plan_99000_config", style="success")],
    [_button("🥇 ویژه | 3 ماه | 199.000 تومان", callback_data="plan_199000_config", style="success")],
    [_button("🥇 ویژه | 6 ماه | 299.000 تومان", callback_data="plan_299000_config", style="success")],
])
premium_keyboard = _inline_keyboard([
    [_button("💎 پرمیوم | 1 ماهه | 850,000 تومان", callback_data="plan_850000_premium", style="success")],
    [_button("💎 پرمیوم | 3 ماهه | 2,250,000 تومان", callback_data="plan_2250000_premium", style="success")],
    [_button("💎 پرمیوم | 6 ماهه | 2,900,000 تومان", callback_data="plan_2900000_premium", style="success")],
    [_button("💎 پرمیوم | 12 ماهه | 5,200,000 تومان", callback_data="plan_5200000_premium", style="success")],
])
self_keyboard = _inline_keyboard([
    [_button("🤖 فعالسازی با آیدی | 120,000 تومان", callback_data="plan_120000_self", style="success")],
    [_button("🤖 فعالسازی با ورود به حساب | 95,000 تومان", callback_data="plan_95000_self", style="success")],
])
virtual_keyboard = _inline_keyboard([
    [_button("🥇 کشور فیجی | 300,000 تومان", callback_data="plan_300000_virtual", style="success")],
    [_button("🥈 کشور آمریکا | 95,000 تومان", callback_data="plan_95000_virtual", style="success")],
])
stars_keyboard = _inline_keyboard([
    [_button("⭐️ 50 استارز | 180,000 تومان", callback_data="plan_180000_stars", style="success")],
    [_button("⭐️ 75 استارز | 240,000 تومان", callback_data="plan_240000_stars", style="success")],
    [_button("⭐️ 100 استارز | 320,000 تومان", callback_data="plan_320000_stars", style="success")],
    [_button("⭐️ 150 استارز | 455,000 تومان", callback_data="plan_455000_stars", style="success")],
    [_button("⭐️ 250 استارز | 770,000 تومان", callback_data="plan_770000_stars", style="success")],
    [_button("⭐️ 500 استارز | 1,500,000 تومان", callback_data="plan_1500000_stars", style="success")],
])
gift_stars_keyboard = _inline_keyboard([
    [_button("🌹", callback_data="plan_45000_gift_15", style="success"), _button("45,000 تومان", callback_data="plan_45000_gift_15", style="success"), _button("15 ⭐", callback_data="plan_45000_gift_15", style="success")],
    [_button("🌷", callback_data="plan_72000_gift_15", style="success"), _button("72,000 تومان", callback_data="plan_72000_gift_15", style="success"), _button("15 ⭐", callback_data="plan_72000_gift_15", style="success")],
    [_button("🌸", callback_data="plan_145000_gift_25", style="success"), _button("145,000 تومان", callback_data="plan_145000_gift_25", style="success"), _button("25 ⭐", callback_data="plan_145000_gift_25", style="success")],
    [_button("💐", callback_data="plan_145000_gift_50", style="success"), _button("145,000 تومان", callback_data="plan_145000_gift_50", style="success"), _button("50 ⭐", callback_data="plan_145000_gift_50", style="success")],
    [_button("🌺", callback_data="plan_290000_gift_100", style="success"), _button("290,000 تومان", callback_data="plan_290000_gift_100", style="success"), _button("100 ⭐", callback_data="plan_290000_gift_100", style="success")],
])
support_keyboard = _inline_keyboard([
    [_button("👩🏻‍💻 پیام به پشتیبانی", url="https://t.me/MDF_1819", style="success")]
])

# ================== متن‌ها ==================
CONFIG_TEXT = get_setting("config_text", "فیلترشکن ویژه زئوس شاپ:\n\nبروزرسانی و اتصال در اینترنت ملی\nسرور های مجزا با لوکیشن های مختلف\nسرعت و پایداری بیشتر\nحذف تبلیغات یوتیوب, ساندکلاد و باقی پلتفرم ها\nبدون محدودیت حجم\nدو کاربر همزمان\nبروزرسانی روزانه + پشتیبانی\n\n👇 مدت زمان سرویس را انتخاب کنید\n")

SUPPORT_TEXT = (
    "📯 <b>نکات مهم در مورد پیام دادن به پشتیبانی :</b>\n\n"
    "🔻1. موقع پیام دادن مشکل خودتون رو به صورت <b>فارسی</b> تایپ کنید "
    "(انگلیسی یا ویس نفرستید)\n\n"
    "🔻2. حتما اسم اینترنت، سیستم عامل (اندروید، آیفون، ویندوز) "
    "و برنامه‌ای که ازش استفاده می‌کنید رو بگید\n\n"
    "🔻3. ترتیب پاسخگویی از پیام‌های قدیمی‌تر به جدید هست، "
    "پس ارسال پیام جدید نوبت شما رو عقب می‌اندازه\n\n"
    "⚠️ لطفا قبل از پیام دادن این موارد رو رعایت کنید تا مشکل شما "
    "سریع و کامل برطرف شود.\n\n"
    "👩🏻‍💻 <b>پشتیبانی سبز نت</b> = @MDF_1819\n\n"
    "@ir_Zeus Shop | کانال اطلاع رسانی\n"
)

HELP_TEXT = (
    "جهت دریافت راهنمایی و سرویس به مشکل خورده به پشتیبانی پیام دهید!\n\n"
    "⚠️ : لطفاً از پیام بی مورد خوداری کنید و صبور باشید.\n\n"
    "با زئوس شاپ، بهترین کیفیت اتصال به اینترنت جهانی را تجربه کن! 🌐\n"
    "@ir_Zeus Shop\n"
)

TEST_TEXT = (
    "در حال حاضر سرویس تست غیرفعال\n\n"
    "به خاطر شرایط فعلی و محدودیت های شدید اینترنت\n"
    "موقتا امکان اراعه تست وجود ندارد\n"
)

CONFIG_MESSAGE = (
    "🔗 لینک اشتراک شما:\n\n"
    "https://sublink.click/sub/MzE40v9pTWFOXzY5NDVfNzA3MCwxNzcwNjUwNzE10jIICDZDak\n\n"
    "با زئوس شاپ، بهترین کیفیت اتصال به اینترنت جهانی را تجربه کن! 🌐\n\n"
    "⚠️ توجه این سرویس دوکاربره می‌باشد!\n\n"
    "@ir_Zeus Shop\n"
)

# متن‌های قابل ویرایش از پنل مدیریت (با حفظ مقدار پیش‌فرض نسخه قدیمی)
SUPPORT_TEXT = get_setting("support_text", SUPPORT_TEXT)
HELP_TEXT = get_setting("help_text", HELP_TEXT)
TEST_TEXT = get_setting("test_text", TEST_TEXT)
CONFIG_MESSAGE = get_setting("config_message", CONFIG_MESSAGE)

# ================== ارسال کانفیگ ==================
def send_config_safe(user_id):
    if os.path.exists(CONFIG_IMAGE_PATH):
        try:
            with open(CONFIG_IMAGE_PATH, "rb") as f:
                bot.send_photo(user_id, f, caption=CONFIG_MESSAGE, timeout=20)
            logging.info("کانفیگ تصویری با موفقیت به {} ارسال شد".format(user_id))
            return
        except Exception as e:
            logging.warning("ارسال عکس کانفیگ ناموفق بود: {}".format(e))

    try:
        bot.send_message(user_id, CONFIG_MESSAGE, timeout=20)
        logging.info("کانفیگ متنی به {} ارسال شد".format(user_id))
    except Exception as e:
        logging.critical("❌ ارسال کانفیگ به {} شکست خورد: {}".format(user_id, e))

# ================== دستورات ==================
@bot.message_handler(commands=["start"])
def start(msg):
    register_user(msg.from_user)
    welcome = get_setting(
        "welcome_text",
        "👋 به ربات زئوس شاپ خوش اومدی\n\nتو این روزای سخت، ما هواتو داریم 💚\n\n"
        "✅ فیلترشکن پرسرعت، بدون محدودیت و اختلال\n\n📢 کانال رسمی زئوس شاپ:\n🟢 @ir_SAbzNet"
    )
    # پیام خوش‌آمد و کیبورد خدمات در همان ارسال، خودکار زیر پیام نمایش داده می‌شود.
    bot.send_message(msg.chat.id, welcome, reply_markup=main_keyboard())

@bot.message_handler(commands=["myid"])
def myid_command(msg):
    register_user(msg.from_user)
    u = msg.from_user
    joined = cur.execute("SELECT created_at FROM users WHERE user_id=?", (u.id,)).fetchone()
    purchases = cur.execute("SELECT COUNT(*) FROM invoices WHERE user_id=? AND status='approved'", (u.id,)).fetchone()[0]
    username = "@" + u.username if u.username else "ندارد"
    bot.send_message(msg.chat.id,
        "👤 <b>پروفایل شما</b>\n\n"
        "نام: {}\nآیدی: <code>{}</code>\nیوزرنیم: {}\nتاریخ عضویت: {}\nتعداد خرید موفق: {}".format(
            (u.first_name or "") + ((" " + u.last_name) if u.last_name else ""),
            u.id, username, joined[0] if joined else "نامشخص", purchases))

@bot.message_handler(commands=["coupon"])
def apply_coupon(msg):
    register_user(msg.from_user)
    parts = (msg.text or "").split(maxsplit=1)
    if len(parts) != 2:
        bot.send_message(msg.chat.id, "روش استفاده: /coupon CODE")
        return
    code = parts[1].strip().upper()
    coupon = cur.execute("SELECT discount_percent FROM coupons WHERE code=? AND active=1", (code,)).fetchone()
    invoice = cur.execute("SELECT invoice,amount FROM invoices WHERE user_id=? AND status='pending' ORDER BY created_at DESC LIMIT 1", (msg.from_user.id,)).fetchone()
    if not coupon:
        bot.send_message(msg.chat.id, "❌ کد تخفیف معتبر نیست."); return
    if not invoice:
        bot.send_message(msg.chat.id, "ابتدا یک محصول انتخاب کن تا فاکتور ساخته شود."); return
    new_amount = max(1, int(invoice[1] * (100 - coupon[0]) / 100))
    cur.execute("UPDATE invoices SET amount=? WHERE invoice=?", (new_amount, invoice[0])); conn.commit()
    bot.send_message(msg.chat.id, "✅ تخفیف {}٪ اعمال شد. مبلغ جدید فاکتور: {:,} تومان\nلطفاً رسید پرداخت را ارسال کن.".format(coupon[0], new_amount))

@bot.message_handler(commands=["support"])
def support_command(msg):
    bot.send_message(msg.chat.id, get_setting("support_text", SUPPORT_TEXT), reply_markup=support_keyboard)

@bot.message_handler(commands=["help"])
def help_command(msg):
    bot.send_message(msg.chat.id, HELP_TEXT, reply_markup=support_keyboard)

@bot.message_handler(commands=["test"])
def help_command(msg):
    bot.send_message(msg.chat.id, TEST_TEXT, reply_markup=support_keyboard)

# ================== منو ==================
@bot.message_handler(commands=["admin"])
def admin_command(msg):
    if msg.from_user.id not in ADMIN_IDS:
        return
    bot.send_message(msg.chat.id, "🛠 <b>پنل مدیریت زئوس شاپ</b>\n\nاز منوی زیر انتخاب کنید:", reply_markup=admin_keyboard())

@bot.callback_query_handler(func=lambda c: c.data.startswith("adm_") and not c.data.startswith("adm_text_"))
def admin_panel_callback(call):
    if call.from_user.id not in ADMIN_IDS:
        bot.answer_callback_query(call.id, "دسترسی ندارید", show_alert=True)
        return
    action = call.data[4:]
    bot.answer_callback_query(call.id)

    if action == "products":
        products = cur.execute("SELECT id,service,title,price,icon,active FROM products ORDER BY id").fetchall()
        rows = []
        for pid, service, title, price, icon, active in products:
            state = "🟢" if active else "🔴"
            rows.append([_button("{} {} | {:,} | {}".format(state, title, price, service), callback_data="editprod_{}".format(pid), style="success")])
        rows.append([_button("➕ افزودن محصول", callback_data="adm_add", style="success")])
        kb = _inline_keyboard(rows)
        bot.send_message(call.message.chat.id, "🛍 <b>مدیریت محصولات</b>\nروی محصول بزنید:", reply_markup=kb)

    elif action == "add":
        ADMIN_STATE[call.from_user.id] = {"state": "add", "step": 1}
        bot.send_message(
            call.message.chat.id,
            "➕ افزودن محصول\n\n"
            "مرحله 1/4: سرویس را وارد کن:\n"
            "<code>config</code> / <code>premium</code> / <code>self</code> / <code>virtual</code> / <code>stars</code> / <code>gift_15</code> / <code>gift_25</code> / <code>gift_50</code> / <code>gift_100</code>"
        )

    elif action == "broadcast":
        ADMIN_STATE[call.from_user.id] = {"state": "broadcast"}
        bot.send_message(call.message.chat.id, "📢 متن پیام همگانی را ارسال کن.\nبرای لغو بنویس: لغو")

    elif action == "stats":
        count = cur.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        invoices = cur.execute("SELECT COUNT(*) FROM invoices").fetchone()[0]
        bot.send_message(call.message.chat.id, "📊 کاربران: <b>{:,}</b>\n🧾 فاکتورها: <b>{:,}</b>".format(count, invoices))

    elif action == "users":
        rows = cur.execute("SELECT user_id,first_name,username,created_at FROM users ORDER BY created_at DESC LIMIT 50").fetchall()
        if not rows:
            bot.send_message(call.message.chat.id, "هنوز کاربری ثبت نشده است.")
        else:
            lines = ["👥 <b>۵۰ کاربر آخر</b>"]
            for uid, first, username, joined in rows:
                lines.append("• {} | <code>{}</code> | {} | {}".format(first or "بدون نام", uid, "@"+username if username else "بدون یوزرنیم", joined or "-"))
            bot.send_message(call.message.chat.id, "\n".join(lines))
    elif action == "card":
        kb = _inline_keyboard([
            [_button("✏️ تغییر شماره کارت", callback_data="card_edit_number", style="success"), _button("🗑 حذف شماره کارت", callback_data="card_delete_number", style="danger")],
            [_button("✏️ تغییر نام گیرنده", callback_data="card_edit_owner", style="success"), _button("🗑 حذف نام گیرنده", callback_data="card_delete_owner", style="danger")],
        ])
        bot.send_message(call.message.chat.id,
            "💳 <b>تنظیمات کارت بانکی</b>\n\n"
            "شماره کارت فعلی: <code>{}</code>\n"
            "نام گیرنده فعلی: {}\n\n"
            "عملیات موردنظر را انتخاب کن:".format(get_setting("card_number", "ثبت نشده"), get_setting("card_owner", "ثبت نشده")),
            reply_markup=kb)
    elif action == "coupon":
        ADMIN_STATE[call.from_user.id] = {"state": "coupon_code"}
        bot.send_message(call.message.chat.id, "کد تخفیف را بفرست:")
    elif action == "backup":
        try:
            conn.commit()
            backup_path = "/tmp/zeus_shop_backup_{}.db".format(datetime.now().strftime("%Y%m%d_%H%M%S"))
            dest = sqlite3.connect(backup_path)
            conn.backup(dest)
            dest.close()
            with open(backup_path, "rb") as f:
                bot.send_document(call.message.chat.id, f, caption="💾 بکاپ دیتابیس زئوس شاپ")
            os.remove(backup_path)
        except Exception as e:
            bot.send_message(call.message.chat.id, "خطا در بکاپ: {}".format(e))
    elif action == "restore":
        ADMIN_STATE[call.from_user.id] = {"state": "restore"}
        bot.send_message(call.message.chat.id, "فایل بکاپ دیتابیس با پسوند db یا sqlite را ارسال کن. دیتابیس فعلی قبل از جایگزینی بکاپ می‌شود.")
    elif action == "texts":
        rows = []
        text_options = [
            ("متن خوش‌آمدگویی", "welcome"),
            ("متن پشتیبانی", "support"),
            ("متن توضیحات کانفیگ", "config"),
            ("متن راهنما", "help"),
            ("متن سرویس تست", "test"),
            ("متن کانفیگ ارسالی پس از خرید", "config_message"),
        ]
        for label, key in text_options:
            rows.append([_button(label, callback_data="adm_text_" + key, style="success")])
        bot.send_message(call.message.chat.id, "✏️ کدام متن را می‌خواهی ویرایش کنی؟", reply_markup=_inline_keyboard(rows))

@bot.callback_query_handler(func=lambda c: c.data in ("card_edit_number", "card_delete_number", "card_edit_owner", "card_delete_owner"))
def card_setting_callback(call):
    if call.from_user.id not in ADMIN_IDS:
        bot.answer_callback_query(call.id, "دسترسی ندارید", show_alert=True)
        return
    action = call.data
    bot.answer_callback_query(call.id)
    if action == "card_delete_number":
        set_setting("card_number", "")
        bot.send_message(call.message.chat.id, "🗑 شماره کارت حذف شد.")
    elif action == "card_delete_owner":
        set_setting("card_owner", "")
        bot.send_message(call.message.chat.id, "🗑 نام گیرنده کارت حذف شد.")
    elif action == "card_edit_number":
        ADMIN_STATE[call.from_user.id] = {"state": "card_number"}
        bot.send_message(call.message.chat.id, "شماره کارت جدید را فقط با ارقام بفرست:")
    elif action == "card_edit_owner":
        ADMIN_STATE[call.from_user.id] = {"state": "card_owner"}
        bot.send_message(call.message.chat.id, "نام جدید گیرنده کارت را بفرست:")

@bot.callback_query_handler(func=lambda c: c.data.startswith("adm_text_"))
def admin_text_callback(call):
    if call.from_user.id not in ADMIN_IDS:
        bot.answer_callback_query(call.id, "دسترسی ندارید", show_alert=True); return
    key = call.data[len("adm_text_"):]
    mapping = {
        "welcome": "welcome_text", "support": "support_text", "config": "config_text",
        "help": "help_text", "test": "test_text", "config_message": "config_message"
    }
    if key not in mapping:
        bot.answer_callback_query(call.id, "گزینه نامعتبر است", show_alert=True)
        return
    ADMIN_STATE[call.from_user.id] = {"state": "edit_text", "key": mapping[key]}
    bot.answer_callback_query(call.id)
    bot.send_message(call.message.chat.id, "متن جدید را ارسال کن. برای لغو بنویس لغو.")

@bot.callback_query_handler(func=lambda c: c.data.startswith("editprod_"))
def edit_product_callback(call):
    if call.from_user.id not in ADMIN_IDS:
        return
    pid = int(call.data.split("_", 1)[1])
    row = cur.execute("SELECT id,service,title,price,icon,sticker_file_id,active FROM products WHERE id=?", (pid,)).fetchone()
    if not row:
        bot.answer_callback_query(call.id, "محصول پیدا نشد", show_alert=True)
        return
    _, service, title, price, icon, sticker_id, active = row
    kb = _inline_keyboard([
        [_button("💰 تغییر قیمت", callback_data="setprice_{}".format(pid), style="success"), _button("✏️ تغییر نام", callback_data="settitle_{}".format(pid), style="success")],
        [_button("🎨 تغییر آیکون", callback_data="seticon_{}".format(pid), style="success"), _button("🗂 تغییر دسته‌بندی", callback_data="setservice_{}".format(pid), style="success")],
        [_button("🎟 تغییر استیکر", callback_data="setsticker_{}".format(pid), style="success"), _button("🟢/🔴 فعال/غیرفعال", callback_data="toggle_{}".format(pid), style="success")],
        [_button("🗑 حذف", callback_data="delprod_{}".format(pid), style="danger")],
    ])
    bot.answer_callback_query(call.id)
    bot.send_message(
        call.message.chat.id,
        "🛍 <b>مدیریت محصول</b>\n\n"
        "نام: {}\nقیمت: {:,} تومان\nسرویس: {}\nآیکون: {}\nاستیکر: {}\nوضعیت: {}".format(
            title, price, service, icon or "ندارد", "دارد" if sticker_id else "ندارد",
            "فعال" if active else "غیرفعال"
        ),
        reply_markup=kb
    )

@bot.callback_query_handler(func=lambda c: c.data.startswith(("setprice_","settitle_","seticon_","setsticker_","toggle_","delprod_")))
def product_action_callback(call):
    if call.from_user.id not in ADMIN_IDS:
        return
    action, pid_s = call.data.rsplit("_", 1)
    pid = int(pid_s)
    bot.answer_callback_query(call.id)
    if action == "toggle":
        cur.execute("UPDATE products SET active=CASE active WHEN 1 THEN 0 ELSE 1 END WHERE id=?", (pid,))
        conn.commit()
        bot.send_message(call.message.chat.id, "✅ وضعیت محصول تغییر کرد.")
    elif action == "delprod":
        cur.execute("DELETE FROM products WHERE id=?", (pid,))
        conn.commit()
        bot.send_message(call.message.chat.id, "🗑 محصول حذف شد.")
    else:
        ADMIN_STATE[call.from_user.id] = {"state": action, "product_id": pid}
        prompts = {
            "setprice": "💰 قیمت جدید را فقط به تومان وارد کن.",
            "settitle": "✏️ نام جدید محصول را بفرست.",
            "seticon": "🎨 آیکون/ایموجی جدید را بفرست.",
            "setsticker": "🎟 استیکر جدید را همینجا ارسال کن.",
            "setservice": "🗂 شناسه دسته‌بندی جدید را بفرست؛ مثل config یا premium یا self یا virtual یا stars یا gift_15.",
        }
        bot.send_message(call.message.chat.id, prompts[action])

@bot.message_handler(commands=["broadcast"])
def broadcast_command(msg):
    if msg.from_user.id not in ADMIN_IDS:
        return
    ADMIN_STATE[msg.from_user.id] = {"state": "broadcast"}
    bot.send_message(msg.chat.id, "📢 متن پیام همگانی را ارسال کن.")

@bot.message_handler(content_types=["text","sticker","document"], func=lambda m: m.from_user.id in ADMIN_IDS and m.from_user.id in ADMIN_STATE)
def admin_state_handler(msg):
    global conn, cur
    state_data = ADMIN_STATE.get(msg.from_user.id)
    if not state_data:
        return
    state = state_data["state"]

    if msg.content_type == "text" and (msg.text or "").strip() == "لغو":
        ADMIN_STATE.pop(msg.from_user.id, None)
        bot.send_message(msg.chat.id, "❌ عملیات لغو شد.")
        return

    if state == "restore":
        if msg.content_type != "document":
            bot.send_message(msg.chat.id, "لطفاً فایل بکاپ را به صورت Document ارسال کن.")
            return
        name = (msg.document.file_name or "").lower()
        if not name.endswith((".db", ".sqlite", ".sqlite3")):
            bot.send_message(msg.chat.id, "فقط فایل دیتابیس با پسوند db یا sqlite پذیرفته می‌شود.")
            return
        try:
            info = bot.get_file(msg.document.file_id)
            data = bot.download_file(info.file_path)
            tmp = DATABASE_PATH + ".restore_tmp"
            with open(tmp, "wb") as f: f.write(data)
            test = sqlite3.connect(tmp)
            test.execute("PRAGMA integrity_check").fetchone()
            test.close()
            conn.commit()
            safety_path = DATABASE_PATH + ".before_restore.bak"
            safety = sqlite3.connect(safety_path)
            conn.backup(safety)
            safety.close()
            conn.close()
            os.replace(tmp, DATABASE_PATH)
            conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
            cur = conn.cursor()
            bot.send_message(msg.chat.id, "✅ دیتابیس با موفقیت ریستور شد. ربات آماده ادامه کار است.")
            ADMIN_STATE.pop(msg.from_user.id, None)
        except Exception as e:
            bot.send_message(msg.chat.id, "❌ ریستور انجام نشد: {}".format(e))
        return

    if state == "card_number":
        if msg.content_type != "text" or not msg.text.strip().isdigit():
            bot.send_message(msg.chat.id, "شماره کارت باید فقط شامل رقم باشد.")
            return
        set_setting("card_number", msg.text.strip())
        ADMIN_STATE[msg.from_user.id] = {"state": "card_owner"}
        bot.send_message(msg.chat.id, "نام صاحب کارت را بفرست:")
        return
    if state == "card_owner":
        if msg.content_type != "text": return
        set_setting("card_owner", msg.text.strip())
        ADMIN_STATE.pop(msg.from_user.id, None)
        bot.send_message(msg.chat.id, "✅ اطلاعات کارت ذخیره شد.")
        return
    if state == "coupon_code":
        if msg.content_type != "text": return
        ADMIN_STATE[msg.from_user.id] = {"state": "coupon_percent", "code": msg.text.strip().upper()}
        bot.send_message(msg.chat.id, "درصد تخفیف را بین 1 تا 90 بفرست:")
        return
    if state == "coupon_percent":
        try: percent = int(msg.text.strip())
        except Exception:
            bot.send_message(msg.chat.id, "درصد نامعتبر است."); return
        if not 1 <= percent <= 90:
            bot.send_message(msg.chat.id, "درصد باید بین 1 تا 90 باشد."); return
        cur.execute("INSERT OR REPLACE INTO coupons(code,discount_percent,active) VALUES (?,?,1)", (state_data["code"], percent)); conn.commit()
        ADMIN_STATE.pop(msg.from_user.id, None)
        bot.send_message(msg.chat.id, "✅ کد تخفیف {} با {}٪ ساخته شد.".format(state_data["code"], percent))
        return
    if state == "edit_text":
        if msg.content_type != "text": return
        set_setting(state_data["key"], msg.text)
        ADMIN_STATE.pop(msg.from_user.id, None)
        bot.send_message(msg.chat.id, "✅ متن با موفقیت ذخیره شد.")
        return
    if state == "edit_support":
        if msg.content_type != "text": return
        set_setting("support_text", msg.text)
        ADMIN_STATE.pop(msg.from_user.id, None)
        bot.send_message(msg.chat.id, "✅ متن پشتیبانی ذخیره شد.")
        return

    if state == "broadcast":
        if msg.content_type != "text":
            bot.send_message(msg.chat.id, "❌ برای پیام همگانی فعلاً فقط متن ارسال کن.")
            return
        users = [r[0] for r in cur.execute("SELECT user_id FROM users").fetchall()]
        ok = 0
        for uid in users:
            try:
                bot.send_message(uid, msg.text)
                ok += 1
            except Exception:
                pass
        ADMIN_STATE.pop(msg.from_user.id, None)
        bot.send_message(msg.chat.id, "📢 ارسال تمام شد. موفق: {} از {}".format(ok, len(users)))
        return

    if state == "add":
        step = state_data["step"]
        if msg.content_type != "text":
            bot.send_message(msg.chat.id, "❌ متن ارسال کن.")
            return
        if step == 1:
            state_data["service"] = msg.text.strip()
            state_data["step"] = 2
            bot.send_message(msg.chat.id, "مرحله 2/4: نام محصول را بفرست.")
        elif step == 2:
            state_data["title"] = msg.text.strip()
            state_data["step"] = 3
            bot.send_message(msg.chat.id, "مرحله 3/4: قیمت را به تومان بفرست.")
        elif step == 3:
            try:
                price = int(msg.text.replace(",", "").replace("٬", "").strip())
            except ValueError:
                bot.send_message(msg.chat.id, "❌ قیمت نامعتبر است.")
                return
            state_data["price"] = price
            state_data["step"] = 4
            bot.send_message(msg.chat.id, "مرحله 4/4: آیکون/ایموجی محصول را بفرست.")
        elif step == 4:
            cur.execute(
                "INSERT INTO products(service,title,price,icon) VALUES (?,?,?,?)",
                (state_data["service"], state_data["title"], state_data["price"], msg.text.strip())
            )
            conn.commit()
            ADMIN_STATE.pop(msg.from_user.id, None)
            bot.send_message(msg.chat.id, "✅ محصول با موفقیت اضافه شد.")
        return

    pid = state_data["product_id"]
    if state in ("setprice","settitle","seticon"):
        if msg.content_type != "text":
            bot.send_message(msg.chat.id, "❌ متن ارسال کن.")
            return
        if state == "setprice":
            try:
                value = int(msg.text.replace(",", "").replace("٬", "").strip())
            except ValueError:
                bot.send_message(msg.chat.id, "❌ قیمت نامعتبر است.")
                return
            cur.execute("UPDATE products SET price=? WHERE id=?", (value, pid))
        elif state == "settitle":
            cur.execute("UPDATE products SET title=? WHERE id=?", (msg.text.strip(), pid))
        else:
            cur.execute("UPDATE products SET icon=? WHERE id=?", (msg.text.strip(), pid))
        conn.commit()
        ADMIN_STATE.pop(msg.from_user.id, None)
        bot.send_message(msg.chat.id, "✅ تغییرات ذخیره شد.")
    elif state == "setservice":
        if msg.content_type != "text": return
        cur.execute("UPDATE products SET service=? WHERE id=?", (msg.text.strip(), pid))
        conn.commit(); ADMIN_STATE.pop(msg.from_user.id, None)
        bot.send_message(msg.chat.id, "✅ دسته‌بندی محصول تغییر کرد.")
    elif state == "setsticker":
        if msg.content_type != "sticker":
            bot.send_message(msg.chat.id, "❌ لطفاً یک استیکر ارسال کن.")
            return
        cur.execute("UPDATE products SET sticker_file_id=? WHERE id=?", (msg.sticker.file_id, pid))
        conn.commit()
        ADMIN_STATE.pop(msg.from_user.id, None)
        bot.send_message(msg.chat.id, "✅ استیکر محصول ذخیره شد.")

# ================== منو ==================
@bot.message_handler(func=lambda m: True, content_types=["text"])
def menu_handler(msg):
    register_user(msg.from_user)
    text = msg.text
    if text == "🤖 سلف و تبچی":
        show_products(msg.chat.id, "self")
    elif text == "♻️ شماره مجازی":
        show_products(msg.chat.id, "virtual")
    elif text == "🎁 گیفت استارزی":
        show_products(msg.chat.id, "gift_15")
        # محصولات تمام گیفت‌ها را پشت سر هم نشان می‌دهیم تا مدیریتشان مستقل باشد.
        show_products(msg.chat.id, "gift_25")
        show_products(msg.chat.id, "gift_50")
        show_products(msg.chat.id, "gift_100")
    elif text == "💫 استازر":
        show_products(msg.chat.id, "stars")
    elif text == "🔥 کانفیگ اختصاصی":
        show_products(msg.chat.id, "config")
    elif text == "💎 پرمیوم":
        show_products(msg.chat.id, "premium")
    elif text == "☎️ پشتیبانی":
        bot.send_message(msg.chat.id, get_setting("support_text", SUPPORT_TEXT), reply_markup=support_keyboard)
    elif text in ["لغو", "منوی اصلی"]:
        bot.send_message(msg.chat.id, "🏠", reply_markup=main_keyboard())

# ================== انتخاب خدمات از کیبورد اصلی تلگرام ==================
@bot.callback_query_handler(func=lambda c: c.data.startswith("main_"))
def main_menu_callback(call):
    register_user(call.from_user)
    action = call.data[5:]
    bot.answer_callback_query(call.id)
    if action == "self":
        show_products(call.message.chat.id, "self")
    elif action == "virtual":
        show_products(call.message.chat.id, "virtual")
    elif action == "gift":
        for service in ("gift_15", "gift_25", "gift_50", "gift_100"):
            show_products(call.message.chat.id, service)
    elif action == "config":
        show_products(call.message.chat.id, "config")
    elif action == "premium":
        show_products(call.message.chat.id, "premium")
    elif action == "stars":
        show_products(call.message.chat.id, "stars")
    elif action == "support":
        bot.send_message(call.message.chat.id, get_setting("support_text", SUPPORT_TEXT), reply_markup=support_keyboard)

# ================== انتخاب محصول از پنل ==================
@bot.callback_query_handler(func=lambda c: c.data.startswith("prod_"))
def product_handler(call):
    register_user(call.from_user)
    try:
        pid = int(call.data.split("_", 1)[1])
    except ValueError:
        bot.answer_callback_query(call.id, "محصول نامعتبر", show_alert=True)
        return
    row = cur.execute(
        "SELECT service,title,price,sticker_file_id FROM products WHERE id=? AND active=1",
        (pid,)
    ).fetchone()
    if not row:
        bot.answer_callback_query(call.id, "این محصول دیگر فعال نیست.", show_alert=True)
        return
    service, title, amount, sticker_id = row
    bot.answer_callback_query(call.id)
    if sticker_id:
        try:
            bot.send_sticker(call.message.chat.id, sticker_id)
        except Exception:
            pass
    invoice = "SN-{}".format(random.randint(100000, 999999))
    cur.execute("DELETE FROM invoices WHERE user_id=? AND status='pending'", (call.from_user.id,))
    cur.execute(
        "INSERT INTO invoices VALUES (?,?,?,?,?,?,?,?,?,?)",
        (invoice, call.from_user.id, amount, "pending", 0, None, datetime.now().isoformat(), service, None, 0)
    )
    conn.commit()
    bot.send_message(
        call.message.chat.id,
        "✅ فاکتور خرید شما ساخته شد!\n\n"
        "💳 شماره فاکتور: {}\n"
        "📦 محصول: {}\n"
        "💲 مبلغ قابل پرداخت: {:,} تومان\n"
        "~~~~\n"
        "💳 شماره کارت: {}\n"
        "👤 صاحب کارت: {}\n\n"
        "🔵 لطفاً رسید پرداخت را ارسال کنید".format(invoice, title, amount, get_setting("card_number", "ثبت نشده"), get_setting("card_owner", "ثبت نشده")),
        reply_markup=invoice_keyboard
    )

# ================== انتخاب پلن ==================
@bot.callback_query_handler(func=lambda c: c.data.startswith("plan_"))
def plan_handler(call):
    bot.answer_callback_query(call.id)
    
    parts = call.data.split("_")
    
    if len(parts) == 4 and parts[3].startswith("gift"):
        amount = parts[1]
        service = "{}_{}".format(parts[2], parts[3])
    else:
        amount = parts[1]
        service = parts[2]
    
    amount = int(amount)
    invoice = "SN-{}".format(random.randint(100000,999999))

    cur.execute("DELETE FROM invoices WHERE user_id=? AND status='pending'", (call.from_user.id,))
    cur.execute(
        "INSERT INTO invoices VALUES (?,?,?,?,?,?,?,?,?,?)",
        (invoice, call.from_user.id, amount, "pending", 0, None, datetime.now().isoformat(), service, None, 0)
    )
    conn.commit()

    bot.send_message(
        call.message.chat.id,
        "✅ فاکتور خرید شما ساخته شد!\n\n"
        "💳 شماره فاکتور: {}\n"
        "💲 مبلغ قابل پرداخت: {:,} تومان\n"
        "~~~~\n"
        "💳 شماره کارت: {}\n"
        "👤 صاحب کارت: {}\n\n"
        "🔵 لطفاً رسید پرداخت را ارسال کنید".format(invoice, amount, get_setting("card_number", "ثبت نشده"), get_setting("card_owner", "ثبت نشده")),
        reply_markup=invoice_keyboard
    )

# ================== دریافت رسید ==================
@bot.message_handler(content_types=["photo"])
def receipt_handler(msg):
    cur.execute(
        "SELECT invoice, receipt_sent FROM invoices "
        "WHERE user_id=? AND status='pending' "
        "ORDER BY created_at DESC LIMIT 1",
        (msg.from_user.id,)
    )
    row = cur.fetchone()
    if not row or row[1]:
        return

    invoice = row[0]

    wait_msg = bot.send_message(
        msg.chat.id,
        "⏳ رسید شما دریافت شد و در انتظار تأیید می‌باشد",
        reply_markup=main_keyboard()
    )

    file_id = msg.photo[-1].file_id
    cur.execute(
        "UPDATE invoices SET receipt_sent=1, wait_message_id=?, receipt_file_id=? WHERE invoice=?",
        (wait_msg.message_id, file_id, invoice)
    )
    conn.commit()

    kb = _inline_keyboard([[
        _button("✅ تأیید پرداخت", callback_data="approve_{}".format(invoice), style="success"),
        _button("❌ لغو پرداخت", callback_data="reject_{}".format(invoice), style="danger"),
    ]])

    first = msg.from_user.first_name or ""
    last = msg.from_user.last_name or ""
    username = msg.from_user.username

    user_info = (first + " " + last).strip()
    if username:
        user_info += " (@{})".format(username)

    user_info += " (ID: {})".format(msg.from_user.id)
    
    for admin in ADMIN_IDS:
        bot.send_photo(
            admin,
            file_id,
            caption="📸 رسید جدید\n💳 فاکتور: {}\n👤 {}\n🕐 {}".format(
                invoice, user_info, datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            ),
            reply_markup=kb
        )

# ================== تصمیم ادمین ==================
@bot.callback_query_handler(func=lambda c: c.data.startswith(("approve_", "reject_")))
def admin_handler(call):
    if call.from_user.id not in ADMIN_IDS:
        return

    action, invoice = call.data.split("_", 1)

    cur.execute(
        "SELECT status, user_id, wait_message_id, service, receipt_file_id, amount "
        "FROM invoices WHERE invoice=?",
        (invoice,)
    )
    row = cur.fetchone()
    if not row or row[0] != "pending":
        try:
            bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id)
        except:
            pass
        return

    status, user_id, wait_msg_id, service, receipt_file_id, amount = row

    try:
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id)
    except:
        pass

    if action == "approve":
        cur.execute("UPDATE invoices SET status='approved' WHERE invoice=?", (invoice,))
        conn.commit()

        try:
            bot.edit_message_text("✅ پرداخت شما تأیید شد!", chat_id=user_id, message_id=wait_msg_id)
        except Exception as e:
            logging.error("خطا در ویرایش پیام تایید: {}".format(e))
            bot.send_message(user_id, "✅ پرداخت شما تأیید شد!")

        service_messages = {
            "premium": {
                "text": "لطفاً جهت فعالسازی پرمیوم بر روی حساب مورد نظر خودت به پشتیبانی پیام دهید!\n\n⚠️ توجه : قبل از پیام به پشتیبانی از این صفحه اسکرین شات بگیرید و برای پشتیبانی ارسال کنید.",
                "button_text": "💎 پیام به پشتیبانی پرمیوم"
            },
            "self": {
                "text": "لطفاً جهت فعالسازی سلف بر روی حساب مورد نظر خودت به پشتیبانی پیام دهید!\n\n⚠️ توجه : قبل از پیام به پشتیبانی از این صفحه اسکرین شات بگیرید و برای پشتیبانی ارسال کنید.",
                "button_text": "🤖 پیام به پشتیبانی سلف"
            },
            "virtual": {
                "text": "لطفاً جهت دریافت شماره مجازی به پشتیبانی پیام دهید!\n\n⚠️ توجه : قبل از پیام به پشتیبانی از این صفحه اسکرین شات بگیرید و برای پشتیبانی ارسال کنید.",
                "button_text": "♻️ پیام به پشتیبانی شماره مجازی"
            },
            "stars": {
                "text": "لطفاً جهت دریافت استارز خریداری شده به پشتیبانی پیام دهید!\n\n⚠️ توجه : قبل از پیام به پشتیبانی از این صفحه اسکرین شات بگیرید و برای پشتیبانی ارسال کنید.",
                "button_text": "⭐️ پیام به پشتیبانی استارز"
            },
            "gift": {
                "text": "لطفاً جهت دریافت گیفت استارز خریداری شده به پشتیبانی پیام دهید!\n\n⚠️ توجه : قبل از پیام به پشتیبانی از این صفحه اسکرین شات بگیرید و برای پشتیبانی ارسال کنید.",
                "button_text": "🎁 پیام به پشتیبانی گیفت استارز"
            },
            "gift_15": {
                "text": "لطفاً جهت دریافت گیفت استارز خریداری شده به پشتیبانی پیام دهید!\n\n⚠️ توجه : قبل از پیام به پشتیبانی از این صفحه اسکرین شات بگیرید و برای پشتیبانی ارسال کنید.",
                "button_text": "🎁 پیام به پشتیبانی گیفت استارز"
            },
            "gift_25": {
                "text": "لطفاً جهت دریافت گیفت استارز خریداری شده به پشتیبانی پیام دهید!\n\n⚠️ توجه : قبل از پیام به پشتیبانی از این صفحه اسکرین شات بگیرید و برای پشتیبانی ارسال کنید.",
                "button_text": "🎁 پیام به پشتیبانی گیفت استارز"
            },
            "gift_50": {
                "text": "لطفاً جهت دریافت گیفت استارز خریداری شده به پشتیبانی پیام دهید!\n\n⚠️ توجه : قبل از پیام به پشتیبانی از این صفحه اسکرین شات بگیرید و برای پشتیبانی ارسال کنید.",
                "button_text": "🎁 پیام به پشتیبانی گیفت استارز"
            },
            "gift_100": {
                "text": "لطفاً جهت دریافت گیفت استارز خریداری شده به پشتیبانی پیام دهید!\n\n⚠️ توجه : قبل از پیام به پشتیبانی از این صفحه اسکرین شات بگیرید و برای پشتیبانی ارسال کنید.",
                "button_text": "🎁 پیام به پشتیبانی گیفت استارز"
            }
        }

        service_data = service_messages.get(service)
        
        if service_data:
            keyboard = _inline_keyboard([[
                _button(service_data["button_text"], url="https://t.me/MDF_1819", style="success")
            ]])
            
            bot.send_message(
                user_id,
                "{}\n\n@MDF_1819".format(service_data["text"]),
                reply_markup=keyboard
            )

        if service not in ["premium", "self", "virtual", "stars", "gift", "gift_15", "gift_25", "gift_50", "gift_100"]:
            send_config_safe(user_id)

        if receipt_file_id:
            cur.execute("SELECT sent_to_owner FROM invoices WHERE invoice=?", (invoice,))
            already_sent = cur.fetchone()[0]
            
            if not already_sent:
                if send_receipt_to_owner_automatically(receipt_file_id, invoice, user_id, amount, service):
                    cur.execute("UPDATE invoices SET sent_to_owner=1 WHERE invoice=?", (invoice,))
                    conn.commit()
                    logging.info("✅ رسید {} برای مالک ارسال شد".format(invoice))

        try:
            bot.edit_message_caption(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                caption=call.message.caption + "\n✅ پرداخت تأیید شد"
            )
        except:
            pass

    else:
        cur.execute("UPDATE invoices SET status='rejected' WHERE invoice=?", (invoice,))
        conn.commit()

        try:
            reject_keyboard = _inline_keyboard([[
                _button("📞 پیام به پشتیبانی", url="https://t.me/MDF_1819", style="success")
            ]])
            
            bot.edit_message_text(
                "❌ پرداخت شما رد شد\n\nلطفاً با پشتیبانی تماس بگیرید:\n@MDF_1819",
                chat_id=user_id,
                message_id=wait_msg_id,
                reply_markup=reject_keyboard
            )
        except Exception as e:
            logging.error("خطا در ویرایش پیام رد پرداخت: {}".format(e))
            bot.send_message(user_id, "❌ پرداخت شما رد شد\n\nلطفاً با پشتیبانی تماس بگیرید:\n@MDF_1819")

        try:
            bot.edit_message_caption(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                caption=call.message.caption + "\n❌ پرداخت لغو شد"
            )
        except:
            pass


# ================== Telegram Mini App (ZEUS NEON) ==================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MINIAPP_DIR = os.path.join(BASE_DIR, "miniapp")
# Support both expected layouts: miniapp/index.html and index.html at repo root.
if not os.path.isfile(os.path.join(MINIAPP_DIR, "index.html")):
    if os.path.isfile(os.path.join(BASE_DIR, "index.html")):
        MINIAPP_DIR = BASE_DIR
    else:
        logging.error("Mini App index.html not found in %s or %s", MINIAPP_DIR, BASE_DIR)
mini_app = Flask(__name__, static_folder=MINIAPP_DIR, static_url_path="")

SERVICE_LABELS = {
    "config": "کانفیگ اختصاصی", "premium": "تلگرام پرمیوم", "self": "سلف و تبچی",
    "virtual": "شماره مجازی", "stars": "تلگرام استارز",
    "gift_15": "گیفت ۱۵ استارز", "gift_25": "گیفت ۲۵ استارز",
    "gift_50": "گیفت ۵۰ استارز", "gift_100": "گیفت ۱۰۰ استارز",
}

def validate_webapp_init_data(init_data):
    if not init_data:
        return None
    try:
        values = dict(urllib.parse.parse_qsl(init_data, keep_blank_values=True))
        received_hash = values.pop("hash", "")
        if not received_hash:
            return None
        data_check_string = "\n".join("{}={}".format(k, v) for k, v in sorted(values.items()))
        secret_key = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
        calculated = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(calculated, received_hash):
            return None
        auth_date = int(values.get("auth_date", "0"))
        if auth_date <= 0 or time.time() - auth_date > 86400 or auth_date > time.time() + 60:
            return None
        user = json.loads(values.get("user", "{}"))
        if not user.get("id"):
            return None
        return user
    except Exception:
        logging.exception("اعتبارسنجی Mini App ناموفق بود")
        return None

@mini_app.get("/")
def mini_home():
    return send_from_directory(MINIAPP_DIR, "index.html")

@mini_app.get("/api/products")
def mini_products():
    db = sqlite3.connect(DATABASE_PATH, timeout=10)
    db.row_factory = sqlite3.Row
    try:
        rows = db.execute("SELECT id,service,title,price,icon FROM products WHERE active=1 ORDER BY id").fetchall()
        products = [{"id": r["id"], "service": r["service"], "service_title": SERVICE_LABELS.get(r["service"], r["service"]),
                    "title": r["title"], "price": r["price"], "icon": r["icon"] or "🛍️"} for r in rows]
        return jsonify({"ok": True, "products": products})
    finally:
        db.close()

@mini_app.post("/api/order")
def mini_create_order():
    payload = request.get_json(silent=True) or {}
    user = validate_webapp_init_data(payload.get("initData", ""))
    if not user:
        return jsonify({"ok": False, "error": "اعتبار نشست تلگرام تأیید نشد. مینی‌اپ را از داخل ربات باز کنید."}), 401
    try:
        product_id = int(payload.get("product_id", 0))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "محصول نامعتبر است."}), 400
    db = sqlite3.connect(DATABASE_PATH, timeout=10)
    try:
        db.execute("BEGIN IMMEDIATE")
        product = db.execute("SELECT service,title,price FROM products WHERE id=? AND active=1", (product_id,)).fetchone()
        if not product:
            db.rollback()
            return jsonify({"ok": False, "error": "این محصول در دسترس نیست."}), 404
        invoice = "SN-{}{}".format(int(time.time()), random.randint(100, 999))
        db.execute("DELETE FROM invoices WHERE user_id=? AND status='pending'", (int(user["id"]),))
        db.execute("INSERT INTO invoices VALUES (?,?,?,?,?,?,?,?,?,?)",
                   (invoice, int(user["id"]), int(product[2]), "pending", 0, None, datetime.now().isoformat(), product[0], None, 0))
        db.commit()
        card = db.execute("SELECT value FROM settings WHERE key='card_number'").fetchone()
        owner = db.execute("SELECT value FROM settings WHERE key='card_owner'").fetchone()
        card_number = card[0] if card else "ثبت نشده"
        card_owner = owner[0] if owner else "ثبت نشده"
    except Exception:
        db.rollback()
        logging.exception("ساخت فاکتور از Mini App ناموفق بود")
        return jsonify({"ok": False, "error": "ساخت فاکتور انجام نشد؛ دوباره تلاش کنید."}), 500
    finally:
        db.close()
    try:
        bot.send_message(int(user["id"]),
            "✅ <b>فاکتور خرید شما ساخته شد!</b>\n\n"
            "🧾 شماره فاکتور: <code>{}</code>\n📦 محصول: {}\n💳 مبلغ: {:,} تومان\n\n"
            "💳 شماره کارت: <code>{}</code>\n👤 صاحب کارت: {}\n\n"
            "🔵 لطفاً رسید پرداخت را همین‌جا در گفت‌وگوی ربات ارسال کنید.".format(
                invoice, product[1], int(product[2]), card_number, card_owner), reply_markup=invoice_keyboard)
    except Exception:
        logging.exception("ارسال جزئیات فاکتور به کاربر ناموفق بود")
        return jsonify({"ok": False, "error": "فاکتور ساخته شد اما پیام بات ارسال نشد. ربات را باز کنید و دوباره /start بزنید."}), 502
    return jsonify({"ok": True, "invoice": invoice, "message": "فاکتور در گفت‌وگوی ربات ارسال شد."})

def run_mini_app_server():
    port = int(os.getenv("PORT", "8080"))
    serve(mini_app, host="0.0.0.0", port=port, threads=4)

print("=" * 50)
print("🚀 ربات آماده اجرا است")
print("👤 رسیدها به صورت خودکار به آیدی {} ارسال می‌شوند".format(YOUR_PRIVATE_ID))
print("📝 دستورات:")
print("   /start - شروع ربات")
print("   /help - راهنمایی")
print("   /support - پشتیبانی")

print("=" * 50)

if MINI_APP_URL:
    threading.Thread(target=run_mini_app_server, daemon=True).start()
    logging.info("Mini App server enabled on port %s", os.getenv("PORT", "8080"))
else:
    logging.warning("MINI_APP_URL تنظیم نشده؛ دکمه مینی‌اپ در ربات نمایش داده نمی‌شود")

try:
    bot.set_my_commands([
        types.BotCommand("start", "شروع / استارت مجدد"),
        types.BotCommand("myid", "نمایش پروفایل کاربر"),
        types.BotCommand("admin", "پنل مدیریت (فقط مدیر)"),
    ])
except Exception as e:
    logging.warning("ثبت منوی دستورات انجام نشد: %s", e)

bot.infinity_polling(skip_pending=True)