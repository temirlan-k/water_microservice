import asyncio
from decimal import Decimal
import os
import uuid
from datetime import datetime, timedelta
from dotenv import load_dotenv

import asyncpg
import openai
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)
from telegram.request import HTTPXRequest

load_dotenv()

# Устанавливаем API-ключ OpenAI из переменной окружения
openai.api_key = os.getenv("OPENAI_API_KEY")

# ========================
# Работа с базой данных
# ========================

class Database:
    def __init__(self):
        self.pool = None
        self.db_url = "postgresql://postgres:mysecretpassword@localhost:5440/postgres"

    async def connect(self):
        if not self.db_url:
            raise ValueError("DATABASE_URL не задан в .env файле")
        if self.pool is None:
            self.pool = await asyncpg.create_pool(self.db_url)
            print("✅ Подключение к базе установлено")

    async def _get_connection(self):
        if self.pool is None:
            await self.connect()
        return await self.pool.acquire()

    async def user_exists(self, user_id):
        conn = await self._get_connection()
        try:
            result = await conn.fetchval("SELECT 1 FROM users WHERE user_id = $1", user_id)
            return result is not None
        finally:
            await self.pool.release(conn)

    async def add_user(self, user_id, iin, address, phone, district):
        conn = await self._get_connection()
        try:
            await conn.execute(
                """
                INSERT INTO users (user_id, iin, address, phone, district)
                VALUES ($1, $2, $3, $4, $5)
                """,
                user_id, iin, address, phone, district
            )
        finally:
            await self.pool.release(conn)

    async def update_user(self, user_id, iin, address, phone, district):
        conn = await self._get_connection()
        try:
            await conn.execute(
                """
                UPDATE users SET iin = $2, address = $3, phone = $4, district = $5
                WHERE user_id = $1
                """,
                user_id, iin, address, phone, district
            )
        finally:
            await self.pool.release(conn)

    async def get_user(self, user_id):
        conn = await self._get_connection()
        try:
            user = await conn.fetchrow("SELECT * FROM users WHERE user_id = $1", user_id)
            return user
        finally:
            await self.pool.release(conn)

    async def get_bonus_balance(self, user_id):
        conn = await self._get_connection()
        try:
            balance = await conn.fetchval("SELECT balance FROM bonuses WHERE user_id = $1", user_id)
            return balance if balance is not None else 0
        finally:
            await self.pool.release(conn)

    async def generate_qr(self, user_id: int, order_id: int):
        code = str(uuid.uuid4())
        expires_at = datetime.utcnow() + timedelta(hours=1)
        conn = await self._get_connection()
        try:
            await conn.execute(
                """
                INSERT INTO qr_codes (code, user_id, order_id, expires_at)
                VALUES ($1, $2, $3, $4)
                """,
                code, user_id, order_id, expires_at
            )
        finally:
            await self.pool.release(conn)
        return code

    async def update_residents(self, user_id, adults, children, renters):
        # Если таблица residents отсутствует, можно закомментировать этот метод
        conn = await self._get_connection()
        try:
            await conn.execute(
                """
                INSERT INTO residents (user_id, adults, children, renters)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (user_id) DO UPDATE
                SET adults = EXCLUDED.adults,
                    children = EXCLUDED.children,
                    renters = EXCLUDED.renters
                """,
                user_id, adults, children, renters
            )
            total_bonus = (adults + children + renters) * 2.5
            await conn.execute(
                """
                INSERT INTO bonuses (user_id, balance)
                VALUES ($1, $2)
                ON CONFLICT (user_id) DO UPDATE
                SET balance = $2
                """,
                user_id, total_bonus
            )
        finally:
            await self.pool.release(conn)

    # Бонусы обновляются только для клиентов (запись в таблице users должна существовать)
    async def add_bonus(self, user_id: int, amount: float):
        if not await self.user_exists(user_id):
            return 0
        conn = await self._get_connection()
        try:
            current = await conn.fetchval("SELECT balance FROM bonuses WHERE user_id = $1", user_id)
            if current is None:
                current = Decimal(0)
            new_balance = current + Decimal(amount)
            await conn.execute(
                """
                INSERT INTO bonuses (user_id, balance)
                VALUES ($1, $2)
                ON CONFLICT (user_id) DO UPDATE
                SET balance = $2
                """,
                user_id, new_balance
            )
            return new_balance
        finally:
            await self.pool.release(conn)

    async def deduct_all_bonus(self, user_id: int):
        conn = await self._get_connection()
        try:
            await conn.execute("UPDATE bonuses SET balance = 0 WHERE user_id = $1", user_id)
            return 0
        finally:
            await self.pool.release(conn)

    async def create_couriers(self, full_name, IIN, phone_number, address, email, telegram_id, district):
        conn = await self._get_connection()
        try:
            await conn.execute(
                """
                INSERT INTO couriers (full_name, IIN, phone_number, address, email, telegram_id, district)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                """,
                full_name, IIN, phone_number, address, email, telegram_id, district
            )
        finally:
            await self.pool.release(conn)

    async def get_courier(self, telegram_id):
        conn = await self._get_connection()
        try:
            courier = await conn.fetchrow("SELECT * FROM couriers WHERE telegram_id = $1", telegram_id)
            return courier
        finally:
            await self.pool.release(conn)

    async def get_client_district(self, user_id):
        conn = await self._get_connection()
        try:
            district = await conn.fetchval("SELECT district FROM users WHERE user_id = $1", user_id)
            return district
        finally:
            await self.pool.release(conn)

    async def match_courier_by_district(self, district):
        conn = await self._get_connection()
        try:
            courier = await conn.fetchrow("SELECT * FROM couriers WHERE district = $1 LIMIT 1", district)
            return courier
        finally:
            await self.pool.release(conn)

    async def create_order(self, user_id, courier_id, description, status="new"):
        conn = await self._get_connection()
        try:
            order_id = await conn.fetchval(
                """
                INSERT INTO orders (user_id, courier_id, description, status, created_at, updated_at)
                VALUES ($1, $2, $3, $4, NOW(), NOW())
                RETURNING id
                """,
                user_id, courier_id, description, status
            )
            return order_id
        finally:
            await self.pool.release(conn)

    async def get_orders_for_courier(self, courier_id):
        conn = await self._get_connection()
        try:
            orders = await conn.fetch(
                """
                SELECT * FROM orders WHERE courier_id = $1 ORDER BY created_at DESC
                """,
                courier_id
            )
            return orders
        finally:
            await self.pool.release(conn)

    async def get_qr_record(self, code: str):
        conn = await self._get_connection()
        try:
            record = await conn.fetchrow("SELECT * FROM qr_codes WHERE code = $1", code)
            return record
        finally:
            await self.pool.release(conn)

    async def get_active_order(self, user_id: int):
        conn = await self._get_connection()
        try:
            order = await conn.fetchrow("SELECT * FROM orders WHERE user_id = $1 AND status = 'new' LIMIT 1", user_id)
            return order
        finally:
            await self.pool.release(conn)

    async def get_qr_by_order(self, order_id: int):
        conn = await self._get_connection()
        try:
            record = await conn.fetchrow("SELECT * FROM qr_codes WHERE order_id = $1", order_id)
            return record
        finally:
            await self.pool.release(conn)

    async def complete_order_by_user(self, user_id: int, courier_id: int):
        conn = await self._get_connection()
        try:
            order = await conn.fetchrow(
                "SELECT * FROM orders WHERE user_id = $1 AND courier_id = $2 AND status = 'new' ORDER BY created_at LIMIT 1",
                user_id, courier_id
            )
            if order:
                await conn.execute(
                    "UPDATE orders SET status = 'done', updated_at = NOW() WHERE id = $1",
                    order['id']
                )
                return order['id']
            else:
                return None
        finally:
            await self.pool.release(conn)

    async def deduct_bonus(self, user_id: int, amount: float):
        conn = await self._get_connection()
        try:
            current = await conn.fetchval("SELECT balance FROM bonuses WHERE user_id = $1", user_id)
            if current is None:
                current = Decimal(0)
            new_balance = current - Decimal(amount)
            if new_balance < 0:
                new_balance = Decimal(0)
            await conn.execute(
                "UPDATE bonuses SET balance = $1 WHERE user_id = $2",
                new_balance, user_id
            )
            return new_balance
        finally:
            await self.pool.release(conn)

db = Database()

# ========================
# Определение состояний для ConversationHandler-ов
# ========================
# Для регистрации клиента
CLIENT_REGISTER_IIN, CLIENT_REGISTER_ADDRESS, CLIENT_REGISTER_PHONE, CLIENT_REGISTER_DISTRICT, CLIENT_VERIFY_CODE = range(5)
# Для регистрации курьера
COURIER_REGISTRATION_FULL_NAME, COURIER_REGISTRATION_IIN, COURIER_REGISTRATION_PHONE, COURIER_REGISTRATION_ADDRESS, COURIER_REGISTRATION_EMAIL, COURIER_REGISTRATION_DISTRICT = range(6)
# Для обновления данных о проживающих
ADULTS, CHILDREN, RENTERS = range(3)
# Для пополнения бонусов
TOPUP_ADULTS, TOPUP_CHILDREN, TOPUP_RENTERS = range(3)
# Псевдо-состояние для ожидания кнопки "Главное меню"
MAIN_MENU_STATE = 100

# ========================
# Функция-помощник для добавления кнопки "Главное меню"
# ========================
def add_main_menu_button(keyboard: list) -> list:
    keyboard.append([InlineKeyboardButton("Главное меню", callback_data="main_menu")])
    return keyboard

# ========================
# Функция для показа главного меню для клиента (динамически добавляем кнопку QR, если есть активный заказ)
# ========================
async def show_client_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    active_order = await db.get_active_order(user_id)
    keyboard = [
        [InlineKeyboardButton("Регистрация клиента", callback_data="client_register")],
        [InlineKeyboardButton("Мой профиль", callback_data="client_profile")],
        [InlineKeyboardButton("Обновить данные", callback_data="client_update")],
        [InlineKeyboardButton("Проверить бонусы", callback_data="client_check_bonus")],
        [InlineKeyboardButton("Сделать заказ", callback_data="client_order")],
        [InlineKeyboardButton("Пополнить бонусы", callback_data="client_topup_bonus")]
    ]
    # Если активный заказ есть, добавляем кнопку получения QR
    if active_order:
        keyboard.insert(4, [InlineKeyboardButton("Получить бонус (QR‑код)", callback_data="client_use_bonus")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    if update.message:
        await update.message.reply_text("Выберите действие:", reply_markup=reply_markup)
    elif update.callback_query:
        await update.callback_query.edit_message_text("Выберите действие:", reply_markup=reply_markup)

# ========================
# Функция для получения ответа от OpenAI
# ========================
async def get_openai_answer(question: str) -> str:
    loop = asyncio.get_event_loop()
    response = await loop.run_in_executor(
        None,
        lambda: openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": question}],
            max_tokens=150,
        )
    )
    return response.choices[0].message.content.strip()

# ========================
# ConversationHandler для пополнения бонусов (доступен только для клиентов)
# ========================
async def topup_bonus_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.callback_query.from_user.id
    if not await db.user_exists(user_id):
        await update.callback_query.answer("Эта функция доступна только для клиентов.", show_alert=True)
        return ConversationHandler.END
    await update.callback_query.answer()
    await update.callback_query.edit_message_text("Введите количество взрослых для пополнения бонусов:")
    return TOPUP_ADULTS

async def topup_get_adults(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_valid_number(update.message.text):
        await update.message.reply_text("⚠️ Введите корректное неотрицательное число для взрослых:")
        return TOPUP_ADULTS
    context.user_data['topup_adults'] = int(update.message.text)
    await update.message.reply_text("Введите количество детей:")
    return TOPUP_CHILDREN

async def topup_get_children(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_valid_number(update.message.text):
        await update.message.reply_text("⚠️ Введите корректное неотрицательное число для детей:")
        return TOPUP_CHILDREN
    context.user_data['topup_children'] = int(update.message.text)
    await update.message.reply_text("Введите количество арендаторов:")
    return TOPUP_RENTERS

async def topup_get_renters(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_valid_number(update.message.text):
        await update.message.reply_text("⚠️ Введите корректное неотрицательное число для арендаторов:")
        return TOPUP_RENTERS
    topup_renters = int(update.message.text)
    user_id = update.effective_user.id
    total_bonus = (context.user_data.get('topup_adults', 0) +
                   context.user_data.get('topup_children', 0) +
                   topup_renters) * 2.5
    new_balance = await db.add_bonus(user_id, total_bonus)
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("Главное меню", callback_data="main_menu")]])
    await update.message.reply_text(
        f"Ваш бонусный баланс пополнен на {total_bonus} литров. Новый баланс: {new_balance} литров.",
        reply_markup=keyboard
    )
    return ConversationHandler.END

def is_valid_number(text):
    try:
        num = int(text)
        return num >= 0
    except ValueError:
        return False

bonus_topup_conv = ConversationHandler(
    entry_points=[CallbackQueryHandler(topup_bonus_start, pattern="^client_topup_bonus$")],
    states={
        TOPUP_ADULTS: [MessageHandler(filters.TEXT & ~filters.COMMAND, topup_get_adults)],
        TOPUP_CHILDREN: [MessageHandler(filters.TEXT & ~filters.COMMAND, topup_get_children)],
        TOPUP_RENTERS: [MessageHandler(filters.TEXT & ~filters.COMMAND, topup_get_renters)],
    },
    fallbacks=[],
)

# ========================
# ConversationHandler для завершения заказа курьером (через скан QR-кода)
# ========================
async def courier_complete_order_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.edit_message_text("Пожалуйста, введите QR код клиента:")
    return 1

async def courier_complete_order_get_qr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    qr_code = update.message.text.strip()
    qr_record = await db.get_qr_record(qr_code)
    if not qr_record:
        await update.message.reply_text("Неверный QR код. Попробуйте ещё раз.")
        return 1
    if datetime.utcnow() > qr_record['expires_at']:
        await update.message.reply_text("QR код истек. Попробуйте ещё раз.")
        return 1
    user_id = qr_record['user_id']
    courier_id = update.effective_user.id
    order_id = await db.complete_order_by_user(user_id, courier_id)
    if order_id is None:
        await update.message.reply_text("Не найден заказ для завершения.")
        return ConversationHandler.END
    new_balance = await db.deduct_all_bonus(user_id)
    await update.message.reply_text(f"Заказ №{order_id} завершен. Бонусный баланс клиента теперь: {new_balance} литров воды.")
    return ConversationHandler.END

courier_complete_conv = ConversationHandler(
    entry_points=[CallbackQueryHandler(courier_complete_order_start, pattern="^courier_complete_order$")],
    states={
        1: [MessageHandler(filters.TEXT & ~filters.COMMAND, courier_complete_order_get_qr)]
    },
    fallbacks=[],
)

# ========================
# Остальные обработчики
# ========================
async def start_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("Клиент", callback_data="role_client")],
        [InlineKeyboardButton("Курьер", callback_data="role_courier")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    if update.message:
        await update.message.reply_text("Выберите вашу роль:", reply_markup=reply_markup)
    elif update.callback_query:
        await update.callback_query.edit_message_text("Выберите вашу роль:", reply_markup=reply_markup)

async def role_selection_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    if data == "role_client":
        keyboard = [
            [InlineKeyboardButton("Регистрация клиента", callback_data="client_register")],
            [InlineKeyboardButton("Мой профиль", callback_data="client_profile")],
            [InlineKeyboardButton("Обновить данные", callback_data="client_update")],
            [InlineKeyboardButton("Проверить бонусы", callback_data="client_check_bonus")],
            [InlineKeyboardButton("Сделать заказ", callback_data="client_order")],
            [InlineKeyboardButton("Пополнить бонусы", callback_data="client_topup_bonus")]
        ]
        # Если у клиента есть активный заказ, добавляем кнопку для получения QR-кода
        if await db.get_active_order(query.from_user.id):
            keyboard.insert(4, [InlineKeyboardButton("Получить бонус (QR‑код)", callback_data="client_use_bonus")])
        keyboard = add_main_menu_button(keyboard)
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("Вы выбрали роль *Клиента*. Выберите действие:", parse_mode="Markdown", reply_markup=reply_markup)
    elif data == "role_courier":
        keyboard = [
            [InlineKeyboardButton("Регистрация курьера", callback_data="courier_register")],
            [InlineKeyboardButton("Мой профиль", callback_data="courier_profile")],
            [InlineKeyboardButton("Заказы", callback_data="courier_orders")],
            [InlineKeyboardButton("Поддержка", callback_data="courier_support")],
            [InlineKeyboardButton("Завершить заказ", callback_data="courier_complete_order")]
        ]
        keyboard = add_main_menu_button(keyboard)
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("Вы выбрали роль *Курьера*. Выберите действие:", parse_mode="Markdown", reply_markup=reply_markup)

async def main_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await start_menu(update, context)

async def courier_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("Регистрация курьера", callback_data="courier_register")],
        [InlineKeyboardButton("Мой профиль", callback_data="courier_profile")],
        [InlineKeyboardButton("Заказы", callback_data="courier_orders")],
        [InlineKeyboardButton("Поддержка", callback_data="courier_support")],
        [InlineKeyboardButton("Завершить заказ", callback_data="courier_complete_order")]
    ]
    keyboard = add_main_menu_button(keyboard)
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("Меню курьера. Выберите действие:", reply_markup=reply_markup)

# --- ConversationHandler для регистрации клиента ---
async def client_register_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if await db.get_courier(query.from_user.id):
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("Главное меню", callback_data="main_menu")]])
        await query.edit_message_text("Вы уже зарегистрированы как курьер, поэтому не можете регистрироваться как клиент!", reply_markup=keyboard)
        return MAIN_MENU_STATE
    await query.edit_message_text("👋 Регистрация клиента\nВведите ваш ИИН:")
    return CLIENT_REGISTER_IIN

async def client_register_iin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['iin'] = update.message.text
    await update.message.reply_text("🏠 Введите ваш адрес (например, ул. Дом, кв):")
    return CLIENT_REGISTER_ADDRESS

async def client_register_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['address'] = update.message.text
    await update.message.reply_text("📱 Введите ваш телефон:")
    return CLIENT_REGISTER_PHONE

async def client_register_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['phone'] = update.message.text
    await update.message.reply_text("🗺️ Введите район вашего проживания:")
    return CLIENT_REGISTER_DISTRICT

async def client_register_district(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['district'] = update.message.text
    await update.message.reply_text("🔐 Введите код из SMS (тестовый код: 1234):")
    return CLIENT_VERIFY_CODE

async def client_verify_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "1234":
        user_id = update.effective_user.id
        if await db.user_exists(user_id):
            await db.update_user(
                user_id,
                context.user_data['iin'],
                context.user_data['address'],
                context.user_data['phone'],
                context.user_data['district']
            )
            response_text = "✅ Данные обновлены! Вы зарегистрированы как клиент."
        else:
            await db.add_user(
                user_id,
                context.user_data['iin'],
                context.user_data['address'],
                context.user_data['phone'],
                context.user_data['district']
            )
            response_text = "✅ Регистрация завершена! Вы зарегистрированы как клиент."
        await update.message.reply_text(response_text)
        await show_client_main_menu(update, context)
        return ConversationHandler.END
    else:
        await update.message.reply_text("❌ Неверный код. Попробуйте снова:")
        return CLIENT_VERIFY_CODE

client_registration_conv = ConversationHandler(
    entry_points=[CallbackQueryHandler(client_register_entry, pattern="^client_register$")],
    states={
        CLIENT_REGISTER_IIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, client_register_iin)],
        CLIENT_REGISTER_ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, client_register_address)],
        CLIENT_REGISTER_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, client_register_phone)],
        CLIENT_REGISTER_DISTRICT: [MessageHandler(filters.TEXT & ~filters.COMMAND, client_register_district)],
        CLIENT_VERIFY_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, client_verify_code)],
        MAIN_MENU_STATE: [CallbackQueryHandler(main_menu_handler, pattern="^main_menu$")]
    },
    fallbacks=[CommandHandler('cancel', lambda update, context: ConversationHandler.END)],
)

# --- ConversationHandler для регистрации курьера ---
async def courier_register_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    print(f"[DEBUG] courier_register_entry: user {query.from_user.id} data: {query.data}")
    await query.answer()
    if await db.user_exists(query.from_user.id):
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("Главное меню", callback_data="main_menu")]])
        await query.edit_message_text("Вы уже зарегистрированы как клиент, поэтому не можете регистрироваться как курьер!", reply_markup=keyboard)
        return MAIN_MENU_STATE
    telegram_id = query.from_user.id
    if await db.get_courier(telegram_id):
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("Главное меню", callback_data="main_menu")]])
        await query.edit_message_text("Вы уже зарегистрированы как курьер!", reply_markup=keyboard)
        return MAIN_MENU_STATE
    await query.edit_message_text("Введите ваше полное имя:")
    return COURIER_REGISTRATION_FULL_NAME

async def courier_get_full_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print(f"[DEBUG] courier_get_full_name: received '{update.message.text}'")
    context.user_data['full_name'] = update.message.text
    await update.message.reply_text("Введите ваш ИИН:")
    return COURIER_REGISTRATION_IIN

async def courier_get_iin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['IIN'] = update.message.text
    await update.message.reply_text("Введите ваш номер телефона:")
    return COURIER_REGISTRATION_PHONE

async def courier_get_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['phone_number'] = update.message.text
    await update.message.reply_text("Введите ваш адрес:")
    return COURIER_REGISTRATION_ADDRESS

async def courier_get_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['address'] = update.message.text
    await update.message.reply_text("Введите ваш email:")
    return COURIER_REGISTRATION_EMAIL

async def courier_get_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['email'] = update.message.text
    await update.message.reply_text("🗺️ Введите район, за которым вы отвечаете:")
    return COURIER_REGISTRATION_DISTRICT

async def courier_get_district(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['district'] = update.message.text
    telegram_id = update.effective_user.id
    if await db.get_courier(telegram_id):
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("Главное меню", callback_data="main_menu")]])
        await update.message.reply_text("Вы уже зарегистрированы!", reply_markup=keyboard)
        return MAIN_MENU_STATE
    await db.create_couriers(
        context.user_data['full_name'],
        context.user_data['IIN'],
        context.user_data['phone_number'],
        context.user_data['address'],
        context.user_data['email'],
        telegram_id,
        context.user_data['district']
    )
    await update.message.reply_text("✅ Регистрация курьера прошла успешно!")
    keyboard = [
        [InlineKeyboardButton("Мой профиль", callback_data="courier_profile")],
        [InlineKeyboardButton("Заказы", callback_data="courier_orders")],
        [InlineKeyboardButton("Поддержка", callback_data="courier_support")],
        [InlineKeyboardButton("Завершить заказ", callback_data="courier_complete_order")]
    ]
    keyboard = add_main_menu_button(keyboard)
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Выберите действие:", reply_markup=reply_markup)
    return ConversationHandler.END

courier_registration_conv = ConversationHandler(
    entry_points=[CallbackQueryHandler(courier_register_entry, pattern="^courier_register$")],
    states={
        COURIER_REGISTRATION_FULL_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, courier_get_full_name)],
        COURIER_REGISTRATION_IIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, courier_get_iin)],
        COURIER_REGISTRATION_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, courier_get_phone)],
        COURIER_REGISTRATION_ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, courier_get_address)],
        COURIER_REGISTRATION_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, courier_get_email)],
        COURIER_REGISTRATION_DISTRICT: [MessageHandler(filters.TEXT & ~filters.COMMAND, courier_get_district)],
        MAIN_MENU_STATE: [CallbackQueryHandler(main_menu_handler, pattern="^main_menu$")]
    },
    fallbacks=[CommandHandler('cancel', lambda update, context: ConversationHandler.END)],
)

# --- ConversationHandler для обновления данных о проживающих (клиент) ---
async def update_residents(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👪 Введите количество взрослых:")
    return ADULTS

async def residents_get_adults(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        adults = int(update.message.text)
        if adults < 0:
            raise ValueError
        context.user_data['adults'] = adults
    except ValueError:
        await update.message.reply_text("⚠️ Введите корректное неотрицательное число для взрослых:")
        return ADULTS
    await update.message.reply_text("🧒 Введите количество детей:")
    return CHILDREN

async def residents_get_children(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        children = int(update.message.text)
        if children < 0:
            raise ValueError
        context.user_data['children'] = children
    except ValueError:
        await update.message.reply_text("⚠️ Введите корректное неотрицательное число для детей:")
        return CHILDREN
    await update.message.reply_text("🏡 Введите количество арендаторов:")
    return RENTERS

async def residents_get_renters(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        renters = int(update.message.text)
        if renters < 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("⚠️ Введите корректное неотрицательное число для арендаторов:")
        return RENTERS
    user_id = update.effective_user.id
    await db.update_residents(
        user_id,
        context.user_data.get('adults', 0),
        context.user_data.get('children', 0),
        renters
    )
    await update.message.reply_text("✅ Данные обновлены! Бонусы начислены.")
    await show_client_main_menu(update, context)
    return ConversationHandler.END

residents_conv = ConversationHandler(
    entry_points=[CommandHandler('update_residents', update_residents)],
    states={
        ADULTS: [MessageHandler(filters.TEXT, residents_get_adults)],
        CHILDREN: [MessageHandler(filters.TEXT, residents_get_children)],
        RENTERS: [MessageHandler(filters.TEXT, residents_get_renters)],
    },
    fallbacks=[CommandHandler('cancel', lambda update, context: ConversationHandler.END)],
)

# ========================
# Дополнительные обработчики (инлайн кнопки)
# ========================
async def client_update_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.edit_message_text(
        "Для обновления данных используйте команду /update_residents.",
        reply_markup=InlineKeyboardMarkup(add_main_menu_button([]))
    )

async def client_check_bonus(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    user_id = update.callback_query.from_user.id
    balance = await db.get_bonus_balance(user_id)
    await update.callback_query.edit_message_text(
        f"Ваш бонусный баланс: {balance} литров воды.",
        reply_markup=InlineKeyboardMarkup(add_main_menu_button([]))
    )

# Обработчик для кнопки "Получить бонус (QR‑код)" теперь проверяет, есть ли активный заказ
async def client_use_bonus(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    user_id = update.callback_query.from_user.id
    order = await db.get_active_order(user_id)
    if not order:
        await update.callback_query.answer("У вас нет активного заказа.", show_alert=True)
        return
    qr_record = await db.get_qr_by_order(order['id'])
    if qr_record:
        code = qr_record['code']
    else:
        code = await db.generate_qr(user_id, order['id'])
    await update.callback_query.edit_message_text(
        f"Ваш QR‑код для получения воды:\n{code}\n(Действителен 1 час)",
        reply_markup=InlineKeyboardMarkup(add_main_menu_button([]))
    )

async def client_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    user_id = update.callback_query.from_user.id
    user = await db.get_user(user_id)
    keyboard = add_main_menu_button([])
    reply_markup = InlineKeyboardMarkup(keyboard)
    if user:
        profile_text = (
            f"👤 Профиль клиента:\n"
            f"ИИН: {user['iin']}\n"
            f"Адрес: {user['address']}\n"
            f"Телефон: {user['phone']}\n"
            f"Район: {user['district']}"
        )
        await update.callback_query.edit_message_text(profile_text, reply_markup=reply_markup)
    else:
        await update.callback_query.edit_message_text(
            "Профиль не найден. Пожалуйста, зарегистрируйтесь как клиент.",
            reply_markup=reply_markup
        )

async def courier_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    telegram_id = update.callback_query.from_user.id
    courier = await db.get_courier(telegram_id)
    keyboard = add_main_menu_button([])
    reply_markup = InlineKeyboardMarkup(keyboard)
    if courier:
        profile_text = (
            f"👤 Профиль курьера:\n"
            f"Имя: {courier['full_name']}\n"
            f"ИИН: {courier['iin']}\n"
            f"Телефон: {courier['phone_number']}\n"
            f"Адрес: {courier['address']}\n"
            f"Email: {courier['email']}\n"
            f"Район: {courier.get('district', 'не указан')}"
        )
        await update.callback_query.edit_message_text(profile_text, reply_markup=reply_markup)
    else:
        await update.callback_query.edit_message_text(
            "Профиль не найден. Зарегистрируйтесь через кнопку 'Регистрация курьера'.",
            reply_markup=reply_markup
        )

async def courier_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    telegram_id = update.callback_query.from_user.id
    courier = await db.get_courier(telegram_id)
    if not courier:
        await update.callback_query.edit_message_text("Профиль не найден. Пожалуйста, зарегистрируйтесь как курьер.")
        return
    orders = await db.get_orders_for_courier(telegram_id)
    if orders:
        message = "📦 Ваши заказы:\n\n"
        for order in orders:
            message += (f"Заказ №{order['id']}\n"
                        f"Описание: {order['description']}\n"
                        f"Статус: {order['status']}\n"
                        f"Создан: {order['created_at']}\n\n")
    else:
        message = "У вас пока нет заказов."
    await update.callback_query.edit_message_text(message, reply_markup=InlineKeyboardMarkup(add_main_menu_button([])))

async def courier_support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.edit_message_text(
        "Опишите вашу проблему для поддержки.\nИспользуйте команду /support для отправки сообщения в поддержку.",
        reply_markup=InlineKeyboardMarkup(add_main_menu_button([]))
    )

async def client_make_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    district = await db.get_client_district(user_id)
    user = await db.get_user(user_id)
    if not district:
        await query.edit_message_text("Ваш район не указан. Пожалуйста, обновите данные или пройдите регистрацию.")
        return
    courier = await db.match_courier_by_district(district)
    if courier:
        description = (f"Заказ воды для клиента {query.from_user.first_name} (ID: {user_id})\n"
                       f"Адрес доставки: {user['address']}\n"
                       f"Район: {district}")
        order_id = await db.create_order(user_id, courier['telegram_id'], description)
        client_message = (f"Ваш заказ (№{order_id}) принят! Курьер {courier['full_name']} "
                          f"(район: {courier.get('district', 'не указан')}) скоро привезет воду. Ожидайте.\n\n"
                          "После создания заказа, чтобы получить QR‑код для получения бонусов, нажмите кнопку 'Получить бонус (QR‑код)'.")
        await query.edit_message_text(client_message)
        await context.bot.send_message(chat_id=courier['telegram_id'], text=description)
    else:
        await query.edit_message_text("К сожалению, курьера в вашем районе не найдено. Попробуйте позже.")

async def order_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    district = await db.get_client_district(user_id)
    user = await db.get_user(user_id)
    if not district:
        await update.message.reply_text("Ваш район не указан. Пожалуйста, обновите данные или пройдите регистрацию.")
        return
    courier = await db.match_courier_by_district(district)
    if courier:
        description = (f"Заказ воды для клиента {update.effective_user.first_name} (ID: {user_id})\n"
                       f"Адрес доставки: {user['address']}\n"
                       f"Район: {district}")
        order_id = await db.create_order(user_id, courier['telegram_id'], description)
        client_message = (f"Ваш заказ (№{order_id}) принят! Курьер {courier['full_name']} "
                          f"(район: {courier.get('district', 'не указан')}) скоро привезет воду. Ожидайте.\n\n"
                          "После создания заказа, чтобы получить QR‑код для получения бонусов, нажмите кнопку 'Получить бонус (QR‑код)'.")
        await context.bot.send_message(chat_id=courier['telegram_id'], text=description)
        await update.message.reply_text(client_message)
    else:
        await update.message.reply_text("К сожалению, курьера в вашем районе не найдено. Попробуйте позже.")

async def complete_order_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Пожалуйста, передайте QR код. Пример: /complete_order <код>")
        return
    qr_code = context.args[0]
    qr_record = await db.get_qr_record(qr_code)
    if not qr_record:
        await update.message.reply_text("Неверный QR код.")
        return
    if datetime.utcnow() > qr_record['expires_at']:
        await update.message.reply_text("QR код истек.")
        return
    user_id = qr_record['user_id']
    courier_id = update.effective_user.id
    order_id = await db.complete_order_by_user(user_id, courier_id)
    if order_id is None:
        await update.message.reply_text("Не найден заказ для завершения.")
        return
    new_balance = await db.deduct_all_bonus(user_id)
    await update.message.reply_text(f"Заказ №{order_id} завершен. Бонусный баланс клиента теперь: {new_balance} литров воды.")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.args:
        question = " ".join(context.args)
        answer = await get_openai_answer(question)
        await update.message.reply_text(answer)
    else:
        help_text = (
            "📚 *Доступные команды:*\n"
            "/start - Главное меню\n"
            "/update_residents - Обновить данные о проживающих\n"
            "/order - Сделать заказ\n"
            "/help - Получить помощь (если добавить вопрос, бот ответит через OpenAI)\n\n"
            "Также вы можете написать ваш вопрос с помощью команды /support."
        )
        await update.message.reply_text(help_text, parse_mode="MarkdownV2")

async def support_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    support_chat_id = -1001234567890  # Замените на реальный ID чата поддержки
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

# ========================
# ConversationHandler для завершения заказа курьером (через QR код)
# ========================
async def courier_complete_order_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.edit_message_text("Пожалуйста, введите QR код клиента:")
    return 1

async def courier_complete_order_get_qr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    qr_code = update.message.text.strip()
    qr_record = await db.get_qr_record(qr_code)
    if not qr_record:
        await update.message.reply_text("Неверный QR код. Попробуйте ещё раз.")
        return 1
    if datetime.utcnow() > qr_record['expires_at']:
        await update.message.reply_text("QR код истек. Попробуйте ещё раз.")
        return 1
    user_id = qr_record['user_id']
    courier_id = update.effective_user.id
    order_id = await db.complete_order_by_user(user_id, courier_id)
    if order_id is None:
        await update.message.reply_text("Не найден заказ для завершения.")
        return ConversationHandler.END
    new_balance = await db.deduct_all_bonus(user_id)
    await update.message.reply_text(f"Заказ №{order_id} завершен. Бонусный баланс клиента теперь: {new_balance} литров воды.")
    return ConversationHandler.END

courier_complete_conv = ConversationHandler(
    entry_points=[CallbackQueryHandler(courier_complete_order_start, pattern="^courier_complete_order$")],
    states={
        1: [MessageHandler(filters.TEXT & ~filters.COMMAND, courier_complete_order_get_qr)]
    },
    fallbacks=[],
)

# ========================
# Основная функция запуска бота
# ========================
async def post_init(app):
    await db.connect()

def main():
    request = HTTPXRequest(connect_timeout=30, read_timeout=30)
    app = ApplicationBuilder().token(os.getenv("BOT_TOKEN")).request(request).post_init(post_init).build()

    # Основные команды
    app.add_handler(CommandHandler('start', start_menu))
    app.add_handler(CommandHandler('order', order_command))
    app.add_handler(CommandHandler('complete_order', complete_order_command))
    app.add_handler(CommandHandler('help', help_command))
    app.add_handler(CommandHandler('support', support_request))
    
    # CallbackQuery для меню и выбора роли
    app.add_handler(CallbackQueryHandler(role_selection_handler, pattern="^role_"))
    app.add_handler(CallbackQueryHandler(main_menu_handler, pattern="^main_menu$"))
    app.add_handler(CallbackQueryHandler(courier_menu_handler, pattern="^courier_menu$"))
    
    # ConversationHandlers
    app.add_handler(client_registration_conv)
    app.add_handler(courier_registration_conv)
    app.add_handler(residents_conv)
    app.add_handler(bonus_topup_conv)
    app.add_handler(courier_complete_conv)
    
    # Inline кнопки для клиента
    app.add_handler(CallbackQueryHandler(client_update_data, pattern="^client_update$"))
    app.add_handler(CallbackQueryHandler(client_check_bonus, pattern="^client_check_bonus$"))
    app.add_handler(CallbackQueryHandler(client_use_bonus, pattern="^client_use_bonus$"))
    app.add_handler(CallbackQueryHandler(client_profile, pattern="^client_profile$"))
    app.add_handler(CallbackQueryHandler(client_make_order, pattern="^client_order$"))
    
    # Inline кнопки для курьера
    app.add_handler(CallbackQueryHandler(courier_profile, pattern="^courier_profile$"))
    app.add_handler(CallbackQueryHandler(courier_orders, pattern="^courier_orders$"))
    app.add_handler(CallbackQueryHandler(courier_support, pattern="^courier_support$"))
    
    print("Бот запущен...")
    app.run_polling()

if __name__ == '__main__':
    main()
