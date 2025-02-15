from telegram.ext import ApplicationBuilder
from dotenv import load_dotenv
import os
from bot.handlers.start import get_conv_handler as start_conv
from bot.handlers.residents import get_conv_handler as residents_conv
from bot.handlers.bonuses import get_handlers as bonus_handlers
from bot.handlers.help import get_handlers as help_handlers  # Добавлено
from bot.repo.database import db

load_dotenv()

async def post_init(app):
    await db.connect()

def main():
    app = ApplicationBuilder().token(os.getenv("BOT_TOKEN")).post_init(post_init).build()

    # Регистрация обработчиков
    app.add_handler(start_conv())
    app.add_handler(residents_conv())
    for handler in bonus_handlers():
        app.add_handler(handler)

    # Добавление обработчиков помощи (добавлено)
    for handler in help_handlers():
        app.add_handler(handler)

    app.run_polling()

if __name__ == "__main__":
    main()