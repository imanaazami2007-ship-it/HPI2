سبزنت - اصلاح ارسال کیبورد پنل‌ها

این نسخه مشکل مهم ارسال reply_markup را اصلاح می‌کند:
در نسخه قبلی، کیبوردهای inline به شکل dict خام به pyTelegramBotAPI داده می‌شدند؛ در نسخه 4.26 این مقدار می‌تواند به شکل نامعتبر در درخواست فرم ارسال شود. اکنون تمام کیبوردهای ساخته‌شده با helper به JSON معتبر تبدیل می‌شوند.

فایل اجرا: SabzNet_admin.py
Procfile: worker: python SabzNet_admin.py

Railway Variables:
BOT_TOKEN=توکن جدید بات
ADMIN_IDS=9158813748
OWNER_CHAT_ID=9158813748
DATABASE_PATH=/data/sales.db

Volume mount path: /data

توکن داخل سورس نیست. قبل از deploy مطمئن شوید Procfile و SabzNet_admin.py در ریشه مخزن باشند و نسخه قدیمی main.py به عنوان Start Command اجرا نشود.

پنل اصلی: آبی (primary)
پنل مدیریت: سبز (success)
عملیات حذف/رد: قرمز (danger)
دستورات: /start /myid /admin

تست‌های محلی: کامپایل پایتون، بررسی JSON کیبوردهای اصلی و مدیریتی، بررسی ZIP. اجرای زنده Railway نیازمند deploy است.
