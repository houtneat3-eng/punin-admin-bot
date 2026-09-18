import logging
import secrets
from datetime import datetime, timedelta
import requests
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)
from apscheduler.schedulers.background import BackgroundScheduler

# --- CONFIGURATIONS ---
TELEGRAM_BOT_TOKEN = "8695678508:AAHQVjDn0fU17Ns7Akn4pELiVAWj5SJjqEg"  # ដាក់ Token Bot របស់អ្នកនៅទីនេះ
ADMIN_CHAT_ID = "7121558503"            # ដាក់ Chat ID របស់អ្នក
FIREBASE_URL = "https://punin-mobile-unlock-default-rtdb.asia-southeast1.firebasedatabase.app"

# Setup Logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Tracked users to prevent duplicate notifications
notified_users = set()

# --- DATABASE FUNCTIONS ---
def db_get(path):
    try:
        res = requests.get(f"{FIREBASE_URL}/{path}.json", timeout=5)
        return res.json() or {}
    except Exception:
        return {}

def db_put(path, data):
    try:
        res = requests.put(f"{FIREBASE_URL}/{path}.json", json=data, timeout=5)
        return res.ok
    except Exception:
        return False

def db_delete(path):
    try:
        res = requests.delete(f"{FIREBASE_URL}/{path}.json", timeout=5)
        return res.ok
    except Exception:
        return False

def generate_random_key(duration_label="1Y"):
    p1, p2 = secrets.token_hex(2).upper(), secrets.token_hex(2).upper()
    return f"PUNIN-{duration_label}-{p1}-{p2}"

def calculate_expiry(duration_choice):
    now = datetime.now()
    if duration_choice == "3M":
        return (now + timedelta(days=90)).strftime("%Y-%m-%d"), "3M"
    elif duration_choice == "6M":
        return (now + timedelta(days=180)).strftime("%Y-%m-%d"), "6M"
    elif duration_choice == "1Y":
        return (now + timedelta(days=365)).strftime("%Y-%m-%d"), "1Y"
    elif duration_choice == "LIFE":
        return "2099-12-31", "LIFE"
    else:
        return (now + timedelta(days=365)).strftime("%Y-%m-%d"), "1Y"

# --- BACKGROUND JOB: CHECK NEW PENDING USERS ---
async def check_new_pending_users(app):
    global notified_users
    users = db_get("pending_users")
    if not users or not isinstance(users, dict):
        return

    for username, data in users.items():
        if username not in notified_users:
            notified_users.add(username)
            email = data.get("email", "N/A")

            keyboard = [
                [
                    InlineKeyboardButton("✅ 3 ខែ", callback_data=f"app_3M_{username}"),
                    InlineKeyboardButton("✅ 6 ខែ", callback_data=f"app_6M_{username}"),
                ],
                [
                    InlineKeyboardButton("✅ 1 ឆ្នាំ", callback_data=f"app_1Y_{username}"),
                    InlineKeyboardButton("✅ Lifetime", callback_data=f"app_LIFE_{username}"),
                ],
                [InlineKeyboardButton("❌ Reject / Delete", callback_data=f"rej_{username}")],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            message = (
                f"🚨 **មាន User ថ្មីចុះឈ្មោះរង់ចាំការអនុម័ត!**\n\n"
                f"👤 Username: `{username}`\n"
                f"📧 Email: `{email}`\n\n"
                f"សូមជ្រើសរើសរយៈពេលខាងក្រោមដើម្បី Approve:"
            )

            try:
                await app.bot.send_message(
                    chat_id=ADMIN_CHAT_ID, text=message, parse_mode="Markdown", reply_markup=reply_markup
                )
            except Exception as e:
                logger.error(f"Error sending notification: {e}")

# --- TELEGRAM COMMANDS ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤖 Admin Bot កំពុងដំណើរការធម្មតា! ប្រើប្រាស់ /pending ដើម្បីមើលបញ្ជីរង់ចាំ។")

async def pending_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    users = db_get("pending_users")
    if not users:
        await update.message.reply_text("⏳ គ្មានអ្នកចុះឈ្មោះរង់ចាំ (Pending) ទេបច្ចុប្បន្ន។")
        return

    for username, data in users.items():
        email = data.get("email", "N/A")
        keyboard = [
            [
                InlineKeyboardButton("✅ 3ខែ", callback_data=f"app_3M_{username}"),
                InlineKeyboardButton("✅ 6ខែ", callback_data=f"app_6M_{username}"),
                InlineKeyboardButton("✅ 1ឆ្នាំ", callback_data=f"app_1Y_{username}"),
            ],
            [
                InlineKeyboardButton("✅ Life", callback_data=f"app_LIFE_{username}"),
                InlineKeyboardButton("❌ Delete", callback_data=f"rej_{username}"),
            ],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            f"👤 User: `{username}`\n📧 Email: `{email}`", parse_mode="Markdown", reply_markup=reply_markup
        )

# --- HANDLE BUTTON CLICKS (APPROVE / REJECT) ---
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data_parts = query.data.split("_")
    action = data_parts[0]

    if action == "app":
        dur_code = data_parts[1]
        username = "_".join(data_parts[2:])

        pending_users = db_get("pending_users")
        if not pending_users or username not in pending_users:
            await query.edit_message_text(text=f"⚠️ រកមិនឃើញទិន្នន័យរបស់ {username} ឬត្រូវបានលុបួជារួចហើយ។")
            return

        user_data = pending_users[username]
        exp_date, code = calculate_expiry(dur_code)
        activation_key = generate_random_key(code)

        approved_payload = {
            "email": user_data["email"],
            "password": user_data["password"],
            "license_key": activation_key,
            "duration": dur_code,
            "expiry_date": exp_date,
            "status": "ACTIVE",
            "activated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

        if db_put(f"approved_users/{username}", approved_payload):
            db_delete(f"pending_users/{username}")
            if username in notified_users:
                notified_users.remove(username)

            await query.edit_message_text(
                text=f"✅ **បានអនុម័តជោគជ័យសម្រាប់ {username}!**\n\n"
                f"- រយៈពេល: {dur_code}\n"
                f"- ផុតកំណត់: {exp_date}\n"
                f"- License Key: `{activation_key}`",
                parse_mode="Markdown",
            )
        else:
            await query.edit_message_text(text="❌ មានបញ្ហាในการភ្ជាប់ Firebase Database!")

    elif action == "rej":
        username = "_".join(data_parts[1:])
        if db_delete(f"pending_users/{username}"):
            if username in notified_users:
                notified_users.remove(username)
            await query.edit_message_text(text=f"❌ បានលុប/បដិសេធ (Reject) គណនី {username} រួចរាល់។")
        else:
            await query.edit_message_text(text="❌ មានបញ្ហាในการលុបទិន្នន័យ!")

# --- MAIN PROGRAM ---
def main():
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("pending", pending_command))
    app.add_handler(CallbackQueryHandler(button_handler))

    scheduler = BackgroundScheduler()
    scheduler.add_job(
        lambda: app.job_queue.run_once(lambda ctx: check_new_pending_users(app), 0),
        "interval",
        seconds=10,
    )
    scheduler.start()

    print("🤖 Telegram Admin Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()