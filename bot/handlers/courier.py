import asyncio
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

# Импорт нашего класса Database (убедитесь, что модуль доступен)
from repo.database import db

# --- Константы для состояний регистрации курьера ---
COURIER_REGISTRATION_FULL_NAME, COURIER_REGISTRATION_IIN, COURIER_REGISTRATION_PHONE, COURIER_REGISTRATION_ADDRESS, COURIER_REGISTRATION_EMAIL = range(5)

# --- Константа для поддержки ---
SUPPORT_QUESTION = 0

# ======== Функции для курьера ========

# Стартовое сообщение для курьера
async def start_courier(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет, курьер!\n"
        "Добро пожаловать в систему доставки.\n\n"
        "Чтобы начать, зарегистрируйтесь командой /register_courier или, если вы уже зарегистрированы, "
        "посмотрите свой профиль командой /my_profile."
    )

# ======== Регистрация курьера ========

async def register_courier_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    # Проверка, зарегистрирован ли курьер уже
    courier = await db.get_courier(telegram_id)
    if courier:
        await update.message.reply_text("Вы уже зарегистрированы!")
        return ConversationHandler.END

    await update.message.reply_text("Введите ваше полное имя:")
    return COURIER_REGISTRATION_FULL_NAME

async def get_courier_full_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['full_name'] = update.message.text
    await update.message.reply_text("Введите ваш ИИН:")
    return COURIER_REGISTRATION_IIN

async def get_courier_iin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['IIN'] = update.message.text
    await update.message.reply_text("Введите ваш номер телефона:")
    return COURIER_REGISTRATION_PHONE

async def get_courier_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['phone_number'] = update.message.text
    await update.message.reply_text("Введите ваш адрес:")
    return COURIER_REGISTRATION_ADDRESS

async def get_courier_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['address'] = update.message.text
    await update.message.reply_text("Введите ваш email:")
    return COURIER_REGISTRATION_EMAIL

async def get_courier_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['email'] = update.message.text
    telegram_id = update.effective_user.id

    # Дополнительная проверка на случай, если курьер успел зарегистрироваться в промежутке
    courier = await db.get_courier(telegram_id)
    if courier:
        await update.message.reply_text("Вы уже зарегистрированы!")
        return ConversationHandler.END

    # Сохраняем данные курьера в базе
    await db.create_couriers(
        context.user_data['full_name'],
        context.user_data['IIN'],
        context.user_data['phone_number'],
        context.user_data['address'],
        context.user_data['email'],
        telegram_id
    )
    await update.message.reply_text("✅ Регистрация прошла успешно! Теперь вы будете автоматически получать заказы.")
    return ConversationHandler.END

async def cancel_registration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Регистрация отменена.")
    return ConversationHandler.END

# ======== Просмотр профиля курьера ========
async def view_courier_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    courier = await db.get_courier(telegram_id)
    if courier:
        profile_text = (
            f"👤 Профиль курьера:\n"
            f"Имя: {courier['full_name']}\n"
            f"ИИН: {courier['iin']}\n"
            f"Телефон: {courier['phone_number']}\n"
            f"Адрес: {courier['address']}\n"
            f"Email: {courier['email']}"
        )
        await update.message.reply_text(profile_text)
    else:
        await update.message.reply_text("Профиль не найден. Пожалуйста, зарегистрируйтесь командой /register_courier.")

# ======== Обработка заказа ========
# Функция-симуляция: курьер получает уведомление о новом заказе
async def order_notification(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # В реальном приложении данные заказа будут получаться из БД или внешней системы
    order_id = 123  # Пример идентификатора заказа
    order_details = (
        f"📦 Новый заказ получен!\n"
        f"Заказ №{order_id}\n"
        f"Клиент: Иван Иванов\n"
        f"Адрес доставки: ул. Пушкина, д. 10\n"
        f"QR-код клиента: 123e4567-e89b-12d3-a456-426614174000\n\n"
        "После доставки подтвердите выполнение заказа командой /confirm_delivery."
    )
    await update.message.reply_text(order_details)

# Функция для подтверждения доставки
async def confirm_delivery(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Здесь в реальном приложении необходимо обновить статус заказа в БД
    await update.message.reply_text("✅ Заказ доставлен! Статус обновлён на 'delivered'.")

# ======== Поддержка для курьеров (ИИ‑техподдержка) ========
async def support_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Опишите вашу проблему или вопрос в службу поддержки:")
    return SUPPORT_QUESTION

async def support_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_query = update.message.text
    # Здесь можно интегрировать обращение к ИИ‑системе для анализа запроса
    # В данном примере возвращается шаблонный ответ
    ai_response = (
        "Это автоматический ответ службы поддержки. "
        "Мы рассмотрим ваш запрос и свяжемся с вами в ближайшее время."
    )
    await update.message.reply_text(ai_response)
    return ConversationHandler.END

async def cancel_support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Обращение в поддержку отменено.")
    return ConversationHandler.END

# ======== Создание conversation handlers для курьера ========
def get_courier_conv_handler():
    registration_conv = ConversationHandler(
        entry_points=[CommandHandler('register_courier', register_courier_entry)],
        states={
            COURIER_REGISTRATION_FULL_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_courier_full_name)],
            COURIER_REGISTRATION_IIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_courier_iin)],
            COURIER_REGISTRATION_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_courier_phone)],
            COURIER_REGISTRATION_ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_courier_address)],
            COURIER_REGISTRATION_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_courier_email)],
        },
        fallbacks=[CommandHandler('cancel', cancel_registration)]
    )

    support_conv = ConversationHandler(
        entry_points=[CommandHandler('support', support_start)],
        states={
            SUPPORT_QUESTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, support_receive)],
        },
        fallbacks=[CommandHandler('cancel', cancel_support)]
    )

    return registration_conv, support_conv

# Функция для регистрации всех handlers, связанных с курьером
def get_courier_handlers():
    registration_conv, support_conv = get_courier_conv_handler()
    return [
        CommandHandler('start_courier', start_courier),
        registration_conv,
        CommandHandler('my_profile', view_courier_profile),
        CommandHandler('order', order_notification),
        CommandHandler('confirm_delivery', confirm_delivery),
        support_conv,
    ]