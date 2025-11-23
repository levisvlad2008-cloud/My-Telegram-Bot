import os
import aiosqlite
import asyncio
import time
import json
from datetime import timedelta
from typing import List, Optional

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from aiohttp import web

# --- НАСТРОЙКИ СЕРВЕРА WEBHOOKS ---
WEB_SERVER_HOST = "0.0.0.0"
WEB_SERVER_PORT = os.getenv("PORT", 8080)
WEBHOOK_PATH = "/webhook"
TOKEN = os.getenv("BOT_TOKEN")

# --- КОНСТАНТЫ ИГРЫ ---
bot = Bot(token=TOKEN, parse_mode="HTML")
dp = Dispatcher()
DB_NAME = "rpg_players.db"
COOLDOWN_SECONDS = 3 * 60 * 60 # 3 часа
MAX_MAGIC_SLOTS = 4
MAX_STAT = 250

# --- СПИСКИ ИГРЫ ---

RACES = {
    "Люди": [], "Эльфы": ["Темные Эльфы"], "Дварфы": [], "Орки": [], 
    "Дракониды": [], "Зверолюди": [], "Инсектоиды": [], "Гиганты": ["Титаны"], 
    "Вампиры": [], "Оборотни": [], "Нежить": [], "Демоны": ["Багровые", "Суккубы"], 
    "Ангелы": ["Архангелы", "Падшие"], "Монстры": [], "Энты": [], "Феи": [], 
    "Холодоки": [], "Русалки": [], "Големы": [], "Химеры": [], 
    "Астрали": [], "Наги": [],
}

MAGIC_SCHOOLS = {
    "Стихийная": ["Магия огня", "Магия воды", "Магия земли", "Магия воздуха", "Магия молнии", "Магия льда", "Магия природы"],
    "Специальная": ["Магия крови", "Магия металла", "Магия звука", "Магия гравитации"],
    "Высшая": ["Магия времени", "Магия пространства", "Магия разрушения", "Магия созидания", "Магия света", "Магия тьмы"], # Теперь доступна всем
    "Ментальная": ["Магия ментальная", "Магия духовная", "Магия иллюзорная", "Магия усиления", "Магия энергии", "Магия сновидений", "Магия вирусов", "Магия эмоций", "Магия призыва", "Магия некромантия", "Магия превращения", "Магия теней", "Магия печатей"],
    "Особая": ["Антимагия"],
}
ALL_MAGICS = [item for sublist in MAGIC_SCHOOLS.values() for item in sublist]

DEFAULT_STATS = {
    "Сила": 10, "Живучесть": 10, "Защита": 10, "Ловкость": 10, 
    "Интеллект": 10, "Мудрость": 10, "Харизма": 10, "Восприятие": 10, 
    "Выносливость": 10, "Энергия": 10, "Удача": 10
}

# --- ФУНКЦИИ БАЗЫ ДАННЫХ ---

async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                Сила INTEGER DEFAULT 10,
                Живучесть INTEGER DEFAULT 10,
                Защита INTEGER DEFAULT 10,
                Ловкость INTEGER DEFAULT 10,
                Интеллект INTEGER DEFAULT 10,
                Мудрость INTEGER DEFAULT 10,
                Харизма INTEGER DEFAULT 10,
                Восприятие INTEGER DEFAULT 10,
                Выносливость INTEGER DEFAULT 10,
                Энергия INTEGER DEFAULT 10,
                Удача INTEGER DEFAULT 10,
                last_meditation INTEGER DEFAULT 0,
                race TEXT DEFAULT 'Не выбрана',
                magic TEXT DEFAULT '[]', 
                total_stats INTEGER DEFAULT 110
            )
        ''')
        await db.commit()

async def get_user(user_id: int) -> dict:
    async with aiosqlite.connect(DB_NAME) as db:
        keys = list(DEFAULT_STATS.keys()) + ['last_meditation', 'race', 'magic', 'total_stats']
        async with db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                user_data = dict(zip(['user_id'] + keys, row))
                user_data['magic'] = json.loads(user_data['magic'])
                return user_data
            else:
                await db.execute("INSERT INTO users (user_id) VALUES (?)", (user_id,))
                await db.commit()
                return await get_user(user_id)

async def update_user(user_id: int, **kwargs):
    async with aiosqlite.connect(DB_NAME) as db:
        user = await get_user(user_id)
        current_stats = {k: user[k] for k in DEFAULT_STATS.keys()}
        current_stats.update(kwargs)
        
        if 'magic' in kwargs and isinstance(kwargs['magic'], list):
            kwargs['magic'] = json.dumps(kwargs['magic'])
        
        if 'total_stats' not in kwargs:
            kwargs['total_stats'] = sum(current_stats.values())
            
        set_clause = ', '.join([f"{k} = ?" for k in kwargs.keys()])
        values = list(kwargs.values()) + [user_id]
        
        await db.execute(f"UPDATE users SET {set_clause} WHERE user_id = ?", values)
        await db.commit()

# --- ФУНКЦИИ ФОРМАТИРОВАНИЯ И КЛАВИАТУР ---

def format_cooldown(seconds_left: int) -> str:
    """Форматирует оставшееся время в ЧАСЫ, МИНУТЫ, СЕКУНДЫ."""
    if seconds_left <= 0:
        return "сейчас"
    td = timedelta(seconds=seconds_left)
    hours, remainder = divmod(td.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours} часов {minutes} минут {seconds} секунд"

def generate_profile_text(user: dict, last_action_message: str = "") -> str:
    """Генерирует текст профиля по заданному формату."""
    stats_text = ""
    for k in DEFAULT_STATS.keys():
        stats_text += f"{k}: {user[k]}/{MAX_STAT}\n"
    
    magic_list = user['magic'] if user['magic'] and user['magic'] != ['Антимагия'] else ["Не выбрана"]
    
    if user['magic'] == ['Антимагия']:
        magic_display = "Антимагия (Магия недоступна)"
    elif magic_list == ["Не выбрана"] and user['magic'] == []:
        magic_display = "Не выбрана"
    else:
        magic_display = ', '.join(magic_list)
    
    now = int(time.time())
    cooldown_left = COOLDOWN_SECONDS - (now - user['last_meditation'])
    cooldown_display = format_cooldown(cooldown_left)
    
    text = f"""
Раса: {user.get('race', 'Не выбрана')}
Магия: {magic_display}
Миры: Теранис (Земля) (Основной Мир)

Текущие характеристики:
{stats_text.strip()}

Следующая медитация через {cooldown_display}
    """.strip()
    
    if last_action_message:
        text = last_action_message + "\n\n" + text
        
    return text

def generate_initial_choice_keyboard() -> InlineKeyboardMarkup:
    """Генерирует кнопки для первого выбора Расы/Магии в /start."""
    keyboard = [
        [InlineKeyboardButton(text="Выбрать Расу", callback_data="open_race_select")],
        [InlineKeyboardButton(text="Выбрать Магию", callback_data="open_magic_select")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def generate_selection_keyboard(choices: dict, current_selections: Optional[List[str]] = None, is_race_menu: bool = False) -> InlineKeyboardMarkup:
    """Генерирует клавиатуру для выбора Расы или Магии."""
    keyboard = []
    
    if is_race_menu:
        # Меню Расы
        for i, (race, subraces) in enumerate(choices.items()):
            text = f"({i+1}) {race}"
            if subraces:
                text += f" (+{len(subraces)} суб-рас)"
            keyboard.append([InlineKeyboardButton(text=text, callback_data=f"select_race_{race}")])
    else:
        # Меню Магии
        for category, items in choices.items():
            keyboard.append([InlineKeyboardButton(text=f"----- {category} -----", callback_data="ignore")])
            
            for item in items:
                is_selected = item in (current_selections or [])
                text = ""
                callback = f"select_magic_{item}"

                # Все магии теперь доступны
                if item == "Антимагия":
                    text = f"❌ Антимагия (Сброс всех)"
                else:
                    text = f"✅ {item}" if is_selected else f"➕ {item}"
                    
                keyboard.append([InlineKeyboardButton(text=text, callback_data=callback)])
    
    keyboard.append([InlineKeyboardButton(text="Назад к Профилю", callback_data="back_to_profile")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


# ================== ХЕНДЛЕРЫ ==================

@dp.message(Command("start", "profile"))
async def start_and_profile(message: Message):
    user = await get_user(message.from_user.id)
    
    is_new_player = (user['race'] == 'Не выбрана' and not user['magic'])
    
    if is_new_player:
        # Приветствие для новых игроков
        welcome_text = (
            "Добро пожаловать в мир Archmage! Ты — новорожденный маг в великой вселенной.\n\n"
            "Чтобы начать свое путешествие, тебе необходимо выбрать свой путь:\n"
            "1. Раса (один выбор)\n"
            f"2. Магия (до {MAX_MAGIC_SLOTS} видов)\n\n"
            "Выбери свой начальный путь, нажав на кнопки ниже:"
        )
        await message.answer(welcome_text, reply_markup=generate_initial_choice_keyboard())
    else:
        # Обычный профиль для существующих игроков
        await message.answer(generate_profile_text(user))


@dp.message(F.text.lower().in_(["медитация", "медитировать", "медитирую"]))
async def meditate_text_handler(message: Message):
    """Обрабатывает медитацию по текстовому ключу."""
    user_id = message.from_user.id
    user = await get_user(user_id)
    now = int(time.time())
    
    seconds_left = COOLDOWN_SECONDS - (now - user["last_meditation"])

    if seconds_left > 0:
        cooldown_display = format_cooldown(seconds_left)
        await message.answer(f"Ты еще не восстановился. Следующая медитация через {cooldown_display}.")
        return

    # Успешная медитация
    new_perc = min(user["Восприятие"] + 2, MAX_STAT)
    new_en = min(user["Энергия"] + 2, MAX_STAT)

    await update_user(user_id, Восприятие=new_perc, Энергия=new_en, last_meditation=now)

    meditation_msg = "Вы погрузились в глубокую медитацию…"
    stats_update_msg = "+2 к Энергии\n+2 к Восприятию"
    
    user = await get_user(user_id)
    profile_text = generate_profile_text(user)
    
    final_message = f"{meditation_msg}\n\n{stats_update_msg}\n\n{profile_text}"
    
    await message.answer(final_message)


# --- ХЕНДЛЕРЫ КЛАВИАТУРЫ (CALLBACKS) ---

@dp.callback_query(F.data == "back_to_profile")
async def back_to_profile(callback: CallbackQuery):
    await callback.answer()
    user = await get_user(callback.from_user.id)
    text = generate_profile_text(user)
    # Используем edit_text, чтобы обновить сообщение
    await callback.message.edit_text(text, reply_markup=generate_initial_choice_keyboard())

# --- Открытие меню выбора Расы/Магии ---

@dp.callback_query(F.data == "open_race_select")
async def open_race_select_menu(callback: CallbackQuery):
    await callback.answer()
    race_keyboard = generate_selection_keyboard(RACES, is_race_menu=True)
    await callback.message.edit_text("Выберите свою Расу (можно выбрать только 1):", reply_markup=race_keyboard)


@dp.callback_query(F.data == "open_magic_select")
async def open_magic_select_menu(callback: CallbackQuery):
    await callback.answer()
    user = await get_user(callback.from_user.id)
    magic_keyboard = generate_selection_keyboard(MAGIC_SCHOOLS, user['magic'])
    
    text = f"Ваша Раса: {user['race']}.\n\n"
    text += f"Выберите до {MAX_MAGIC_SLOTS} видов Магии (выбрано: {len(user['magic'])}/{MAX_MAGIC_SLOTS}):"
    
    await callback.message.edit_text(text, reply_markup=magic_keyboard)

# --- Логика выбора Расы ---

@dp.callback_query(F.data.startswith("select_race_"))
async def process_race_selection(callback: CallbackQuery):
    race = callback.data.replace("select_race_", "")
    user_id = callback.from_user.id
    
    await update_user(user_id, race=race)
    
    await callback.answer(f"Раса: {race} выбрана.", show_alert=True)
    
    user = await get_user(user_id)
    await callback.message.edit_text(
        f"Ваша Раса установлена: {race}.\n\nПерейдите к выбору Магии.", 
        reply_markup=generate_initial_choice_keyboard()
    )

# --- Логика выбора Магии ---

@dp.callback_query(F.data.startswith("select_magic_"))
async def process_magic_selection(callback: CallbackQuery):
    magic = callback.data.replace("select_magic_", "")
    user_id = callback.from_user.id
    user = await get_user(user_id)
    current_magic = user['magic']

    # Логика Антимагии (сброс и установка)
    if magic == "Антимагия":
        await update_user(user_id, magic=["Антимагия"])
        await callback.answer("Вы выбрали Антимагию. Все другие Магии сброшены.", show_alert=True)
        current_magic = ["Антимагия"]
    
    elif magic in current_magic:
        # Удаление
        current_magic.remove(magic)
        await update_user(user_id, magic=current_magic)
        await callback.answer(f"Магия '{magic}' удалена.", show_alert=True)
    
    elif len(current_magic) < MAX_MAGIC_SLOTS and "Антимагия" not in current_magic:
        # Добавление
        current_magic.append(magic)
        await update_user(user_id, magic=current_magic)
        await callback.answer(f"Магия '{magic}' добавлена ({len(current_magic)}/{MAX_MAGIC_SLOTS}).", show_alert=True)
    else:
        # Ограничение
        await callback.answer(f"Вы можете выбрать только {MAX_MAGIC_SLOTS} вида Магии (или уже выбрали Антимагию).", show_alert=True)
        return
    
    # Обновление клавиатуры
    magic_keyboard = generate_selection_keyboard(MAGIC_SCHOOLS, current_magic)
    text = f"Ваша Раса: {user['race']}.\n\n"
    text += f"Выберите до {MAX_MAGIC_SLOTS} видов Магии (выбрано: {len(current_magic)}/{MAX_MAGIC_SLOTS}):"
    
    await callback.message.edit_text(text, reply_markup=magic_keyboard)
    
# --- РЕЙТИНГ ---

@dp.message(Command("rating"))
async def show_rating(message: Message):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT user_id, race, total_stats FROM users ORDER BY total_stats DESC LIMIT 10") as cursor:
            top_users = await cursor.fetchall()
    
    if not top_users:
        await message.answer("В рейтинге пока нет игроков.")
        return
        
    rating_text = "🏆 **ТОП 10 ИГРОКОВ (По общему числу характеристик)**\n\n"
    for i, (user_id, race, stats) in enumerate(top_users):
        name = f"ID: {user_id}"
        try:
            member = await bot.get_chat_member(message.chat.id, user_id)
            name = member.user.full_name
        except Exception:
            pass

        rating_text += f"**{i+1}.** {name} (Раса: {race}) - **{stats}** очков\n"

    await message.answer(rating_text, parse_mode="Markdown")

# ================== ЗАПУСК WEBHOOKS ==================

async def webhook_handler(request):
    """Обработчик входящих Webhooks-запросов (не менять)."""
    if request.match_info.get('path') != WEBHOOK_PATH.lstrip('/'):
        return web.Response(status=404)
    
    update = types.Update.model_validate(await request.json(), context={"bot": bot})
    await dp.feed_update(bot, update)
    return web.Response()

async def start_web_server():
    """Настройка и запуск Webhook-сервера."""
    await init_db()
    
    try:
        EXTERNAL_HOSTNAME = os.environ.get('VERCEL_URL') or os.environ['EXTERNAL_HOSTNAME'] 
    except KeyError:
        print("Ошибка: Переменная EXTERNAL_HOSTNAME/VERCEL_URL не найдена. Webhook не будет установлен.")
        return 

    WEBHOOK_URL = f"https://{EXTERNAL_HOSTNAME}{WEBHOOK_PATH}"
    
    await bot.set_webhook(WEBHOOK_URL)
    print(f"Webhook установлен на: {WEBHOOK_URL}")

    app = web.Application()
    app.router.add_post(f"/{WEBHOOK_PATH.lstrip('/')}", webhook_handler)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, WEB_SERVER_HOST, WEB_SERVER_PORT)
    await site.start()
    
    print(f"Web-сервер запущен на {WEB_SERVER_HOST}:{WEB_SERVER_PORT}")
    
if __name__ == "__main__":
    try:
        asyncio.run(start_web_server())
    except Exception as e:
        print(f"Ошибка при запуске Webhook-сервера: {e}")
