from telegram import Update
from telegram.ext import ContextTypes, CommandHandler
import qrcode
from io import BytesIO
from repo.database import db
async def check_bonus(update: Update, context: ContextTypes.DEFAULT_TYPE):
    balance = await db.get_bonus_balance(update.effective_user.id)
    balance = balance if balance is not None else 0  # Если None, заменяем на 0
    await update.message.reply_text(f"💧 Ваш баланс: {balance} бутылок")


async def use_bonus(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    code = await db.generate_qr(user_id)

    img = qrcode.make(f"WATER:{code}")
    bio = BytesIO()
    img.save(bio, format="PNG")
    bio.seek(0)

    await update.message.reply_photo(
        photo=bio,
        caption="🔑 QR-код действителен 1 час"
    )

def get_handlers():
    return [
        CommandHandler('check_bonus', check_bonus),
        CommandHandler('use_bonus', use_bonus)
    ]