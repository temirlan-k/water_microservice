import asyncpg
from dotenv import load_dotenv
import os
import uuid
from datetime import datetime, timedelta

load_dotenv()


class Database:
    def __init__(self):
        """Инициализация базы данных"""
        self.pool = None
        self.db_url = "postgresql://postgres:mysecretpassword@localhost:5440/postgres"

    async def connect(self):
        """Создание пула соединений"""
        if not self.db_url:
            raise ValueError("DATABASE_URL не задан в .env файле")

        if self.pool is None:
            self.pool = await asyncpg.create_pool(self.db_url)
            print("✅ Подключение к базе установлено")

    async def _get_connection(self):
        """Гарантирует подключение и возвращает соединение"""
        if self.pool is None:
            await self.connect()
        return await self.pool.acquire()

    async def user_exists(self, user_id):
        """Проверяет, существует ли пользователь в базе"""
        conn = await self._get_connection()
        try:
            result = await conn.fetchval(
                "SELECT 1 FROM users WHERE user_id = $1", user_id
            )
            return result is not None
        finally:
            await self.pool.release(conn)

    async def add_user(self, user_id, iin, address, phone):
        """Добавление нового пользователя"""
        conn = await self._get_connection()
        try:
            await conn.execute(
                """
                INSERT INTO users (user_id, iin, address, phone) 
                VALUES ($1, $2, $3, $4)
                """,
                user_id, iin, address, phone
            )
        finally:
            await self.pool.release(conn)

    async def update_user(self, user_id, iin, address, phone):
        """Обновление данных пользователя"""
        conn = await self._get_connection()
        try:
            await conn.execute(
                """
                UPDATE users 
                SET iin = $2, address = $3, phone = $4 
                WHERE user_id = $1
                """,
                user_id, iin, address, phone
            )
        finally:
            await self.pool.release(conn)

    async def get_bonus_balance(self, user_id):
        """Получение баланса бонусов"""
        conn = await self._get_connection()
        try:
            balance = await conn.fetchval(
                "SELECT balance FROM bonuses WHERE user_id = $1", user_id
            )
            return balance if balance is not None else 0
        finally:
            await self.pool.release(conn)

    async def generate_qr(self, user_id):
        """Генерация уникального QR-кода с истечением через 1 час"""
        code = str(uuid.uuid4())
        expires_at = datetime.utcnow() + timedelta(hours=1)

        conn = await self._get_connection()
        try:
            await conn.execute(
                """
                INSERT INTO qr_codes (code, user_id, expires_at) 
                VALUES ($1, $2, $3)
                """,
                code, user_id, expires_at
            )
        finally:
            await self.pool.release(conn)

        return code

    async def update_residents(self, user_id, adults, children, renters):
        """Обновление количества жителей и перерасчёт бонусов"""
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

    async def create_couriers(self,full_name,IIN,phone_number,address,email,telegram_id):
        conn = await self._get_connection()
        try:
            await conn.execute(
                """
                INSERT INTO couriers (full_name,IIN,phone_number,address,email,telegram_id) 
                VALUES ($1, $2, $3, $4, $5, $6)
                """,
                full_name,IIN,phone_number,address,email,telegram_id
            )
        finally:
            await self.pool.release(conn)

    async def get_couriers(self):
        conn = await self._get_connection()
        try:
            couriers = await conn.fetch(
                "SELECT * FROM couriers"
            )
            return couriers
        finally:
            await self.pool.release(conn)

    async def get_courier(self,telegram_id):
        conn = await self._get_connection()
        try:
            courier = await conn.fetchrow(
                "SELECT * FROM couriers WHERE telegram_id = $1",telegram_id
            )
            return courier
        finally:
            await self.pool.release(conn)


db = Database()
