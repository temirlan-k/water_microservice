from telegram import Update
from telegram.ext import ContextTypes, CommandHandler, ConversationHandler, MessageHandler, filters
REGISTER_IIN, REGISTER_ADDRESS, REGISTER_PHONE, VERIFY_CODE = range(4)
from repo.database import db

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Добро пожаловать! Введите ваш ИИН:")
    return REGISTER_IIN

async def register_iin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['iin'] = update.message.text
    await update.message.reply_text("🏠 Введите ваш адрес (ул. Дом.кв):")
    return REGISTER_ADDRESS

async def register_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['address'] = update.message.text
    await update.message.reply_text("📱 Введите ваш телефон:")
    return REGISTER_PHONE

async def register_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Мок SMS верификации: генерируем код 1234
    context.user_data['phone'] = update.message.text
    await update.message.reply_text("🔐 Введите код из SMS (тестовый код: 1234):")
    return VERIFY_CODE

async def verify_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Проверка кода подтверждения и регистрация пользователя"""
    if update.message.text == "1234":
        user_id = update.effective_user.id

        user_exists = await db.user_exists(user_id)

        if user_exists:
            await db.update_user(
                user_id,
                context.user_data['iin'],
                context.user_data['address'],
                context.user_data['phone']
            )
            await update.message.reply_text("✅ Данные обновлены!")
        else:
            await db.add_user(
                user_id,
                context.user_data['iin'],
                context.user_data['address'],
                context.user_data['phone']
            )
            await update.message.reply_text("✅ Регистрация завершена!")

        return ConversationHandler.END
    else:
        await update.message.reply_text("❌ Неверный код. Попробуйте снова.")
        return VERIFY_CODE

def get_conv_handler():
    return ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            REGISTER_IIN: [MessageHandler(filters.TEXT, register_iin)],
            REGISTER_ADDRESS: [MessageHandler(filters.TEXT, register_address)],
            REGISTER_PHONE: [MessageHandler(filters.TEXT, register_phone)],
            VERIFY_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, verify_code)],
        },
        fallbacks=[],
    )