import os
import aiosqlite
import asyncio
import time
from datetime import timedelta

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from aiohttp import web

# --- КОНСТАНТЫ ДЛЯ WEBHOOKS ---
WEB_SERVER_HOST = "0.0.0.0"
WEB_SERVER_PORT = os.getenv("PORT", 8080) # Порт, который будет слушать Vercel/хостинг
WEBHOOK_PATH = "/webhook"
# ВАЖНО: WEBHOOK_URL будет установлена позже, при развертывании на Vercel

# ←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←
TOKEN = os.getenv("BOT_TOKEN")
# →→→→→→→→→→→→→→→→→→→→→→→→→→→→→→→

bot = Bot(token=TOKEN, parse_mode="HTML")
dp = Dispatcher()
DB_NAME = "rpg_players.db"

# --- КОНСТАНТЫ И СПИСКИ (как и раньше) ---
RACES = [
    "Люди", "Эльфы", "Дварфы", "Орки", "Дракониды", "Зверолюди", "Инсектоиды", 
    "Гиганты", "Вампиры", "Оборотни", "Нежить", "Демоны", "Ангелы", "Монстры", 
    "Энты", "Феи", "Холодоки", "Русалки", "Големы", "Химеры", "Астрали", "Наги"
]

DEFAULT_STATS = {
    "strength": 10, "durability": 10, "defense": 10, "agility": 10, 
    "intellect": 10, "wisdom": 10, "charisma": 10, "perception": 10, 
    "stamina": 10, "energy": 10, "luck": 10
}

# --- ФУНКЦИИ БАЗЫ ДАННЫХ (оставляем как в RPG-коде) ---
async def init_db():
    # ... (код init_db остается прежним)
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                strength INTEGER DEFAULT 10,
                durability INTEGER DEFAULT 10,
                defense INTEGER DEFAULT 10,
                agility INTEGER DEFAULT 10,
                intellect INTEGER DEFAULT 10,
                wisdom INTEGER DEFAULT 10,
                charisma INTEGER DEFAULT 10,
                perception INTEGER DEFAULT 10,
                stamina INTEGER DEFAULT 10,
                energy INTEGER DEFAULT 10,
                luck INTEGER DEFAULT 10,
                last_meditation INTEGER DEFAULT 0,
                race TEXT DEFAULT 'Не выбрана',
                magic TEXT DEFAULT 'Не выбрана'
            )
        ''')
        await db.commit()

async def get_user(user_id: int):
    # ... (код get_user остается прежним)
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                keys = list(DEFAULT_STATS.keys()) + ['last_meditation', 'race', 'magic']
                user_data = dict(zip(['user_id'] + keys, row))
                return user_data
            else:
                await db.execute("INSERT INTO users (user_id) VALUES (?)", (user_id,))
                await db.commit()
                return await get_user(user_id)

async def update_user(user_id: int, **kwargs):
    # ... (код update_user остается прежним)
    async with aiosqlite.connect(DB_NAME) as db:
        set_clause = ', '.join([f"{k} = ?" for k in kwargs.keys()])
        values = list(kwargs.values()) + [user_id]
        
        await db.execute(f"UPDATE users SET {set_clause} WHERE user_id = ?", values)
        await db.commit()

# --- ФУНКЦИИ КЛАВИАТУРЫ И ПРОФИЛЯ (оставляем как в RPG-коде) ---
async def profile_keyboard(user_id: int):
    user = await get_user(user_id)
    now = int(time.time())
    cooldown = 3 * 60 * 60
    can_meditate = (now - user["last_meditation"]) >= cooldown

    cooldown_left = timedelta(seconds=cooldown - (now - user['last_meditation']))
    
    meditate_btn = InlineKeyboardButton(
        text="Медитация 🧘‍♂️" if can_meditate else f"Медитация 🔒 ({str(cooldown_left).split('.')[0]})", 
        callback_data="meditate"
    )
    select_btn = InlineKeyboardButton(text="Выбрать Расу/Магию", callback_data="open_select")

    keyboard = InlineKeyboardMarkup(inline_keyboard=[[meditate_btn], [select_btn]])
    return keyboard

def generate_profile_text(user: dict, last_action_message: str = "") -> str:
    text = f"""
<b>Твой профиль</b>

Раса: {user.get('race', 'Не выбрана')}
Магия: {user.get('magic', 'Не выбрана')}

Сила: {user['strength']}/250
Живучесть: {user['durability']}/250
Защита: {user['defense']}/250
Ловкость: {user['agility']}/250
Интеллект: {user['intellect']}/250
Мудрость: {user['wisdom']}/250
Харизма: {user['charisma']}/250
Восприятие: {user['perception']}/250
Выносливость: {user['stamina']}/250
Энергия: {user['energy']}/250
Удача: {user['luck']}/250
{last_action_message}
    """.strip()
    return text

def generate_race_keyboard():
    keyboard = []
    for i in range(0, len(RACES), 2):
        row = []
        row.append(InlineKeyboardButton(text=f"♦️({i+1}) {RACES[i]}", callback_data=f"select_race_{RACES[i]}"))
        if i + 1 < len(RACES):
            row.append(InlineKeyboardButton(text=f"♦️({i+2}) {RACES[i+1]}", callback_data=f"select_race_{RACES[i+1]}"))
        keyboard.append(row)
        
    keyboard.append([InlineKeyboardButton(text="Назад к Профилю", callback_data="back_to_profile")])
    
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

# ================== ХЕНДЛЕРЫ (оставляем как в RPG-коде) ==================

@dp.message(Command("start"))
async def start(message: Message):
    user = await get_user(message.from_user.id)
    await message.answer(
        generate_profile_text(user, "<b>Добро пожаловать в мир Archmage!</b>\nИспользуй /profile, чтобы увидеть характеристики."),
        reply_markup=await profile_keyboard(message.from_user.id)
    )

@dp.message(Command("profile"))
async def profile(message: Message):
    user = await get_user(message.from_user.id)
    await message.answer(generate_profile_text(user), reply_markup=await profile_keyboard(message.from_user.id))

@dp.callback_query(F.data == "meditate")
async def meditate(callback: CallbackQuery):
    user = await get_user(callback.from_user.id)
    now = int(time.time())
    cooldown = 3 * 60 * 60

    if now - user["last_meditation"] < cooldown:
        left = timedelta(seconds=cooldown - (now - user["last_meditation"]))
        await callback.answer(f"Медитация будет доступна через {str(left).split('.')[0]}", show_alert=True)
        return

    new_perc = min(user["perception"] + 2, 250)
    new_en = min(user["energy"] + 2, 250)
    await update_user(callback.from_user.id, perception=new_perc, energy=new_en, last_meditation=now)

    last_action_message = f"🧘 Ты погрузился в глубокую медитацию…\n\n✨ +2 к Энергии ({new_en})\n✨ +2 к Восприятию ({new_perc})\n\nСледующая медитация через 3 часа."
    
    await callback.answer("Медитация прошла успешно!", show_alert=True)
    
    user = await get_user(callback.from_user.id)
    await callback.message.edit_text(
        generate_profile_text(user, last_action_message), 
        reply_markup=await profile_keyboard(callback.from_user.id)
    )

@dp.callback_query(F.data == "open_select")
async def open_select_menu(callback: CallbackQuery):
    await callback.answer()
    text = "<b>Выберите свою Расу:</b>\n\n" + '\n'.join([f"♦️({i+1}) {RACES[i]}" for i in range(len(RACES))])
    
    await callback.message.edit_text(
        text, 
        reply_markup=generate_race_keyboard()
    )

@dp.callback_query(F.data.startswith("select_race_"))
async def process_race_selection(callback: CallbackQuery):
    race = callback.data.replace("select_race_", "")
    await update_user(callback.from_user.id, race=race)

    await callback.answer(f"Твоя Раса установлена: {race}", show_alert=True)
    
    user = await get_user(callback.from_user.id)
    await callback.message.edit_text(
        generate_profile_text(user, f"Раса успешно выбрана: **{race}**."),
        reply_markup=await profile_keyboard(callback.from_user.id)
    )

@dp.callback_query(F.data == "back_to_profile")
async def back_to_profile(callback: CallbackQuery):
    user = await get_user(callback.from_user.id)
    await callback.message.edit_text(
        generate_profile_text(user), 
        reply_markup=await profile_keyboard(callback.from_user.id)
    )

# ================== ФУНКЦИИ ДЛЯ WEBHOOKS (НОВЫЙ БЛОК) ==================

# Хендлер для входящих Webhooks-запросов
async def webhook_handler(request):
    if request.match_info.get('path') != WEBHOOK_PATH.lstrip('/'):
        return web.Response(status=404)
    
    update = types.Update.model_validate(await request.json(), context={"bot": bot})
    await dp.feed_update(bot, update)
    return web.Response()

# Функция запуска Web-сервера
async def start_web_server():
    await init_db()
    
    # Получаем внешний URL, который нам даст Vercel (или другой хостинг)
    # На Vercel этот URL доступен через os.environ['VERCEL_URL'] или другой env-переменной
    # Для простоты, мы будем использовать заглушку. В реальном Vercel это нужно заменить.
    try:
        EXTERNAL_HOSTNAME = os.environ['EXTERNAL_HOSTNAME'] # Vercel часто использует переменные среды
    except KeyError:
        # Для локального тестирования или Render (если он был бы Webhook-friendly)
        print("Внимание: Переменная EXTERNAL_HOSTNAME не найдена. Webhook не будет установлен.")
        return 

    WEBHOOK_URL = f"https://{EXTERNAL_HOSTNAME}{WEBHOOK_PATH}"
    
    # Устанавливаем Webhook в Telegram
    await bot.set_webhook(WEBHOOK_URL)
    print(f"Webhook установлен на: {WEBHOOK_URL}")

    # Запускаем AioHttp Web-сервер
    app = web.Application()
    app.router.add_post(f"/{WEBHOOK_PATH.lstrip('/')}", webhook_handler)

    # Запуск сервера на указанном порту
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, WEB_SERVER_HOST, WEB_SERVER_PORT)
    await site.start()
    
    print(f"Web-сервер запущен на {WEB_SERVER_HOST}:{WEB_SERVER_PORT}")
    
# Главная точка запуска
if __name__ == "__main__":
    try:
        asyncio.run(start_web_server())
    except Exception as e:
        print(f"Ошибка при запуске Webhook-сервера: {e}")
        print("Попробуйте использовать команду 'python bot.py' для запуска.")

