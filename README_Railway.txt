SabzNet Telegram Bot - Railway

Files:
- SabzNet_admin.py : bot source
- requirements.txt : Python dependencies

Railway settings:
- Start command: python SabzNet_admin.py
- Variables:
  BOT_TOKEN = (your new Telegram bot token)
  ADMIN_IDS = 9158813748
  OWNER_CHAT_ID = 9158813748
  DATABASE_PATH = /data/sales.db
- Add a Railway Volume and mount it at /data to persist the SQLite database.

Admin panel:
Use /admin. Includes products, add product, broadcast, stats, card settings,
coupon creation, database backup/restore, and editing welcome/support/config texts.
Use /coupon CODE after creating a pending invoice to apply a discount.

Important:
Telegram Bot API does not allow bots to set custom colors for keyboard buttons.
The requested blue/green button colors cannot be enforced by the bot; Telegram
renders keyboard colors according to the user's app theme.

Restore:
Upload a .db/.sqlite file as a document from the admin restore flow. A safety
backup is created alongside the database before replacement. Restart the
Railway service after the bot confirms the restore upload.
