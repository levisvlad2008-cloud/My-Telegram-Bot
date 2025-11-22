import os # <-- НУЖНО ДОБАВИТЬ ЭТУ БИБЛИОТЕКУ
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram import F
import asyncio
import aiosqlite
import time
from datetime import datetime, timedelta

# ←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←
# СЕЙЧАС ТОКЕН ЧИТАЕТСЯ ИЗ ПЕРЕМЕННОЙ ОКРУЖЕНИЯ "BOT_TOKEN"
TOKEN = os.getenv("BOT_TOKEN")
# →→→→→→→→→→→→→→→→→→→→→→→→→→→→→→→

bot = Bot(token=TOKEN, parse_mode="HTML")
dp = Dispatcher()

DB_NAME = "rpg_players.db"

# Инициализация базы
async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                perception INTEGER DEFAULT 10,
                energy INTEGER DEFAULT 10,
                last_meditation INTEGER DEFAULT 0
            )
        ''')
        await db.commit()

# Получить или создать игрока
async def get_user(user_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                return {"user_id": row[0], "perception": row[1], "energy": row[2], "last_meditation": row[3]}
            else:
                await db.execute("INSERT INTO users (user_id) VALUES (?)", (user_id,))
                await db.commit()
                return {"user_id": user_id, "perception": 10, "energy": 10, "last_meditation": 0}

# Обновить характеристики и таймер
async def update_user(user_id: int, perception: int, energy: int, last_meditation: int):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            INSERT INTO users(user_id, perception, energy, last_meditation)
            VALUES(?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
            perception = excluded.perception,
            energy = excluded.energy,
            last_meditation = excluded.last_meditation
        """, (user_id, perception, energy, last_meditation))
        await db.commit()

# Клавиатура профиля + медитация
async def profile_keyboard(user_id: int):
    user = await get_user(user_id)
    now = int(time.time())
    cooldown = 3 * 60 * 60  # 3 часа в секундах
    can_meditate = (now - user["last_meditation"]) >= cooldown

    btn_text = "Медитация 🧘‍♂️" if can_meditate else f"Медитация 🔒 ({timedelta(seconds=cooldown - (now - user['last_meditation']))})"
    meditate_btn = InlineKeyboardButton(btn_text, callback_data="meditate")

    keyboard = InlineKeyboardMarkup(inline_keyboard=[[meditate_btn]])
    return keyboard

# ================== ХЕНДЛЕРЫ ==================

@dp.message(Command("start"))
async def start(message: Message):
    await message.answer(
        "<b>Добро пожаловать в систему прокачки!</b>\n\n"
        "Используй /profile, чтобы посмотреть свои характеристики и медитировать.",
        reply_markup=await profile_keyboard(message.from_user.id)
    )

@dp.message(Command("profile"))
async def profile(message: Message):
    user = await get_user(message.from_user.id)
    text = f"""
<b>Твой профиль</b>

Сила: 10/250
Живучесть: 10/250
Защита: 10/250
Ловкость: 10/250
Интеллект: 10/250
Мудрость: 10/250
Харизма: 10/250
<b>Восприятие: {user['perception']}/250</b>
Выносливость: 10/250
<b>Энергия: {user['energy']}/250</b>
Удача: 10/250
    """.strip()

    await message.answer(text, reply_markup=await profile_keyboard(message.from_user.id))

# Нажатие на кнопку Медитация
@dp.callback_query(F.data == "meditate")
async def meditate(callback: CallbackQuery):
    user = await get_user(callback.from_user.id)
    now = int(time.time())
    cooldown = 3 * 60 * 60

    if now - user["last_meditation"] < cooldown:
        left = timedelta(seconds=cooldown - (now - user["last_meditation"]))
        await callback.answer(f"Медитация будет доступна через {left}", show_alert=True)
        return

    # Успешная медитация
    new_perc = min(user["perception"] + 2, 250)
    new_en = min(user["energy"] + 2, 250)

    await update_user(callback.from_user.id, new_perc, new_en, now)

    await callback.answer("Медитация прошла успешно! +2 Восприятие, +2 Энергия", show_alert=True)
    
    # Обновляем сообщение
    user = await get_user(callback.from_user.id)  # обновляем данные
    text = f"""
<b>Твой профиль</b>

Сила: 10/250
Живучесть: 10/250
Защита: 10/250
Ловкость: 10/250
Интеллект: 10/250
Мудрость: 10/250
Харизма: 10/250
<b>Восприятие: {user['perception']}/250</b>
Выносливость: 10/250
<b>Энергия: {user['energy']}/250</b>
Удача: 10/250

🧘‍♂️ Медитация успешна! Следующая через 3 часа.
    """.strip()

    await callback.message.edit_text(text, reply_markup=await profile_keyboard(callback.from_user.id))

# ================== ЗАПУСК ==================
async def main():
    await init_db()
    print("Бот запущен и готов к медитациям 🧘‍♂️")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
