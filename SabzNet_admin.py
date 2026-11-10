import telebot
from telebot import types
import sqlite3
import random
import os
from datetime import datetime
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)

# ================== تنظیمات ==================
TOKEN = os.getenv("BOT_TOKEN", "").strip()
if not TOKEN:
    raise RuntimeError("متغیر BOT_TOKEN در تنظیمات محیطی تعریف نشده است.")

ADMIN_IDS = [
    int(value.strip())
    for value in os.getenv("ADMIN_IDS", "9158813748").split(",")
    if value.strip()
]
OWNER_CHAT_ID = os.getenv("OWNER_CHAT_ID", "").strip()
OWNER_CHAT_ID = int(OWNER_CHAT_ID) if OWNER_CHAT_ID else None
CONFIG_IMAGE_PATH = os.getenv("CONFIG_IMAGE_PATH", "photo_5771850719550967090_y.jpg")
PAYMENT_CARD_NUMBER = os.getenv("PAYMENT_CARD_NUMBER", "").strip()
PAYMENT_CARD_OWNER = os.getenv("PAYMENT_CARD_OWNER", "").strip()
CONFIG_SUBSCRIPTION_LINK = os.getenv("CONFIG_SUBSCRIPTION_LINK", "").strip()

# اجرای تک‌نخی برای جلوگیری از تداخل cursor مشترک SQLite در هندلرها
bot = telebot.TeleBot(TOKEN, parse_mode="HTML", threaded=False)

# ================== دیتابیس ==================
DATABASE_PATH = os.getenv("DATABASE_PATH", "sales.db")
database_dir = os.path.dirname(os.path.abspath(DATABASE_PATH))
os.makedirs(database_dir, exist_ok=True)
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
    active INTEGER DEFAULT 1
)
""")
# تنظیمات قابل تغییر از پنل مدیریت (در دیتابیس ذخیره می‌شوند)
cur.execute("CREATE TABLE IF NOT EXISTS app_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL DEFAULT '')")
cur.execute("INSERT OR IGNORE INTO app_settings(key,value) VALUES ('payment_card_number',?)", (PAYMENT_CARD_NUMBER,))
cur.execute("INSERT OR IGNORE INTO app_settings(key,value) VALUES ('payment_card_owner',?)", (PAYMENT_CARD_OWNER,))
conn.commit()

def get_setting(key, fallback=''):
    row = cur.execute("SELECT value FROM app_settings WHERE key=?", (key,)).fetchone()
    return row[0] if row else fallback

def set_setting(key, value):
    cur.execute("INSERT INTO app_settings(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
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
        rows.append([types.InlineKeyboardButton(
            "{} {} | {:,} تومان".format(icon or "🛍️", title, price),
            callback_data="prod_{}".format(pid), style="success")])
    kb = types.InlineKeyboardMarkup()
    for row in rows:
        kb.row(*row)
    return kb

def show_products(chat_id, service):
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

# ================== ارسال خودکار به شما ==================
def send_receipt_to_owner_automatically(file_id, invoice, user_id, amount, service):
    if not OWNER_CHAT_ID:
        logging.warning("OWNER_CHAT_ID تنظیم نشده؛ رسید برای مالک ارسال نشد.")
        return False
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
        
        if not OWNER_CHAT_ID:
            logging.warning("OWNER_CHAT_ID تنظیم نشده؛ ارسال رسید به مالک انجام نشد.")
            return False
        bot.send_photo(OWNER_CHAT_ID, file_id, caption=caption)
        logging.info("✅ رسید {} به مالک ارسال شد".format(invoice))
        return True
        
    except Exception as e:
        logging.error("❌ خطا در ارسال خودکار: {}".format(e))
        
        try:
            if not OWNER_CHAT_ID:
                return False
            bot.send_message(
                OWNER_CHAT_ID,
                "📋 <b>رسید تایید شده</b>\n"
                "⏰ {}\n"
                "━━━━━━━━━━━━━━━━\n"
                "💳 فاکتور: {}\n"
                "👤 کاربر: {}\n"
                "💰 مبلغ: {:,} تومان\n"
                "📦 سرویس: {}\n"
                "⚠️ ارسال عکس با خطا مواجه شد".format(
                    datetime.now().strftime('%Y/%m/%d %H:%M'),
                    invoice, user_id, amount, service
                )
            )
            return True
        except Exception as e2:
            logging.error("❌ خطا در ارسال متن: {}".format(e2))
            return False

# ================== کیبوردها ==================
def main_keyboard(user_id=None):
    # کیبورد ثابت پایین صفحه فقط برای ناوبری است.
    # دکمه مدیریت فقط برای شناسه‌های مدیر نمایش داده می‌شود.
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("🚀 شروع", "👤 پروفایل")
    if user_id in ADMIN_IDS:
        kb.row("🛠 مدیریت")
    return kb


def services_keyboard():
    # کاشی‌های خدمات با رنگ آبی اصلی تلگرام؛ آیکون‌ها به ایموجی‌های قبلی برگردانده شدند.
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("🔥 کانفیگ اختصاصی", callback_data="svc_config", style="primary"),
        types.InlineKeyboardButton("💎 پرمیوم", callback_data="svc_premium", style="primary"),
        types.InlineKeyboardButton("🤖 سلف و تبچی", callback_data="svc_self", style="primary"),
        types.InlineKeyboardButton("♻️ شماره مجازی", callback_data="svc_virtual", style="primary"),
        types.InlineKeyboardButton("💫 استارز", callback_data="svc_stars", style="primary"),
        types.InlineKeyboardButton("🎁 گیفت استارزی", callback_data="svc_gift", style="primary"),
        types.InlineKeyboardButton("☎️ پشتیبانی", callback_data="svc_support", style="primary"),
    )
    return kb

invoice_keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
invoice_keyboard.add("لغو", "منوی اصلی")

plan_keyboard = types.InlineKeyboardMarkup()
plan_keyboard.add(types.InlineKeyboardButton("🥇 ویژه | 1 ماه | 99.000 تومان", callback_data="plan_99000_config", style="success"))
plan_keyboard.add(types.InlineKeyboardButton("🥇 ویژه | 3 ماه | 199.000 تومان", callback_data="plan_199000_config", style="success"))
plan_keyboard.add(types.InlineKeyboardButton("🥇 ویژه | 6 ماه | 299.000 تومان", callback_data="plan_299000_config", style="success"))

premium_keyboard = types.InlineKeyboardMarkup()
premium_keyboard.add(types.InlineKeyboardButton("💎 پرمیوم | 1 ماهه | 850,000 تومان", callback_data="plan_850000_premium", style="success"))
premium_keyboard.add(types.InlineKeyboardButton("💎 پرمیوم | 3 ماهه | 2,250,000 تومان", callback_data="plan_2250000_premium", style="success"))
premium_keyboard.add(types.InlineKeyboardButton("💎 پرمیوم | 6 ماهه | 2,900,000 تومان", callback_data="plan_2900000_premium", style="success"))
premium_keyboard.add(types.InlineKeyboardButton("💎 پرمیوم | 12 ماهه | 5,200,000 تومان", callback_data="plan_5200000_premium", style="success"))

self_keyboard = types.InlineKeyboardMarkup()
self_keyboard.add(types.InlineKeyboardButton("🤖 فعالسازی با آیدی | 120,000 تومان", callback_data="plan_120000_self", style="success"))
self_keyboard.add(types.InlineKeyboardButton("🤖 فعالسازی با ورود به حساب | 95,000 تومان", callback_data="plan_95000_self", style="success"))

virtual_keyboard = types.InlineKeyboardMarkup()
virtual_keyboard.add(types.InlineKeyboardButton("🥇 کشور فیجی | 300,000 تومان", callback_data="plan_300000_virtual", style="success"))
virtual_keyboard.add(types.InlineKeyboardButton("🥈 کشور آمریکا | 95,000 تومان", callback_data="plan_95000_virtual", style="success"))

stars_keyboard = types.InlineKeyboardMarkup()
stars_keyboard.add(types.InlineKeyboardButton("⭐️ 50 استارز | 180,000 تومان", callback_data="plan_180000_stars", style="success"))
stars_keyboard.add(types.InlineKeyboardButton("⭐️ 75 استارز | 240,000 تومان", callback_data="plan_240000_stars", style="success"))
stars_keyboard.add(types.InlineKeyboardButton("⭐️ 100 استارز | 320,000 تومان", callback_data="plan_320000_stars", style="success"))
stars_keyboard.add(types.InlineKeyboardButton("⭐️ 150 استارز | 455,000 تومان", callback_data="plan_455000_stars", style="success"))
stars_keyboard.add(types.InlineKeyboardButton("⭐️ 250 استارز | 770,000 تومان", callback_data="plan_770000_stars", style="success"))
stars_keyboard.add(types.InlineKeyboardButton("⭐️ 500 استارز | 1,500,000 تومان", callback_data="plan_1500000_stars", style="success"))

gift_stars_keyboard = types.InlineKeyboardMarkup(row_width=3)
gift_stars_keyboard.add(
    types.InlineKeyboardButton("🌹", callback_data="plan_45000_gift_15", style="success"),
    types.InlineKeyboardButton("45,000 تومان", callback_data="plan_45000_gift_15", style="success"),
    types.InlineKeyboardButton("15 ⭐", callback_data="plan_45000_gift_15", style="success")
)
gift_stars_keyboard.add(
    types.InlineKeyboardButton("🌷", callback_data="plan_72000_gift_25", style="success"),
    types.InlineKeyboardButton("72,000 تومان", callback_data="plan_72000_gift_25", style="success"),
    types.InlineKeyboardButton("25 ⭐", callback_data="plan_72000_gift_25", style="success")
)
gift_stars_keyboard.add(
    types.InlineKeyboardButton("🌸", callback_data="plan_145000_gift_50", style="success"),
    types.InlineKeyboardButton("145,000 تومان", callback_data="plan_145000_gift_50", style="success"),
    types.InlineKeyboardButton("50 ⭐", callback_data="plan_145000_gift_50", style="success")
)
gift_stars_keyboard.add(
    types.InlineKeyboardButton("💐", callback_data="plan_290000_gift_100", style="success"),
    types.InlineKeyboardButton("290,000 تومان", callback_data="plan_290000_gift_100", style="success"),
    types.InlineKeyboardButton("100 ⭐", callback_data="plan_290000_gift_100", style="success")
)

support_keyboard = types.InlineKeyboardMarkup()
support_keyboard.add(types.InlineKeyboardButton("👩🏻‍💻 پیام به پشتیبانی", url="https://t.me/DFG_1819", style="success"))

# ================== متن‌ها ==================
CONFIG_TEXT = (
    "فیلترشکن ویژه سبزنت:\n\n"
    "بروزرسانی و اتصال در اینترنت ملی\n"
    "سرور های مجزا با لوکیشن های مختلف\n"
    "سرعت و پایداری بیشتر\n"
    "حذف تبلیغات یوتیوب, ساندکلاد و باقی پلتفرم ها\n"
    "بدون محدودیت حجم\n"
    "دو کاربر همزمان\n"
    "بروزرسانی روزانه + پشتیبانی\n\n"
    "👇 مدت زمان سرویس را انتخاب کنید\n"
)

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
    "👩🏻‍💻 <b>پشتیبانی سبز نت</b> = @DFG_1819\n\n"
    "@ir_SabzNet | کانال اطلاع رسانی\n"
)

HELP_TEXT = (
    "جهت دریافت راهنمایی و سرویس به مشکل خورده به پشتیبانی پیام دهید!\n\n"
    "⚠️ : لطفاً از پیام بی مورد خوداری کنید و صبور باشید.\n\n"
    "با سبزنت، بهترین کیفیت اتصال به اینترنت جهانی را تجربه کن! 🌐\n"
    "@ir_SabzNet\n"
)

TEST_TEXT = (
    "در حال حاضر سرویس تست غیرفعال\n\n"
    "به خاطر شرایط فعلی و محدودیت های شدید اینترنت\n"
    "موقتا امکان اراعه تست وجود ندارد\n"
)

CONFIG_MESSAGE = (
    "🔗 لینک اشتراک شما:\n\n"
    "{}\n\n".format(CONFIG_SUBSCRIPTION_LINK) +
    "با سبزنت، بهترین کیفیت اتصال به اینترنت جهانی را تجربه کن! 🌐\n\n"
    "⚠️ توجه این سرویس دوکاربره می‌باشد!\n\n"
    "@ir_SabzNet\n"
)

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
    bot.send_message(
        msg.chat.id,
        "👋 به ربات سبزنت خوش اومدی\n\n"
        "تو این روزای سخت، ما هواتو داریم 💚\n\n"
        "✅ فیلترشکن پرسرعت، بدون محدودیت و اختلال\n\n"
        "📢 کانال رسمی سبزنت:\n🟢 @ir_SAbzNet",
        reply_markup=main_keyboard(msg.from_user.id)
    )
    bot.send_message(msg.chat.id, "🔷 <b>خدمات سبزنت</b>\nیکی از سرویس‌های زیر را انتخاب کنید:", reply_markup=services_keyboard())

@bot.message_handler(commands=["support"])
def support_command(msg):
    bot.send_message(msg.chat.id, SUPPORT_TEXT, reply_markup=support_keyboard)

@bot.message_handler(commands=["help"])
def help_command(msg):
    bot.send_message(msg.chat.id, HELP_TEXT, reply_markup=support_keyboard)

@bot.message_handler(commands=["test"])
def help_command(msg):
    bot.send_message(msg.chat.id, TEST_TEXT, reply_markup=support_keyboard)

# ================== انتخاب خدمات از کاشی‌های دو ستونه ==================
@bot.callback_query_handler(func=lambda c: c.data.startswith("svc_"))
def service_tile_handler(call):
    register_user(call.from_user)
    service = call.data[4:]
    bot.answer_callback_query(call.id)
    if service == "support":
        bot.send_message(call.message.chat.id, SUPPORT_TEXT, reply_markup=support_keyboard)
    elif service == "gift":
        for gift_service in ("gift_15", "gift_25", "gift_50", "gift_100"):
            show_products(call.message.chat.id, gift_service)
    elif service in {"config", "premium", "self", "virtual", "stars"}:
        show_products(call.message.chat.id, service)


# ================== منو ==================
@bot.message_handler(commands=["admin"])
def admin_command(msg):
    if msg.from_user.id not in ADMIN_IDS:
        return
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("🛍 مدیریت محصولات", callback_data="adm_products", style="success"),
        types.InlineKeyboardButton("➕ افزودن محصول", callback_data="adm_add", style="success"),
        types.InlineKeyboardButton("📢 پیام همگانی", callback_data="adm_broadcast", style="success"),
        types.InlineKeyboardButton("📊 آمار کاربران", callback_data="adm_stats", style="success"),
        types.InlineKeyboardButton("💳 تنظیمات شماره کارت", callback_data="adm_payment", style="success"),
    )
    bot.send_message(msg.chat.id, "🛠 <b>پنل مدیریت سبزنت</b>\n\nاز منوی زیر انتخاب کنید:", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("adm_"))
def admin_panel_callback(call):
    if call.from_user.id not in ADMIN_IDS:
        bot.answer_callback_query(call.id, "دسترسی ندارید", show_alert=True)
        return
    action = call.data[4:]
    bot.answer_callback_query(call.id)

    if action == "products":
        products = cur.execute("SELECT id,service,title,price,icon,active FROM products ORDER BY id").fetchall()
        kb = types.InlineKeyboardMarkup()
        for pid, service, title, price, icon, active in products:
            state = "🟢" if active else "🔴"
            kb.add(types.InlineKeyboardButton(
                "{} {} | {:,} | {}".format(state, title, price, service),
                callback_data="editprod_{}".format(pid), style="success"))
        kb.add(types.InlineKeyboardButton("➕ افزودن محصول", callback_data="adm_add", style="success"))
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

    elif action == "payment":
        card = get_setting("payment_card_number", PAYMENT_CARD_NUMBER)
        owner = get_setting("payment_card_owner", PAYMENT_CARD_OWNER)
        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.add(
            types.InlineKeyboardButton("✏️ ویرایش شماره کارت", callback_data="payset_card", style="success"),
            types.InlineKeyboardButton("🗑 حذف شماره کارت", callback_data="payclear_card", style="success"),
            types.InlineKeyboardButton("✏️ ویرایش نام گیرنده", callback_data="payset_owner", style="success"),
            types.InlineKeyboardButton("🗑 حذف نام گیرنده", callback_data="payclear_owner", style="success"),
        )
        bot.send_message(call.message.chat.id,
            "💳 <b>تنظیمات پرداخت</b>\n\nشماره کارت: <code>{}</code>\nنام گیرنده: <b>{}</b>\n\nبرای حذف یا ویرایش از دکمه‌ها استفاده کن.".format(
                card or "ثبت نشده", owner or "ثبت نشده"), reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data in ("payset_card", "payset_owner", "payclear_card", "payclear_owner"))
def payment_settings_callback(call):
    if call.from_user.id not in ADMIN_IDS:
        bot.answer_callback_query(call.id, "دسترسی ندارید", show_alert=True)
        return
    action = call.data
    bot.answer_callback_query(call.id)
    if action == "payclear_card":
        set_setting("payment_card_number", "")
        bot.send_message(call.message.chat.id, "🗑 شماره کارت حذف شد. از این به بعد در فاکتور نمایش داده نمی‌شود.")
    elif action == "payclear_owner":
        set_setting("payment_card_owner", "")
        bot.send_message(call.message.chat.id, "🗑 نام گیرنده حذف شد. از این به بعد در فاکتور نمایش داده نمی‌شود.")
    elif action == "payset_card":
        ADMIN_STATE[call.from_user.id] = {"state": "payment_card"}
        bot.send_message(call.message.chat.id, "💳 شماره کارت جدید را ارسال کن. برای لغو بنویس: لغو")
    elif action == "payset_owner":
        ADMIN_STATE[call.from_user.id] = {"state": "payment_owner"}
        bot.send_message(call.message.chat.id, "👤 نام صاحب کارت جدید را ارسال کن. برای لغو بنویس: لغو")

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
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("💰 تغییر قیمت", callback_data="setprice_{}".format(pid), style="success"),
        types.InlineKeyboardButton("✏️ تغییر نام", callback_data="settitle_{}".format(pid), style="success"),
        types.InlineKeyboardButton("🎨 تغییر آیکون", callback_data="seticon_{}".format(pid), style="success"),
        types.InlineKeyboardButton("🎟 تغییر استیکر", callback_data="setsticker_{}".format(pid), style="success"),
        types.InlineKeyboardButton("🟢/🔴 فعال/غیرفعال", callback_data="toggle_{}".format(pid), style="success"),
        types.InlineKeyboardButton("🗑 حذف", callback_data="delprod_{}".format(pid), style="success"),
    )
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
        }
        bot.send_message(call.message.chat.id, prompts[action])

@bot.message_handler(commands=["broadcast"])
def broadcast_command(msg):
    if msg.from_user.id not in ADMIN_IDS:
        return
    ADMIN_STATE[msg.from_user.id] = {"state": "broadcast"}
    bot.send_message(msg.chat.id, "📢 متن پیام همگانی را ارسال کن.")

@bot.message_handler(content_types=["text","sticker"], func=lambda m: m.from_user.id in ADMIN_IDS and m.from_user.id in ADMIN_STATE)
def admin_state_handler(msg):
    state_data = ADMIN_STATE.get(msg.from_user.id)
    if not state_data:
        return
    state = state_data["state"]

    if msg.content_type == "text" and msg.text == "لغو":
        ADMIN_STATE.pop(msg.from_user.id, None)
        bot.send_message(msg.chat.id, "❌ عملیات لغو شد.")
        return

    if state in ("payment_card", "payment_owner"):
        if msg.content_type != "text":
            bot.send_message(msg.chat.id, "❌ لطفاً مقدار را به صورت متن ارسال کن.")
            return
        value = msg.text.strip()
        if not value:
            bot.send_message(msg.chat.id, "❌ مقدار خالی قابل ثبت نیست.")
            return
        if state == "payment_card":
            digits = "".join(ch for ch in value if ch.isdigit())
            if len(digits) != 16:
                bot.send_message(msg.chat.id, "❌ شماره کارت باید ۱۶ رقم باشد. دوباره ارسال کن یا لغو بنویس.")
                return
            set_setting("payment_card_number", value)
            answer = "✅ شماره کارت ذخیره شد."
        else:
            if len(value) > 100:
                bot.send_message(msg.chat.id, "❌ نام گیرنده بیش از حد طولانی است.")
                return
            set_setting("payment_card_owner", value)
            answer = "✅ نام گیرنده ذخیره شد."
        ADMIN_STATE.pop(msg.from_user.id, None)
        bot.send_message(msg.chat.id, answer)
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
            service_value = msg.text.strip()
            allowed_services = {"config", "premium", "self", "virtual", "stars",
                                "gift_15", "gift_25", "gift_50", "gift_100"}
            if service_value not in allowed_services:
                bot.send_message(msg.chat.id, "❌ نوع سرویس معتبر نیست. یکی از مقادیر راهنما را وارد کن.")
                return
            state_data["service"] = service_value
            state_data["step"] = 2
            bot.send_message(msg.chat.id, "مرحله 2/4: نام محصول را بفرست.")
        elif step == 2:
            state_data["title"] = msg.text.strip()
            state_data["step"] = 3
            bot.send_message(msg.chat.id, "مرحله 3/4: قیمت را به تومان بفرست.")
        elif step == 3:
            try:
                price = int(msg.text.replace(",", "").replace("٬", "").strip())
                if price <= 0:
                    raise ValueError
            except ValueError:
                bot.send_message(msg.chat.id, "❌ قیمت باید عددی بزرگ‌تر از صفر باشد.")
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
                if value <= 0:
                    raise ValueError
            except ValueError:
                bot.send_message(msg.chat.id, "❌ قیمت باید عددی بزرگ‌تر از صفر باشد.")
                return
            cur.execute("UPDATE products SET price=? WHERE id=?", (value, pid))
        elif state == "settitle":
            cur.execute("UPDATE products SET title=? WHERE id=?", (msg.text.strip(), pid))
        else:
            cur.execute("UPDATE products SET icon=? WHERE id=?", (msg.text.strip(), pid))
        conn.commit()
        ADMIN_STATE.pop(msg.from_user.id, None)
        bot.send_message(msg.chat.id, "✅ تغییرات ذخیره شد.")
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
    if text in ("🚀 شروع", "شروع"):
        start(msg)
        return
    elif text in ("👤 پروفایل", "پروفایل"):
        row = cur.execute(
            "SELECT first_name, username, created_at FROM users WHERE user_id=?",
            (msg.from_user.id,)
        ).fetchone()
        purchases = cur.execute(
            "SELECT COUNT(*) FROM invoices WHERE user_id=? AND status='approved'",
            (msg.from_user.id,)
        ).fetchone()[0]
        if row:
            first_name, username, created_at = row
        else:
            first_name, username, created_at = (msg.from_user.first_name or "", msg.from_user.username or "", datetime.now().isoformat())
        try:
            joined = datetime.fromisoformat(created_at).strftime("%Y/%m/%d")
        except Exception:
            joined = str(created_at)
        username_text = "@{}".format(username) if username else "ندارد"
        profile_text = (
            "👤 <b>پروفایل شما</b>\n\n"
            "🪪 نام: {}\n"
            "🔗 نام کاربری: {}\n"
            "🆔 آیدی عددی: <code>{}</code>\n"
            "📅 تاریخ عضویت: {}\n"
            "🛍 تعداد خریدهای موفق: {}"
        ).format(first_name or "ثبت نشده", username_text, msg.from_user.id, joined, purchases)
        bot.send_message(msg.chat.id, profile_text, reply_markup=main_keyboard(msg.from_user.id))
        return
    elif text in ("🛠 مدیریت", "مدیریت"):
        if msg.from_user.id in ADMIN_IDS:
            admin_command(msg)
        else:
            bot.send_message(msg.chat.id, "⛔️ شما به پنل مدیریت دسترسی ندارید.")
        return
    elif text == "🤖 سلف و تبچی":
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
        bot.send_message(msg.chat.id, SUPPORT_TEXT, reply_markup=support_keyboard)
    elif text in ["لغو", "منوی اصلی"]:
        bot.send_message(msg.chat.id, "🏠", reply_markup=main_keyboard(msg.from_user.id))

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
        "🔵 لطفاً رسید پرداخت را ارسال کنید".format(
            invoice, title, amount, get_setting("payment_card_number", PAYMENT_CARD_NUMBER) or "در تنظیمات ثبت نشده",
            get_setting("payment_card_owner", PAYMENT_CARD_OWNER) or "در تنظیمات ثبت نشده"
        ),
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
    
    try:
        amount = int(amount)
    except (TypeError, ValueError):
        bot.answer_callback_query(call.id, "مبلغ نامعتبر است.", show_alert=True)
        return
    if amount <= 0 or service not in {"config", "premium", "self", "virtual", "stars",
                                      "gift_15", "gift_25", "gift_50", "gift_100"}:
        bot.answer_callback_query(call.id, "پلن نامعتبر است.", show_alert=True)
        return
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
        "🔵 لطفاً رسید پرداخت را ارسال کنید".format(
            invoice, amount, get_setting("payment_card_number", PAYMENT_CARD_NUMBER) or "در تنظیمات ثبت نشده",
            get_setting("payment_card_owner", PAYMENT_CARD_OWNER) or "در تنظیمات ثبت نشده"
        ),
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
        reply_markup=main_keyboard(msg.from_user.id)
    )

    file_id = msg.photo[-1].file_id
    cur.execute(
        "UPDATE invoices SET receipt_sent=1, wait_message_id=?, receipt_file_id=? WHERE invoice=?",
        (wait_msg.message_id, file_id, invoice)
    )
    conn.commit()

    kb = types.InlineKeyboardMarkup()
    kb.add(
        types.InlineKeyboardButton("✅ تأیید پرداخت", callback_data="approve_{}".format(invoice), style="success"),
        types.InlineKeyboardButton("❌ لغو پرداخت", callback_data="reject_{}".format(invoice), style="success")
    )

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
            keyboard = types.InlineKeyboardMarkup()
            keyboard.add(
                types.InlineKeyboardButton(
                    text=service_data["button_text"],
                    url="https://t.me/DFG_1819", style="success")
            )
            
            bot.send_message(
                user_id,
                "{}\n\n@DFG_1819".format(service_data["text"]),
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
            reject_keyboard = types.InlineKeyboardMarkup()
            reject_keyboard.add(
                types.InlineKeyboardButton(
                    text="📞 پیام به پشتیبانی",
                    url="https://t.me/DFG_1819", style="success")
            )
            
            bot.edit_message_text(
                "❌ پرداخت شما رد شد\n\nلطفاً با پشتیبانی تماس بگیرید:\n@DFG_1819",
                chat_id=user_id,
                message_id=wait_msg_id,
                reply_markup=reject_keyboard
            )
        except Exception as e:
            logging.error("خطا در ویرایش پیام رد پرداخت: {}".format(e))
            bot.send_message(user_id, "❌ پرداخت شما رد شد\n\nلطفاً با پشتیبانی تماس بگیرید:\n@DFG_1819")

        try:
            bot.edit_message_caption(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                caption=call.message.caption + "\n❌ پرداخت لغو شد"
            )
        except:
            pass

print("=" * 50)
print("🚀 ربات آماده اجرا است")
if not ADMIN_IDS:
    logging.warning("ADMIN_IDS تنظیم نشده؛ دستورات مدیریتی و بررسی رسیدها در دسترس نخواهند بود.")
print("👤 ارسال خودکار رسید به مالک: {}".format("فعال" if OWNER_CHAT_ID else "غیرفعال"))
print("📝 دستورات:")
print("   /start - شروع ربات")
print("   /help - راهنمایی")
print("   /support - پشتیبانی")
print("=" * 50)

bot.infinity_polling()