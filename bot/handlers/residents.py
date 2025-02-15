from telegram import Update
from telegram.ext import ContextTypes, CommandHandler, MessageHandler, filters
from repo.database import db
from telegram.ext import ConversationHandler

# Функция для проверки корректности ввода
def is_valid_number(text):
    try:
        num = int(text)
        return num >= 0  # Число должно быть неотрицательным
    except ValueError:
        return False

async def update_residents(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👪 Введите количество взрослых:")
    return "ADULTS"

async def get_adults(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_valid_number(update.message.text):
        await update.message.reply_text("⚠️ Пожалуйста, введите корректное неотрицательное число для взрослых.")
        return "ADULTS"

    context.user_data['adults'] = int(update.message.text)
    await update.message.reply_text("🧒 Введите количество детей:")
    return "CHILDREN"

async def get_children(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_valid_number(update.message.text):
        await update.message.reply_text("⚠️ Пожалуйста, введите корректное неотрицательное число для детей.")
        return "CHILDREN"

    context.user_data['children'] = int(update.message.text)
    await update.message.reply_text("🏡 Введите количество арендаторов:")
    return "RENTERS"

async def get_renters(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_valid_number(update.message.text):
        await update.message.reply_text("⚠️ Пожалуйста, введите корректное неотрицательное число для арендаторов.")
        return "RENTERS"

    renters = int(update.message.text)
    user_id = update.effective_user.id
    await db.update_residents(
        user_id,
        context.user_data['adults'],
        context.user_data['children'],
        renters
    )
    await update.message.reply_text("✅ Данные обновлены! Бонусы начислены.")
    return ConversationHandler.END

def get_conv_handler():
    return ConversationHandler(
        entry_points=[CommandHandler('update_residents', update_residents)],
        states={
            "ADULTS": [MessageHandler(filters.TEXT, get_adults)],
            "CHILDREN": [MessageHandler(filters.TEXT, get_children)],
            "RENTERS": [MessageHandler(filters.TEXT, get_renters)]
        },
        fallbacks=[]
    )
