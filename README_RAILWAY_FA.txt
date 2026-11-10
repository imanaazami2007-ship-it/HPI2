ZEUS NEON — بسته آماده استقرار در Railway

ساختار بسته:
- SabzNet_admin.py
- Procfile
- requirements.txt
- index.html (مسیر جایگزین)
- miniapp/index.html (مسیر اصلی مینی‌اپ)

مراحل انتشار:
1) از مخزن GitHub فعلی یک نسخه پشتیبان بگیرید.
2) فایل‌های این بسته را در ریشه همان مخزن قرار دهید و فایل‌های هم‌نام را جایگزین کنید.
3) پوشه miniapp را دقیقاً با همین نام و شامل index.html در ریشه مخزن نگه دارید.
4) تغییرات را Commit/Push کنید و در Railway منتظر پایان Deploy بمانید.
5) در Railway > Variables متغیر MINI_APP_URL باید دقیقاً آدرس دامنه HTTPS همین سرویس باشد؛
   برای نمونه: https://worker-production-cc22.up.railway.app
6) متغیرهای BOT_TOKEN و ADMIN_IDS و سایر متغیرهای فعلی را حذف یا تغییر ندهید.
7) پس از Deploy، در مرورگر این آدرس را آزمایش کنید:
   https://worker-production-cc22.up.railway.app/
   سپس:
   https://worker-production-cc22.up.railway.app/api/products

نکته‌ها:
- Procfile سرویس را با `python SabzNet_admin.py` اجرا می‌کند.
- برنامه پورت عمومی را از متغیر PORT خود Railway می‌خواند.
- این بسته دیتابیس، توکن بات یا اطلاعات محرمانه را شامل نمی‌شود.
- اگر از GitHub استفاده می‌کنید، کل ZIP را به‌صورت یک فایل داخل مخزن آپلود نکنید؛ ابتدا Extract کنید و محتویات را در ریشه مخزن قرار دهید.
