import os
import aiosqlite
import asyncio
import time
import json
from datetime import timedelta
from typing import List, Optional

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, StateFilter
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from aiohttp import web

# --- КОНСТАНТЫ ДЛЯ WEBHOOKS (НЕ МЕНЯТЬ) ---
WEB_SERVER_HOST = "0.0.0.0"
WEB_SERVER_PORT = os.getenv("PORT", 8080)
WEBHOOK_PATH = "/webhook"
TOKEN = os.getenv("BOT_TOKEN")

# --- НАСТРОЙКИ АДМИНИСТРАТОРА ---
# !!! ВАЖНО: ЗАМЕНИТЕ НА СВОЙ TELEGRAM ID ДЛЯ ДОСТУПА К АДМИН-КОМАНДАМ !!!
ADMIN_ID = 123456789 

bot = Bot(token=TOKEN, parse_mode="HTML")
dp = Dispatcher()
DB_NAME = "rpg_players.db"
COOLDOWN_SECONDS = 3 * 60 * 60 # 3 часа

# --- КОНСТАНТЫ И СПИСКИ ИГРЫ ---

RACES = {
    "Люди": [], 
    "Эльфы": ["Темные Эльфы"], 
    "Дварфы": [], 
    "Орки": [], 
    "Дракониды": [], 
    "Зверолюди": [], 
    "Инсектоиды": [], 
    "Гиганты": ["Титаны"], 
    "Вампиры": [], 
    "Оборотни": [], 
    "Нежить": [], 
    "Демоны": ["Багровые", "Суккубы"], 
    "Ангелы": ["Архангелы", "Падшие"], 
    "Монстры": [], 
    "Энты": [], 
    "Феи": [], 
    "Холодоки": [], 
    "Русалки": [], 
    "Големы": [], 
    "Химеры": [], 
    "Астрали": [], 
    "Наги": [],
}
RACE_CHOICES = list(RACES.keys())

MAGIC_SCHOOLS = {
    "Стихийная": [
        "Магия огня", "Магия воды", "Магия земли", "Магия воздуха", 
        "Магия молнии", "Магия льда", "Магия природы"
    ],
    "Специальная": [
        "Магия крови", "Магия металла", "Магия звука", "Магия гравитации"
    ],
    "Высшая (Адм)": [
        "Магия времени", "Магия пространства", "Магия разрушения", 
        "Магия созидания", "Магия света", "Магия тьмы"
    ],
    "Ментальная": [
        "Магия ментальная", "Магия духовная", "Магия иллюзорная", 
        "Магия усиления", "Магия энергии", "Магия сновидений", 
        "Магия вирусов", "Магия эмоций", "Магия призыва", 
        "Магия некромантия", "Магия превращения", "Магия теней", 
        "Магия печатей"
    ],
    "Особая": ["Антимагия"],
}
ALL_MAGICS = [item for sublist in MAGIC_SCHOOLS.values() for item in sublist]


DEFAULT_STATS = {
    "Сила": 10, "Живучесть": 10, "Защита": 10, "Ловкость": 10, 
    "Интеллект": 10, "Мудрость": 10, "Харизма": 10, "Восприятие": 10, 
    "Выносливость": 10, "Энергия": 10, "Удача": 10
}
MAX_STAT = 250

# --- СОСТОЯНИЯ (FSM) ---
class AdminStates(StatesGroup):
    """Состояния для админ-команды."""
    waiting_for_user_id = State()
    waiting_for_new_magic = State()
    
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
                magic TEXT DEFAULT '[]', -- Теперь хранит JSON-строку со списком
                total_stats INTEGER DEFAULT 110 -- Для рейтинга
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
                # Преобразование строки магии в список
                user_data['magic'] = json.loads(user_data['magic'])
                return user_data
            else:
                await db.execute("INSERT INTO users (user_id) VALUES (?)", (user_id,))
                await db.commit()
                return await get_user(user_id)

async def update_user(user_id: int, **kwargs):
    async with aiosqlite.connect(DB_NAME) as db:
        # Автоматическое обновление total_stats
        user = await get_user(user_id)
        current_stats = {k: user[k] for k in DEFAULT_STATS.keys()}
        current_stats.update(kwargs) # Обновляем переданные характеристики
        
        if 'magic' in kwargs and isinstance(kwargs['magic'], list):
            kwargs['magic'] = json.dumps(kwargs['magic'])
        
        if 'total_stats' not in kwargs:
            kwargs['total_stats'] = sum(current_stats.values())
            
        set_clause = ', '.join([f"{k} = ?" for k in kwargs.keys()])
        values = list(kwargs.values()) + [user_id]
        
        await db.execute(f"UPDATE users SET {set_clause} WHERE user_id = ?", values)
        await db.commit()

# --- ГЕНЕРАЦИЯ ТЕКСТА И КЛАВИАТУР ---

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
    
    magic_list = user['magic'] if user['magic'] else ["Не выбрана"]
    
    now = int(time.time())
    cooldown_left = COOLDOWN_SECONDS - (now - user['last_meditation'])
    cooldown_display = format_cooldown(cooldown_left)
    
    text = f"""
Раса: {user.get('race', 'Не выбрана')}
Магия: {', '.join(magic_list)}
Миры: Теранис (Земля) (Основной Мир)

Текущие характеристики:
{stats_text.strip()}

Следующая медитация через {cooldown_display}
    """.strip()
    
    if last_action_message:
        text = last_action_message + "\n\n" + text
        
    return text

def generate_selection_keyboard(choices: dict, current_selections: Optional[List[str]] = None) -> InlineKeyboardMarkup:
    """Генерирует клавиатуру для выбора Расы или Магии."""
    keyboard = []
    
    for category, items in choices.items():
        if isinstance(items, list): # Это магии
            keyboard.append([InlineKeyboardButton(text=f"----- {category} -----", callback_data="ignore")])
            current_count = len(current_selections) if current_selections else 0
            
            for item in items:
                is_selected = item in (current_selections or [])
                
                # Админ-магии могут быть выбраны только Админом
                if category == "Высшая (Адм)" and item not in (current_selections or []):
                    text = f"{item} (Адм)"
                    callback = "ignore"
                # Антимагия заменяет все магии
                elif item == "Антимагия":
                    text = f"Антимагия (Сброс Магии)"
                    callback = f"select_magic_{item}"
                # Остальные магии
                else:
                    text = f"✅ {item}" if is_selected else f"➕ {item}"
                    callback = f"select_magic_{item}"
                    
                keyboard.append([InlineKeyboardButton(text=text, callback_data=callback)])
        
        else: # Это расы
            for i, (race, subraces) in enumerate(choices.items()):
                text = f"({i+1}) {race}"
                if subraces:
                    text += f" (+{len(subraces)})"
                keyboard.append([InlineKeyboardButton(text=text, callback_data=f"select_race_{race}")])

    keyboard.append([InlineKeyboardButton(text="Назад к Профилю", callback_data="back_to_profile")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

# --- ХЕНДЛЕРЫ ---

@dp.message(Command("start", "profile"))
async def start_and_profile(message: Message):
    user = await get_user(message.from_user.id)
    
    # Проверка, нужно ли предложить выбор
    if user['race'] == 'Не выбрана' or not user['magic']:
        text = "Добро пожаловать в мир Archmage! Сначала выберите свою Расу и Магию."
        await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Выбрать Расу/Магию", callback_data="open_select_menu")]
        ]))
    else:
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

    # Обновляем базу
    await update_user(
        user_id, 
        Восприятие=new_perc, 
        Энергия=new_en, 
        last_meditation=now
    )

    meditation_msg = "Вы погрузились в глубокую медитацию…"
    stats_update_msg = "+2 к Энергии\n+2 к Восприятию"
    
    user = await get_user(user_id) # Обновляем данные для вывода
    
    # Форматирование профиля после медитации
    profile_text = generate_profile_text(user)
    
    final_message = f"{meditation_msg}\n\n{stats_update_msg}\n\n{profile_text}"
    
    await message.answer(final_message)


# --- ХЕНДЛЕРЫ ВЫБОРА (CALLBACKS) ---

@dp.callback_query(F.data == "open_select_menu")
@dp.callback_query(F.data == "back_to_profile")
async def open_or_back(callback: CallbackQuery):
    await callback.answer()
    if callback.data == "back_to_profile":
        user = await get_user(callback.from_user.id)
        text = generate_profile_text(user)
        # Отправляем новое сообщение, чтобы избежать ошибок редактирования, если это callback из другого меню
        await callback.message.answer(text)
        await callback.message.delete()
        return

    # Открытие меню выбора Расы
    race_keyboard = generate_selection_keyboard(RACES)
    await callback.message.edit_text("Выберите свою Расу (можно выбрать только 1):", reply_markup=race_keyboard)

@dp.callback_query(F.data.startswith("select_race_"))
async def process_race_selection(callback: CallbackQuery):
    race = callback.data.replace("select_race_", "")
    user_id = callback.from_user.id
    
    # Сохраняем выбор в базу
    await update_user(user_id, race=race)
    
    # Открываем меню выбора Магии
    user = await get_user(user_id)
    magic_keyboard = generate_selection_keyboard(MAGIC_SCHOOLS, user['magic'])
    
    text = f"Ваша Раса установлена: {race}.\n\n"
    text += f"Выберите до 4-х видов Магии (выбрано: {len(user['magic'])}/4):"
    
    await callback.answer(f"Раса: {race} выбрана.", show_alert=True)
    await callback.message.edit_text(text, reply_markup=magic_keyboard)

@dp.callback_query(F.data.startswith("select_magic_"))
async def process_magic_selection(callback: CallbackQuery):
    magic = callback.data.replace("select_magic_", "")
    user_id = callback.from_user.id
    user = await get_user(user_id)
    current_magic = user['magic']

    # Логика Антимагии (сброс)
    if magic == "Антимагия":
        await update_user(user_id, magic=["Антимагия"])
        await callback.answer("Вы выбрали Антимагию. Все другие Магии сброшены.", show_alert=True)
        current_magic = ["Антимагия"]
    
    # Логика выбора
    elif magic in current_magic:
        # Удаление
        current_magic.remove(magic)
        await update_user(user_id, magic=current_magic)
        await callback.answer(f"Магия '{magic}' удалена.", show_alert=True)
    elif len(current_magic) < 4 and "Антимагия" not in current_magic:
        # Добавление
        current_magic.append(magic)
        await update_user(user_id, magic=current_magic)
        await callback.answer(f"Магия '{magic}' добавлена ({len(current_magic)}/4).", show_alert=True)
    else:
        # Ограничение
        await callback.answer("Вы можете выбрать только 4 вида Магии (или уже выбрали Антимагию).", show_alert=True)
        return
    
    # Обновление клавиатуры
    magic_keyboard = generate_selection_keyboard(MAGIC_SCHOOLS, current_magic)
    text = f"Ваша Раса: {user['race']}.\n\n"
    text += f"Выберите до 4-х видов Магии (выбрано: {len(current_magic)}/4):"
    
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
        # Используем имя/никнейм (если доступно), иначе ID
        try:
            member = await bot.get_chat_member(message.chat.id, user_id)
            name = member.user.full_name
        except Exception:
            name = f"ID: {user_id}"

        rating_text += f"**{i+1}.** {name} (Раса: {race}) - **{stats}** очков\n"

    await message.answer(rating_text, parse_mode="Markdown")

# --- АДМИН-КОМАНДЫ ---

@dp.message(Command("admin_set_magic"))
async def admin_set_magic_start(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        await message.answer("У вас нет прав администратора.")
        return

    await message.answer("Введите ID пользователя, которому вы хотите изменить Магию:")
    await state.set_state(AdminStates.waiting_for_user_id)

@dp.message(AdminStates.waiting_for_user_id)
async def admin_set_magic_get_id(message: Message, state: FSMContext):
    try:
        target_id = int(message.text.strip())
        await state.update_data(target_id=target_id)
        
        # Проверяем, существует ли пользователь
        target_user = await get_user(target_id)
        
        await message.answer(
            f"ID пользователя {target_id} найден (Раса: {target_user['race']}).\n"
            "Введите НОВЫЙ список Магий через запятую (максимум 4)."
            "\nПример: Магия огня, Магия льда, Магия времени"
        )
        await state.set_state(AdminStates.waiting_for_new_magic)
    except ValueError:
        await message.answer("Неверный формат ID. Введите только число.")
    except Exception:
        await message.answer("Пользователь с таким ID не найден в базе данных.")

@dp.message(AdminStates.waiting_for_new_magic)
async def admin_set_magic_set_magic(message: Message, state: FSMContext):
    data = await state.get_data()
    target_id = data['target_id']
    
    # Обработка нового списка магий
    new_magic_raw = message.text.split(',')
    new_magic_list = [m.strip() for m in new_magic_raw]
    
    # Валидация
    valid_magic = [m for m in new_magic_list if m in ALL_MAGICS or m == "Антимагия"]
    
    if not valid_magic:
        await message.answer("Не найдено ни одной существующей Магии. Попробуйте снова.")
        return
        
    if len(valid_magic) > 4 and "Антимагия" not in valid_magic:
        await message.answer(f"Вы ввели {len(valid_magic)} Магий. Максимум 4. Попробуйте снова.")
        return

    # Сохранение
    await update_user(target_id, magic=valid_magic)
    
    await message.answer(
        f"Успех! Магия для пользователя ID {target_id} обновлена на: {', '.join(valid_magic)}"
    )
    await state.clear()

# ================== ФУНКЦИИ ЗАПУСКА WEBHOOKS ==================

# Хендлер для входящих Webhooks-запросов (не меняем)
async def webhook_handler(request):
    if request.match_info.get('path') != WEBHOOK_PATH.lstrip('/'):
        return web.Response(status=404)
    
    update = types.Update.model_validate(await request.json(), context={"bot": bot})
    await dp.feed_update(bot, update)
    return web.Response()

# Функция запуска Web-сервера (не меняем, но важна для Vercel)
async def start_web_server():
    await init_db()
    
    try:
        # Vercel использует VERCEL_URL или EXTERNAL_HOSTNAME
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
    
# Главная точка запуска
if __name__ == "__main__":
    try:
        asyncio.run(start_web_server())
    except Exception as e:
        print(f"Ошибка при запуске Webhook-сервера: {e}")

