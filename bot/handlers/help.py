from telegram import Update
from telegram.ext import ContextTypes, CommandHandler, MessageHandler, filters
from repo.database import db

HELP_TEXT = """
📚 *Доступные команды:*\n
/start \\- Начать регистрацию\n
/update\\_residents \\- Обновить данные о проживающих\n
/check\\_bonus \\- Проверить баланс бонусов\n
/use\\_bonus \\- Получить QR\\-код для воды\n
/help \\- Получить помощь\n
\n
📨 Напишите ваш вопрос, и мы ответим в ближайшее время\\.
"""

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /help"""
    await update.message.reply_text(HELP_TEXT, parse_mode="MarkdownV2")

async def support_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Пересылка сообщения пользователя в чат поддержки"""
    support_chat_id = -1001234567890  # Замените на ID чата поддержки
    user = update.effective_user

    try:
        await context.bot.forward_message(
            chat_id=support_chat_id,
            from_chat_id=user.id,
            message_id=update.message.message_id
        )
        await update.message.reply_text("✅ Ваше сообщение отправлено в поддержку")
    except Exception as e:
        await update.message.reply_text("❌ Ошибка отправки сообщения")

def get_handlers():
    """Возвращает список обработчиков команд"""
    return [
        CommandHandler('help', help_command),
        MessageHandler(
            filters.TEXT & ~filters.COMMAND & ~filters.Regex(r'^/'),
            support_request
        )
    ]
