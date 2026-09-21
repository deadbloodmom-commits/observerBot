import asyncio
import html
import logging
import os
import re  # <--- Для работы регулярных выражений[cite: 3]
from datetime import datetime, timedelta
from dotenv import load_dotenv

import asyncpg
import psycopg2  # <--- Верните этот импорт для работы init_db()
import asyncpg
from aiohttp import web
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    BotCommand,
    BotCommandScopeChat,
    BotCommandScopeDefault,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    MessageReactionUpdated,
)

# Загружает переменные из локального файла .env (если он есть)
load_dotenv()

# Получаем токен из системных переменных хостинга или .env
TOKEN = os.getenv("ACCESS_TOKEN")

if not TOKEN:
    raise ValueError(f"Токен не найден! Доступные ключи: {list(os.environ.keys())}")

# Создаем бота и диспетчер ОДИН раз
bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())

DATABASE_URL = os.getenv("DATABASE_URL")
GROUP_CHAT_ID = -1003910683430
ADMIN_CHAT_ID = -1003910683430
APPLICATIONS_TOPIC_ID = 4440
OWNER_ID = 8522250722

REVIEWS_CHAT_ID = -1004495861076
REVIEWS_URL = "https://t.me/Observer_black_sector_reviews"

# Кэш сообщений для синхронизации ответов (reply) и реакций
msg_map = {}
# --- FSM СОСТОЯНИЯ ---
class AdminStates(StatesGroup):
    broadcast_msg = State()
    confirm_broadcast = State()
    edit_welcome = State()
    edit_rules = State()
    write_review = State()
    waiting_category_text = State()
    waiting_change_category_text = State()


# --- РАБОТА С БД POSTGRESQL ---

def get_db_connection():
    return psycopg2.connect(DATABASE_URL)

def get_setting(key: str, default: str = "") -> str:
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT value FROM settings WHERE key = %s", (key,))
            row = cursor.fetchone()
    return row[0] if row else default


def set_setting(key: str, value: str):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO settings (key, value) VALUES (%s, %s) 
                ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
                """,
                (key, value),
            )
            conn.commit()


def init_db():
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    username TEXT,
                    full_name TEXT,
                    admin_tag TEXT,
                    topic_id INTEGER,
                    state TEXT,
                    blocked INTEGER DEFAULT 0,
                    banned_by_admin INTEGER DEFAULT 0,
                    streak_count INTEGER DEFAULT 1,
                    last_active_date TEXT,
                    streak_lost_days INTEGER DEFAULT 0,
                    assigned_admin_id BIGINT,
                    last_category TEXT,
                    last_admin_tag TEXT,
                    discussion_topic_id INTEGER
                )
            """)

            cursor.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS topic_id INTEGER;")
            cursor.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS assigned_admin_id BIGINT;")
            cursor.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_category TEXT;")
            cursor.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_admin_tag TEXT;")
            cursor.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS discussion_topic_id INTEGER;")

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS admins (
                    user_id BIGINT PRIMARY KEY,
                    admin_tag TEXT
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS bot_admins (
                    user_id BIGINT PRIMARY KEY
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS stats (
                    id SERIAL PRIMARY KEY,
                    msg_type TEXT,
                    timestamp TEXT
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS user_activity (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT,
                    timestamp TEXT
                )
            """)

            default_welcome = (
                "╔═══ ᏎЁᏢᎻᏏᏓЙ ᏟᎬᏦᎢᏫᏢ ═══╗\n"
                "  ᎻᎪᏮᏗᎰᏫᎠᎪᎢᎬᏗᏏ\n"
                "╚══════════════════╝\n\n"
                "Ꭰᴏᴄᴛуᴨ ᴨᴏᴧучᴇн.\n\n"
                "Ꭼᴄᴧи ᴛы чиᴛᴀᴇɯь ϶ᴛᴏ —\n"
                "ᴄиᴄᴛᴇʍᴀ ужᴇ ɜᴀʍᴇᴛиᴧᴀ ᴛʙᴏё ᴨᴩиᴄуᴛᴄᴛʙиᴇ.\n\n"
                "Здᴇᴄь ʍᴏжнᴏ ᴦᴏʙᴏᴩиᴛь ᴏ ᴛᴏʍ,\n"
                "ᴏ чёʍ ᴏбычнᴏ ʍᴏᴧчᴀᴛ.\n"
                "Ꮇᴏжнᴏ ᴏᴄᴛᴀʙиᴛь иᴄᴛᴏᴩию,\n"
                "ʍыᴄᴧь иᴧи ᴨᴩᴏᴄᴛᴏ нᴇᴄᴋᴏᴧьᴋᴏ ᴄᴧᴏʙ.\n\n"
                "Ꮋᴀбᴧюдᴀᴛᴇᴧь нᴇ ᴨᴇᴩᴇбиʙᴀᴇᴛ.\n"
                "Ꮋᴀбᴧюдᴀᴛᴇᴧь нᴇ ᴏᴄуждᴀᴇᴛ.\n"
                "Ꮋᴀбᴧюдᴀᴛᴇᴧь ᴨᴩᴏᴄᴛᴏ ᴄᴧуɯᴀᴇᴛ.\n\n"
                "Ꮋᴏ ᴨᴏʍни:\n"
                "ʙ Ꮞёᴩнᴏʍ ᴄᴇᴋᴛᴏᴩᴇ ничᴇᴦᴏ нᴇ иᴄчᴇɜᴀᴇᴛ бᴇᴄᴄᴧᴇднᴏ.\n\n"
                "[ ЗᎪ ᎢᏫᏮᏫЙ ᎻᎪᏮᏗᎰᏫᎠᎪᎰᏫᎢ ]"
            )

            default_rules = (
                "Вот правила, которые нужно соблюдать в общении с администрацией:\n\n"
                "1. Не спамьте в бот, за ботом сидят живые люди, у которых так же есть дела, если вам долго не отвечают то повторите свое сообщение.\n\n"
                "2. Ставьте в начале/в конце сообщение тег своего админа, так им будет легче найти вас.\n\n"
                "3. Не скидывайте порнографию, кровь, порезы — это нарушение — бан.\n\n"
                "4. Не оскорбляйте администрацию — бан.\n\n"
                "5. Реклама тоже запрещена — бан.\n\n"
                "6. Выпрашивать у админов инфу о них или просить юзы — бан.\n\n"
                "7. Неуважение к администрации — бан.\n\n"
                "8. Незнание правил не освобождает вас от ответственности.\n\n"
                "Нарушение правил — бан навсегда.\n"
                "С вами был владелец, #сталкер ."
            )

            cursor.execute(
                "INSERT INTO settings (key, value) VALUES ('welcome', %s) ON CONFLICT (key) DO NOTHING",
                (default_welcome,),
            )
            cursor.execute(
                "INSERT INTO settings (key, value) VALUES ('rules', %s) ON CONFLICT (key) DO NOTHING",
                (default_rules,),
            )
            conn.commit()


def get_current_owner_id() -> int:
    val = get_setting("owner_id")
    if val and val.isdigit():
        return int(val)
    return OWNER_ID


def is_owner(user_id: int) -> bool:
    return user_id == get_current_owner_id()


def get_user(user_id: int):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM users WHERE user_id = %s", (user_id,))
            row = cursor.fetchone()
    return row


def register_user(user_id: int, username: str, full_name: str):
    today_str = datetime.now().strftime("%Y-%m-%d")
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO users (user_id, username, full_name, admin_tag, topic_id, state, blocked, banned_by_admin, streak_count, last_active_date, streak_lost_days) 
                VALUES (%s, %s, %s, NULL, NULL, NULL, 0, 0, 1, %s, 0)
                ON CONFLICT (user_id) DO NOTHING
                """,
                (user_id, username, full_name, today_str),
            )
            conn.commit()


def set_user_state(user_id: int, state: str):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE users SET state = %s WHERE user_id = %s", (state, user_id)
            )
            conn.commit()


def reset_user_admin(user_id: int):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT admin_tag, last_category FROM users WHERE user_id = %s", (user_id,))
            row = cursor.fetchone()
            old_tag = row[0] if row and row[0] else "Не было"
            old_cat = row[1] if row and row[1] else "Общение"

            cursor.execute(
                """UPDATE users SET 
                   last_admin_tag = %s, 
                   last_category = %s, 
                   admin_tag = NULL, 
                   assigned_admin_id = NULL 
                   WHERE user_id = %s""", 
                (old_tag, old_cat, user_id)
            )
            conn.commit()


def log_msg(msg_type: str, user_id: int = None):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "INSERT INTO stats (msg_type, timestamp) VALUES (%s, %s)",
                (msg_type, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
            )
            if user_id:
                cursor.execute(
                    "INSERT INTO user_activity (user_id, timestamp) VALUES (%s, %s)",
                    (user_id, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
                )
            conn.commit()


# --- ЛОГИКА СТРИКОВ ---

def update_user_streak(user_id: int) -> tuple:
    today_str = datetime.now().strftime("%Y-%m-%d")
    yesterday_str = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT streak_count, last_active_date, streak_lost_days FROM users WHERE user_id = %s",
                (user_id,),
            )
            row = cursor.fetchone()

            if not row:
                return 1, False

            streak = row[0] if row[0] is not None else 1
            last_date = row[1]

            if streak <= 0:
                return 0, False

            if last_date == today_str:
                return streak, False
            elif last_date == yesterday_str or last_date is None:
                new_streak = streak + 1 if last_date == yesterday_str else 1
                cursor.execute(
                    "UPDATE users SET streak_count = %s, last_active_date = %s, streak_lost_days = 0 WHERE user_id = %s",
                    (new_streak, today_str, user_id),
                )
                conn.commit()
                return new_streak, True
            else:
                try:
                    d1 = datetime.strptime(last_date, "%Y-%m-%d")
                    d2 = datetime.strptime(today_str, "%Y-%m-%d")
                    diff_days = (d2 - d1).days
                except Exception:
                    diff_days = 3

                new_streak = 1 if diff_days >= 3 else streak + 1

                cursor.execute(
                    "UPDATE users SET streak_count = %s, last_active_date = %s, streak_lost_days = 0 WHERE user_id = %s",
                    (new_streak, today_str, user_id),
                )
                conn.commit()
                return new_streak, True


async def check_streaks_daily_task():
    while True:
        now = datetime.now()
        target = now.replace(hour=22, minute=0, second=0, microsecond=0)
        if now >= target:
            target += timedelta(days=1)
        
        await asyncio.sleep((target - datetime.now()).total_seconds())

        today_str = datetime.now().strftime("%Y-%m-%d")
        yesterday_str = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT user_id, streak_count, last_active_date, streak_lost_days FROM users WHERE blocked = 0 AND banned_by_admin = 0 AND streak_count > 0"
                )
                users = cursor.fetchall()

        for u_id, streak, last_date, lost_days in users:
            if last_date != today_str and last_date != yesterday_str:
                new_lost_days = lost_days + 1
                if new_lost_days >= 3:
                    with get_db_connection() as conn:
                        with conn.cursor() as cursor:
                            cursor.execute(
                                "UPDATE users SET streak_count = 0, streak_lost_days = 0 WHERE user_id = %s",
                                (u_id,)
                            )
                            conn.commit()
                    try:
                        await bot.send_message(
                            chat_id=u_id,
                            text="📛 <b>Ваша серия общения сгорела</b>, так как вы не поддерживали её в течение трёх дней.\n\nЧтобы начать новую серию, напишите сообщение своему администратору через бот! 🥀",
                            parse_mode="HTML"
                        )
                    except Exception:
                        pass
                else:
                    with get_db_connection() as conn:
                        with conn.cursor() as cursor:
                            cursor.execute(
                                "UPDATE users SET streak_lost_days = %s WHERE user_id = %s",
                                (new_lost_days, u_id)
                            )
                            conn.commit()
                    try:
                        await bot.send_message(
                            chat_id=u_id,
                            text="📛 <b>Внимание! Вы не поддержали серию общения сегодня.</b>\nЕсли вы не напишете сообщение, серия сгорит через несколько дней!",
                            parse_mode="HTML"
                        )
                    except Exception:
                        pass


# --- КЛАВИАТУРЫ ---

def get_main_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🌑 Ссылки", callback_data="menu_links")],
            [InlineKeyboardButton(text="👀 Правила", callback_data="show_rules")],
            [InlineKeyboardButton(text="🖤 Поговорить", callback_data="menu_talk")],
        ]
    )


def get_categories_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🖤Общение", callback_data="cat_communication")],
            [InlineKeyboardButton(text="🌑 Поддержка", callback_data="cat_support")],
            [InlineKeyboardButton(text="🐾Общение и поддержка", callback_data="cat_both")],
            [InlineKeyboardButton(text="← назад", callback_data="user_back")],
        ]
    )


def get_change_categories_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🖤Общение", callback_data="changecat_communication")],
            [InlineKeyboardButton(text="🌑 Поддержка", callback_data="changecat_support")],
            [InlineKeyboardButton(text="🐾Общение и поддержка", callback_data="changecat_both")],
            [InlineKeyboardButton(text="← назад", callback_data="user_back")],
        ]
    )


def get_links_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🖤 Ссылка на ТГК", url="https://t.me/Observer_black_sector_chanal")],
            [InlineKeyboardButton(text="🖤 Ссылка на отзывы", callback_data="menu_reviews_section")],
            [InlineKeyboardButton(text="🖤 Ссылка на анкетницу", url="https://t.me/Observer_black_sector_anketbot")],
            [InlineKeyboardButton(text="← назад", callback_data="user_back")],
        ]
    )


def get_back_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="← назад", callback_data="user_back")]]
    )


def get_tag_management_kb():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✏️ Сменить тег", callback_data="change_tag_prompt")],
            [InlineKeyboardButton(text="❌ Удалить тег", callback_data="delete_tag_confirm")],
        ]
    )


def get_admin_panel_kb():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📢 Рассылка", callback_data="adm_broadcast"),
                InlineKeyboardButton(text="📊 Статистика", callback_data="adm_stats"),
            ],
            [
                InlineKeyboardButton(text="🚫 Чёрный список", callback_data="adm_ban_list"),
                InlineKeyboardButton(text="🏆 Топ активных", callback_data="adm_top"),
            ],
            [
                InlineKeyboardButton(text="✏️ Тексты", callback_data="adm_texts"),
                InlineKeyboardButton(text="🏷️ Админы с тегами", callback_data="adm_tag_admins"),
            ],
        ]
    )


async def set_bot_commands(bot_instance: Bot):
    default_commands = [
        BotCommand(command="start", description="Запустить бота"),
        BotCommand(command="links", description="Полезные ссылки"),
        BotCommand(command="reviews", description="Раздел отзывов"),
        BotCommand(command="communication", description="Начать общение с админами"),
        BotCommand(command="streak", description="Посмотреть свой стрик общения 🔥"),
    ]
    await bot_instance.set_my_commands(default_commands, scope=BotCommandScopeDefault())

    admin_group_commands = [
        BotCommand(command="settag", description="Установить свой тег (#Тег)"),
        BotCommand(command="mytag", description="Узнать свой тег"),
        BotCommand(command="alltags", description="Список всех тегов админов"),
        BotCommand(command="admins", description="Созвать всех администраторов"),
    ]
    await bot_instance.set_my_commands(admin_group_commands, scope=BotCommandScopeChat(chat_id=ADMIN_CHAT_ID))


@dp.callback_query.outer_middleware()
async def register_user_on_callback(handler, event: types.CallbackQuery, data):
    if event.from_user:
        user_id = event.from_user.id
        register_user(user_id, event.from_user.username, event.from_user.full_name)
        
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT 1 FROM admins WHERE user_id = %s", (user_id,))
                is_admin = cursor.fetchone() is not None

        if not is_owner(user_id) and not is_admin:
            user = get_user(user_id)
            if user and user[6] == 1:
                await event.answer("Вы заблокированы в этом боте!", show_alert=True)
                return
    return await handler(event, data)


# --- ОСНОВНЫЕ КОМАНДЫ ПОЛЬЗОВАТЕЛЯ И АДМИНА ---

@dp.message(Command("admin"), F.chat.type == "private")
async def cmd_admin_panel(message: types.Message, state: FSMContext):
    await state.clear()
    
    if not is_owner(message.from_user.id):
        return
        
    await message.answer("🖤 <b>Панель администратора:</b>", reply_markup=get_admin_panel_kb(), parse_mode="HTML")


@dp.message(Command("start"), F.chat.type == "private")
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    register_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    await message.answer(get_setting("welcome"), reply_markup=get_main_keyboard(), parse_mode="HTML")


@dp.message(Command("links"), F.chat.type == "private")
async def cmd_links_text(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Выбери нужный раздел из списка ниже: 🔎", reply_markup=get_links_keyboard(), parse_mode="HTML")


@dp.message(Command("reviews"), F.chat.type == "private")
async def cmd_reviews_text(message: types.Message, state: FSMContext):
    await state.clear()
    kb = [
        [InlineKeyboardButton(text="🔎 Посмотреть отзывы", url=REVIEWS_URL)],
        [InlineKeyboardButton(text="✍️ Написать отзыв", callback_data="start_write_review")],
        [InlineKeyboardButton(text="←️ Назад", callback_data="user_back")],
    ]
    await message.answer("💬 <b>Раздел отзывов</b>\nЗдесь ты можешь посмотреть отзывы других или оставить свой!", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")


@dp.message(Command("streak"), F.chat.type == "private")
async def cmd_my_streak(message: types.Message, state: FSMContext):
    await state.clear()
    user = get_user(message.from_user.id)
    streak = user[8] if user and len(user) > 8 and user[8] is not None else 0
    if streak <= 0:
        await message.answer("📛 <b>У вас сейчас нет активной серии общения.</b> Напишите администраторам через меню «Поговорить». 🥀", parse_mode="HTML")
    else:
        await message.answer(f"🔥 <b>Ваша серия общения (стрик):</b> {streak} дн. подряд! 👀", parse_mode="HTML")


@dp.message(Command("communication"), F.chat.type == "private")
async def cmd_communication_text(message: types.Message, state: FSMContext):
    await state.clear()
    user = get_user(message.from_user.id)
    admin_tag = user[3] if user else None

    if admin_tag:
        kb = [[InlineKeyboardButton(text="🔄 Сменить администратора", callback_data="change_admin")], [InlineKeyboardButton(text="⬅️ Назад", callback_data="user_back")]]
        await message.answer(f"Твоим администратором на данный момент является <b>{html.escape(str(admin_tag))}</b> 🥀", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")
    else:
        await message.answer("👀 Выберите категорию для общения:", reply_markup=get_categories_keyboard(), parse_mode="HTML")


@dp.message(Command("alltags"))
async def cmd_alltags(message: types.Message, state: FSMContext):
    await state.clear()
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT admins.admin_tag, users.username, users.full_name FROM admins LEFT JOIN users ON admins.user_id = users.user_id")
                rows = cursor.fetchall()
        if not rows:
            await message.answer("👀 Список тегов пуст.")
            return
        text = "👀 <b>Список тегов администраторов:</b>\n\n"
        for tag, uname, fname in rows:
            text += f"• {html.escape(str(tag))} — {html.escape(str(fname or 'Админ'))}\n"
        await message.answer(text, parse_mode="HTML")
    except Exception:
        await message.answer("⚠️ Произошла ошибка при получении списка тегов.")


@dp.callback_query(F.data == "user_back")
async def user_back(call: types.CallbackQuery, state: FSMContext):
    await state.clear()
    set_user_state(call.from_user.id, None)
    await call.message.edit_text(get_setting("welcome"), reply_markup=get_main_keyboard(), parse_mode="HTML")


@dp.callback_query(F.data == "menu_links")
async def process_links(call: types.CallbackQuery):
    await call.message.edit_text("Выбери нужный раздел из списка ниже: 📱", reply_markup=get_links_keyboard(), parse_mode="HTML")


@dp.callback_query(F.data == "show_rules")
async def show_rules(call: types.CallbackQuery):
    await call.message.edit_text(get_setting("rules"), reply_markup=get_back_keyboard(), parse_mode="HTML")


@dp.callback_query(F.data == "menu_talk")
async def process_talk(call: types.CallbackQuery, state: FSMContext):
    user = get_user(call.from_user.id)
    admin_tag = user[3] if user else None
    if admin_tag:
        kb = [[InlineKeyboardButton(text="🔄 Сменить администратора", callback_data="change_admin")], [InlineKeyboardButton(text="⬅️ Назад", callback_data="user_back")]]
        await call.message.edit_text(f"Твоим администратором на данный момент является <b>{html.escape(str(admin_tag))}</b> 🥀", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")
    else:
        await call.message.edit_text("👀 Выберите категорию для общения:", reply_markup=get_categories_keyboard(), parse_mode="HTML")


@dp.callback_query(F.data.in_({"cat_communication", "cat_support", "cat_both"}))
async def process_category(call: types.CallbackQuery, state: FSMContext):
    cat_names = {"cat_communication": "Общение", "cat_support": "Поддержка", "cat_both": "Общение и поддержка"}
    cat_title = cat_names[call.data]
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("UPDATE users SET last_category = %s WHERE user_id = %s", (cat_title, call.from_user.id))
            conn.commit()
    await state.update_data(chosen_category=cat_title)
    await state.set_state(AdminStates.waiting_category_text)
    await call.message.edit_text(f"📱 Напиши своё сообщение для категории <b>{cat_title}</b>:", reply_markup=get_back_keyboard(), parse_mode="HTML")


@dp.callback_query(F.data.in_({"changecat_communication", "changecat_support", "changecat_both"}))
async def process_change_category(call: types.CallbackQuery, state: FSMContext):
    cat_names = {"changecat_communication": "Общение", "changecat_support": "Поддержка", "changecat_both": "Общение и поддержка"}
    cat_title = cat_names[call.data]
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("UPDATE users SET last_category = %s WHERE user_id = %s", (cat_title, call.from_user.id))
            conn.commit()
    await state.update_data(chosen_category=cat_title)
    await state.set_state(AdminStates.waiting_change_category_text)
    await call.message.edit_text(f"📱 Напиши своё сообщение для смены администратора (категория: <b>{cat_title}</b>):", reply_markup=get_back_keyboard(), parse_mode="HTML")


@dp.callback_query(F.data == "menu_reviews_section")
async def process_reviews_section(call: types.CallbackQuery):
    kb = [
        [InlineKeyboardButton(text="🔎 Посмотреть отзывы", url=REVIEWS_URL)],
        [InlineKeyboardButton(text="✍️ Написать отзыв", callback_data="start_write_review")],
        [InlineKeyboardButton(text="←️ Назад", callback_data="menu_links")],
    ]
    await call.message.edit_text("💬 <b>Раздел отзывов</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")


@dp.callback_query(F.data == "start_write_review")
async def start_review(call: types.CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.write_review)
    await call.message.edit_text("📱 Напиши свой отзыв (в начале укажи тег администратора):", parse_mode="HTML", reply_markup=get_back_keyboard())


@dp.message(AdminStates.write_review)
async def process_user_review(message: types.Message, state: FSMContext):
    await state.clear()
    try:
        clean_text = html.escape(message.text or "")
        display_name = html.escape((message.from_user.first_name or "Пользователь"))
        await bot.send_message(chat_id=REVIEWS_CHAT_ID, text=f"💬 <b>Новый отзыв!</b>\nОт: {display_name}\n\n{clean_text}", parse_mode="HTML")
        await message.answer("🕶️Твой отзыв успешно отправлен! Спасибо 🖤", reply_markup=get_main_keyboard())
    except Exception as e:
        await message.answer(f"⚠️ Ошибка: {e}", reply_markup=get_main_keyboard())


# --- УПРАВЛЕНИЕ ТЕГОМ АДМИНА ---

@dp.message(Command("settag"))
async def cmd_set_tag(message: types.Message, state: FSMContext):
    await state.clear()
    args = message.text.split(maxsplit=1)
    if len(args) < 2 or not args[1].startswith("#"):
        await message.answer("⚠️ Использование: <code>/settag #Тег</code>", parse_mode="HTML")
        return
    tag = args[1]
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("INSERT INTO admins (user_id, admin_tag) VALUES (%s, %s) ON CONFLICT (user_id) DO UPDATE SET admin_tag = EXCLUDED.admin_tag", (message.from_user.id, tag))
            conn.commit()
    await message.answer(f"🖤 Тег сохранён: <b>{html.escape(tag)}</b>", reply_markup=get_tag_management_kb(), parse_mode="HTML")


@dp.message(Command("mytag"))
async def cmd_my_tag(message: types.Message, state: FSMContext):
    await state.clear()
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT admin_tag FROM admins WHERE user_id = %s", (message.from_user.id,))
            row = cursor.fetchone()
    if row and row[0]:
        await message.answer(f"🖤 Твой тег: <b>{html.escape(row[0])}</b>", reply_markup=get_tag_management_kb(), parse_mode="HTML")
    else:
        await message.answer("⚠️ У тебя нет тега! Установи его: <code>/settag #Тег</code>", parse_mode="HTML")


@dp.callback_query(F.data == "change_admin")
async def process_change_admin(call: types.CallbackQuery, state: FSMContext):
    await state.clear()
    
    user_info = get_user(call.from_user.id)
    if user_info:
        existing_topic_id = user_info[14] if len(user_info) > 14 and user_info[14] else (user_info[4] if len(user_info) > 4 else None)
        if existing_topic_id:
            try:
                await bot.edit_forum_topic(chat_id=GROUP_CHAT_ID, message_thread_id=existing_topic_id, name="Смена администратора")
            except Exception as e:
                logging.error(f"⚠️ Не удалось переименовать топик в «Смена администратора»: {e}")

    reset_user_admin(call.from_user.id)
    set_user_state(call.from_user.id, None)
    await call.message.edit_text("🔄 Смена администратора.\n\n👀 Выберите новую категорию для общения:", reply_markup=get_change_categories_keyboard(), parse_mode="HTML")


@dp.callback_query(F.data == "change_tag_prompt")
async def change_tag_prompt(call: types.CallbackQuery):
    await call.message.edit_text("Напиши команду снова: <code>/settag #НовыйТег</code>", parse_mode="HTML")


@dp.callback_query(F.data == "delete_tag_confirm")
async def delete_tag_confirm(call: types.CallbackQuery):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM admins WHERE user_id = %s", (call.from_user.id,))
            conn.commit()
    await call.message.edit_text("❌ Тег удалён.")


@dp.message(F.chat.id == GROUP_CHAT_ID, Command("ban"))
async def cmd_ban_user_in_group(message: types.Message):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT admin_tag FROM admins WHERE user_id = %s", (message.from_user.id,))
            admin_row = cursor.fetchone()

    if not admin_row or not admin_row[0]:
        await message.reply("⚠️ У вас нет тега! Установите его командой /settag #Тег")
        return
        
    if not message.reply_to_message:
        await message.reply("⚠️ Ответьте этой командой на сообщение пользователя в группе!")
        return

    target_user_id = None
    reply_msg = message.reply_to_message

    if reply_msg.from_user.id == bot.id or reply_msg.from_user.id == message.from_user.id:
        await message.reply("⚠️ Нельзя забанить этого пользователя!")
        return

    reply_key = (GROUP_CHAT_ID, reply_msg.message_id)
    if reply_key in msg_map:
        val = msg_map[reply_key]
        target_user_id = val[0] if isinstance(val, tuple) else val
    else:
        for (c_id, m_id), mapped_val in msg_map.items():
            if c_id == GROUP_CHAT_ID and m_id == reply_msg.message_id:
                target_user_id = mapped_val[0] if isinstance(mapped_val, tuple) else mapped_val
                break

    if not target_user_id:
        target_user_id = reply_msg.from_user.id

    if not target_user_id or target_user_id == bot.id:
        await message.reply("⚠️ Не удалось определить пользователя для блокировки.")
        return

    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("UPDATE users SET banned_by_admin = 1, assigned_admin_id = NULL WHERE user_id = %s", (target_user_id,))
            conn.commit()
            
    await message.reply(f"🚫 Пользователь <code>{target_user_id}</code> внесён в чёрный список!", parse_mode="HTML")


# --- РАССЫЛКА ---

@dp.callback_query(F.data == "adm_broadcast")
async def adm_broadcast_start(call: types.CallbackQuery, state: FSMContext):
    if not is_owner(call.from_user.id):
        return

    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM users WHERE blocked = 0 AND banned_by_admin = 0")
            count = cursor.fetchone()[0]

    await state.set_state(AdminStates.broadcast_msg)
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="adm_back")]
        ]
    )
    
    await call.message.edit_text(
        f"📢 <b>Найдено активных пользователей: {count}</b>\n\n"
        f"Отправь мне сообщение, фото, видео или пересыл для рассылки.",
        reply_markup=kb,
        parse_mode="HTML",
    )


@dp.message(AdminStates.broadcast_msg, F.chat.type == "private")
async def adm_broadcast_preview(message: types.Message, state: FSMContext):
    await state.update_data(
        broadcast_msg_id=message.message_id, from_chat_id=message.chat.id
    )
    await state.set_state(AdminStates.confirm_broadcast)

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🚀 Отправить", callback_data="confirm_bc_send")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="confirm_bc_cancel")],
        ]
    )

    await message.answer(
        "🩸 <b>Предпросмотр рассылки:</b>\nТак сообщение улетит пользователям ⬇️",
        parse_mode="HTML",
    )
    await message.copy_to(chat_id=message.chat.id)
    await message.answer("Отправляем?", reply_markup=kb)


@dp.callback_query(F.data == "confirm_bc_cancel", AdminStates.confirm_broadcast)
async def adm_broadcast_cancel(call: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text("❌ Рассылка отменена.", reply_markup=get_admin_panel_kb())


@dp.callback_query(F.data == "confirm_bc_send", AdminStates.confirm_broadcast)
async def adm_broadcast_execute(call: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    msg_id = data["broadcast_msg_id"]
    from_chat = data["from_chat_id"]
    await state.clear()

    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT user_id FROM users WHERE blocked = 0 AND banned_by_admin = 0")
            users = cursor.fetchall()

    total_users = len(users)
    success, blocked = 0, 0

    await call.message.edit_text(f"⏳ Рассылка выполняется... (0/{total_users})")

    last_updated = 0

    for index, u in enumerate(users, start=1):
        u_id = u[0]
        try:
            await bot.copy_message(
                chat_id=u_id, from_chat_id=from_chat, message_id=msg_id
            )
            success += 1
        except Exception as e:
            error_str = str(e).lower()
            if "retry_after" in error_str:
                try:
                    sleep_match = re.search(r"retry after (\d+)", error_str)
                    sleep_time = int(sleep_match.group(1)) if sleep_match else 5
                    await asyncio.sleep(sleep_time)
                    await bot.copy_message(
                        chat_id=u_id, from_chat_id=from_chat, message_id=msg_id
                    )
                    success += 1
                    continue
                except Exception:
                    pass

            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        "UPDATE users SET blocked = 1 WHERE user_id = %s", (u_id,)
                    )
                    conn.commit()
            blocked += 1

        if index - last_updated >= 20 or index == total_users:
            try:
                await call.message.edit_text(
                    f"⏳ Рассылка выполняется...\n\n"
                    f"📊 Прогресс: <b>{index}/{total_users}</b>\n"
                    f"✅ Успешно: <b>{success}</b>\n"
                    f"🚫 Заблокировали: <b>{blocked}</b>",
                    parse_mode="HTML",
                )
                last_updated = index
            except Exception:
                pass

        await asyncio.sleep(0.03)

    await call.message.answer(
        f"✅ <b>Рассылка завершена!</b>\n\n"
        f"👥 Всего получателей: <b>{total_users}</b>\n"
        f"✅ Успешно отправлено: <b>{success}</b>\n"
        f"🚫 Заблокировали бота: <b>{blocked}</b>",
        parse_mode="HTML",
        reply_markup=get_admin_panel_kb(),
    )


# --- ОБРАБОТКА ЛИЧНЫХ СООБЩЕНИЙ ПОЛЬЗОВАТЕЛЕЙ ---
@dp.message(F.chat.type == "private") 
async def handle_private_message(message: types.Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state in [AdminStates.broadcast_msg.state, AdminStates.confirm_broadcast.state, AdminStates.write_review.state, AdminStates.edit_welcome.state, AdminStates.edit_rules.state]:
        return

    msg_text_or_caption = message.text or message.caption or ""
    
    is_note = msg_text_or_caption.startswith("//")

    user = get_user(message.from_user.id)
    if not user:
        register_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
        user = get_user(message.from_user.id)

    if user[7] == 1:
        await message.answer("Вы заблокированы в этом боте!")
        return

    update_user_streak(message.from_user.id)
    log_msg("incoming", message.from_user.id)

    if is_note:
        await message.react([types.ReactionTypeEmoji(emoji="✍️")])
        return

    assigned_admin = user[4]
    
    if current_state == AdminStates.waiting_change_category_text.state:
        data = await state.get_data()
        new_category = data.get("chosen_category", "Общение")
        await state.clear()
        set_user_state(message.from_user.id, None)

        clean_text = html.escape(msg_text_or_caption)
        
        raw_prev_cat = user[12] if len(user) > 12 and user[12] is not None else "Общение"
        raw_prev_admin = user[13] if len(user) > 13 and user[13] is not None else "Не было"
        
        prev_category = html.escape(str(raw_prev_cat))
        prev_admin = html.escape(str(raw_prev_admin))
        
        clean_name = html.escape(message.from_user.full_name or "Без имени")
        clean_username = html.escape(f"@{message.from_user.username}" if message.from_user.username else "нет юзернейма")

        app_text = (
            f"<b>СМЕНА АДМИНИСТРАТОРА</b>\n\n"
            f"<b>Прошлый администратор</b> {prev_category}\n"
            f"<b>Новая категория:</b> <b>{new_category}</b>\n"
            f"<b>Имя:</b> {clean_name}\n"
            f"<b>ID:</b> <code>{message.from_user.id}</code>\n"
            f"<b>Юзернейм:</b> {clean_username}\n\n"
            f"<b>Сообщение:</b>\n{clean_text}"
        )

        take_kb = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="🖤 Взять пользователя", callback_data=f"take_user_{message.from_user.id}")]]
        )

        try:
            sent_msg = await bot.send_message(
                chat_id=GROUP_CHAT_ID, 
                message_thread_id=APPLICATIONS_TOPIC_ID, 
                text=app_text, 
                reply_markup=take_kb, 
                parse_mode="HTML"
            )
            msg_map[(GROUP_CHAT_ID, sent_msg.message_id)] = (message.chat.id, message.message_id)
            await message.answer("🔄 Запрос на смену администратора отправлен в топик заявок.\nОжидай ответа.")
        except Exception as e:
            logging.error(f"❌ ОШИБКА ОТПРАВКИ СМЕНЫ АДМИНА: {e}")
            await message.answer(f"⚠️ Ошибка отправки заявки администраторам: {e}")
        return

    if current_state == AdminStates.waiting_category_text.state or not assigned_admin:
        data = await state.get_data()
        category = data.get("chosen_category", "Общение")
        await state.clear()
        set_user_state(message.from_user.id, None)

        clean_name = html.escape(message.from_user.full_name or "Без имени")
        clean_username = html.escape(f"@{message.from_user.username}" if message.from_user.username else "нет юзернейма")
        clean_text = html.escape(msg_text_or_caption)

        app_text = (
            f"🖤 <b>Новая заявка ({category})!</b>\n\n"
            f"<b>Имя:</b> {clean_name}\n"
            f"<b>Юзернейм:</b> {clean_username}\n"
            f"<b>ID:</b> <code>{message.from_user.id}</code>\n"
            f"<b>Категория:</b> <b>{category}</b>\n\n"
            f"<b>Сообщение:</b>\n{clean_text}"
        )

        take_kb = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="🖤 Взять пользователя", callback_data=f"take_user_{message.from_user.id}")]]
        )

        try:
            sent_msg = await bot.send_message(
                chat_id=GROUP_CHAT_ID, 
                message_thread_id=APPLICATIONS_TOPIC_ID, 
                text=app_text, 
                reply_markup=take_kb, 
                parse_mode="HTML"
            )
            msg_map[(GROUP_CHAT_ID, sent_msg.message_id)] = (message.chat.id, message.message_id)
            await message.answer("🖤 Твое сообщение отправлено администрации.\nОжидай ответа.")
        except Exception as e:
            logging.error(f"❌ ОШИБКА ОТПРАВКИ ЗАЯВКИ: {e}")
            await message.answer(f"⚠️ Ошибка отправки заявки администраторам: {e}")
        return

    try:
        reply_to_in_group = None
        if message.reply_to_message:
            key_user = (message.chat.id, message.reply_to_message.message_id)
            if key_user in msg_map:
                reply_to_in_group = msg_map[key_user][1]

        target_thread_id = user[14] if len(user) > 14 and user[14] else (user[4] if len(user) > 4 else None)

        copied = await bot.copy_message(
            chat_id=GROUP_CHAT_ID,
            message_thread_id=target_thread_id,
            from_chat_id=message.chat.id,
            message_id=message.message_id,
            reply_to_message_id=reply_to_in_group
        )
        
        msg_map[(message.chat.id, message.message_id)] = (GROUP_CHAT_ID, copied.message_id)
        msg_map[(GROUP_CHAT_ID, copied.message_id)] = (message.chat.id, message.message_id)

    except Exception as e:
        logging.error(f"⚠️ Ошибка пересылки в группу: {e}")


@dp.callback_query(F.data.startswith("take_user_"))
async def process_take_user(call: types.CallbackQuery):
    target_user_id = int(call.data.split("_")[2])

    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT admin_tag FROM admins WHERE user_id = %s", (call.from_user.id,))
            admin_row = cursor.fetchone()

    if not admin_row or not admin_row[0]:
        await call.answer("⚠️ Сначала установи свой тег командой /settag #Тег", show_alert=True)
        return

    admin_tag = admin_row[0]
    
    user_info = get_user(target_user_id)
    existing_topic_id = user_info[14] if user_info and len(user_info) > 14 and user_info[14] else (user_info[4] if user_info and len(user_info) > 4 else None)

    clean_name = html.escape(user_info[2] if user_info and user_info[2] else "Без имени")
    clean_username = html.escape(f"@{user_info[1]}" if user_info and user_info[1] else "нет юзера")
    clean_admin_tag = html.escape(admin_tag)

    topic_title = f"{clean_admin_tag} || {clean_name} || {clean_username} || {target_user_id}"

    try:
        if existing_topic_id:
            await bot.edit_forum_topic(chat_id=GROUP_CHAT_ID, message_thread_id=existing_topic_id, name=topic_title)
            final_topic_id = existing_topic_id
        else:
            new_topic = await bot.create_forum_topic(chat_id=GROUP_CHAT_ID, name=topic_title)
            final_topic_id = new_topic.message_thread_id
    except Exception as e:
        logging.error(f"⚠️ Ошибка создания/переименования топика: {e}")
        final_topic_id = existing_topic_id

    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE users SET admin_tag = %s, assigned_admin_id = %s, topic_id = %s, discussion_topic_id = %s WHERE user_id = %s", 
                (admin_tag, call.from_user.id, final_topic_id, final_topic_id, target_user_id)
            )
            conn.commit()

    await call.message.edit_text(f"{call.message.html_text}\n\n🖤 <b>Пользователя взял:</b> {clean_admin_tag}", parse_mode="HTML")

    change_kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔄 Сменить администратора", callback_data="change_admin")]])
    try:
        await bot.send_message(chat_id=target_user_id, text=f"🖤 Твой запрос принял администратор <b>{clean_admin_tag}</b>.", reply_markup=change_kb, parse_mode="HTML")
    except Exception:
        pass

    await call.answer("Вы успешно взяли пользователя!")


# --- ОБРАБОТКА СООБЩЕНИЙ АДМИНОВ В ГРУППЕ ---
@dp.message(F.chat.id == GROUP_CHAT_ID)
async def handle_admin_messages(message: types.Message):
    if message.text and message.text.startswith(("/ban", "/admin")):
        return

    msg_text_or_caption = message.text or message.caption or ""
    if msg_text_or_caption.startswith("//"):
        return

    thread_id = message.message_thread_id
    target_user_id = None
    reply_to_user_msg_id = None

    if message.reply_to_message:
        if message.reply_to_message.message_thread_id == APPLICATIONS_TOPIC_ID:
            return
            
        reply_key = (GROUP_CHAT_ID, message.reply_to_message.message_id)
        if reply_key in msg_map:
            target_user_id, reply_to_user_msg_id = msg_map[reply_key]

    if not target_user_id and thread_id and thread_id != APPLICATIONS_TOPIC_ID:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT user_id FROM users WHERE discussion_topic_id = %s OR topic_id = %s",
                    (thread_id, thread_id)
                )
                row = cursor.fetchone()
                if row:
                    target_user_id = row[0]

    if not target_user_id:
        if thread_id and thread_id != APPLICATIONS_TOPIC_ID:
            await message.reply("⚠️ Не удалось определить пользователя для этого топика.")
        return

    try:
        copied = await bot.copy_message(
            chat_id=target_user_id,
            from_chat_id=GROUP_CHAT_ID,
            message_id=message.message_id,
            reply_to_message_id=reply_to_user_msg_id
        )
        log_msg("outgoing")
        
        msg_map[(GROUP_CHAT_ID, message.message_id)] = (target_user_id, copied.message_id)
        msg_map[(target_user_id, copied.message_id)] = (GROUP_CHAT_ID, message.message_id)

    except Exception as e:
        err_str = str(e).lower()
        if "blocked" in err_str or "forbidden" in err_str or "user is deactivated" in err_str:
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("UPDATE users SET blocked = 1 WHERE user_id = %s", (target_user_id,))
                    conn.commit()
            await message.reply("🚫 Пользователь заблокировал бота.")
        else:
            retry_kb = InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="🔄 Повторить отправку", callback_data=f"retry_msg_{message.message_id}_{target_user_id}")]]
            )
            await message.reply("⚠️ Произошел технический сбой, повторить отправку сообщения?", reply_markup=retry_kb)
            logging.error(f"⚠️ Ошибка отправки ответа пользователю: {e}")


@dp.callback_query(F.data.startswith("retry_msg_"))
async def retry_send_message(call: types.CallbackQuery):
    parts = call.data.split("_")
    orig_msg_id = int(parts[2])
    target_user_id = int(parts[3])

    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT admin_tag FROM admins WHERE user_id = %s", (call.from_user.id,))
            admin_row = cursor.fetchone()

    if not admin_row or not admin_row[0]:
        await call.answer("⚠️ Нет доступа (нужен тег)", show_alert=True)
        return

    try:
        copied = await bot.copy_message(
            chat_id=target_user_id,
            from_chat_id=GROUP_CHAT_ID,
            message_id=orig_msg_id
        )
        log_msg("outgoing")
        msg_map[(GROUP_CHAT_ID, orig_msg_id)] = (target_user_id, copied.message_id)
        msg_map[(target_user_id, copied.message_id)] = (GROUP_CHAT_ID, orig_msg_id)
        
        await call.message.edit_text("✅ Сообщение успешно отправлено повторно!")
    except Exception as e:
        await call.answer(f"⚠️ Снова ошибка: {e}", show_alert=True)


@dp.message_reaction()
async def handle_reactions(reaction: MessageReactionUpdated):
    key = (reaction.chat.id, reaction.message_id)
    if key in msg_map:
        target_chat_id, target_msg_id = msg_map[key]
        try:
            await bot.set_message_reaction(chat_id=target_chat_id, message_id=target_msg_id, reaction=reaction.new_reaction)
        except Exception:
            pass


@dp.callback_query(F.data == "adm_back")
async def adm_back_to_panel(call: types.CallbackQuery):
    if not is_owner(call.from_user.id):
        return
    await call.message.edit_text("🖤 <b>Панель администратора:</b>", reply_markup=get_admin_panel_kb(), parse_mode="HTML")


@dp.callback_query(F.data == "adm_ban_list")
async def adm_ban_list(call: types.CallbackQuery):
    if not is_owner(call.from_user.id):
        return
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT user_id, full_name, username FROM users WHERE banned_by_admin = 1")
            rows = cursor.fetchall()
    if not rows:
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="adm_back")]])
        await call.message.edit_text("🚫 Чёрный список пуст.", reply_markup=kb, parse_mode="HTML")
        return
    kb_list = [[InlineKeyboardButton(text=f"🔓 Разбанить {uid}", callback_data=f"unban_user_{uid}")] for uid, _, _ in rows]
    kb_list.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="adm_back")])
    await call.message.edit_text("🚫 <b>Черный список:</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_list), parse_mode="HTML")


@dp.callback_query(F.data.startswith("unban_user_"))
async def adm_unban_user(call: types.CallbackQuery):
    target_uid = int(call.data.split("_")[2])
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("UPDATE users SET banned_by_admin = 0 WHERE user_id = %s", (target_uid,))
            conn.commit()
    await call.answer(f"Пользователь {target_uid} разблокирован!", show_alert=True)
    await adm_ban_list(call)


@dp.callback_query(F.data == "adm_stats")
async def adm_stats(call: types.CallbackQuery):
    if not is_owner(call.from_user.id):
        return

    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM users")
            total_users = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM users WHERE blocked = 1")
            bot_blocked = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM users WHERE banned_by_admin = 1")
            admin_banned = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM stats")
            total_msgs = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM stats WHERE msg_type = 'incoming'")
            in_msgs = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM stats WHERE msg_type = 'outgoing'")
            out_msgs = cursor.fetchone()[0]

    text = (
        f"📊 <b>Статистика бота:</b>\n\n"
        f"<b>Пользователи:</b>\n"
        f"• Всего пользователей: <b>{total_users}</b>\n"
        f"• Заблокировали бота: <b>{bot_blocked}</b>\n"
        f"• В черном списке у админов: <b>{admin_banned}</b>\n\n"
        f"<b>Сообщения:</b>\n"
        f"• Всего сообщений: <b>{total_msgs}</b>\n"
        f"• Входящих: <b>{in_msgs}</b>\n"
        f"• Ответов: <b>{out_msgs}</b>\n"
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="adm_back")]
        ]
    )
    await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")


@dp.callback_query(F.data == "adm_top")
async def adm_top_menu(call: types.CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📅 За день", callback_data="top_day"), InlineKeyboardButton(text="🗓 За неделю", callback_data="top_week")],
        [InlineKeyboardButton(text="📆 За месяц", callback_data="top_month")],
        [InlineKeyboardButton(text="←️ Назад", callback_data="adm_back")],
    ])
    await call.message.edit_text("🏆 Выберите период для топа активных:", reply_markup=kb, parse_mode="HTML")


@dp.callback_query(F.data.startswith("top_"))
async def show_top(call: types.CallbackQuery):
    period = call.data.split("_")[1]
    limit_date = datetime.now() - timedelta(days=1 if period == "day" else (7 if period == "week" else 30))
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT u.full_name, COUNT(a.user_id) as cnt FROM user_activity a JOIN users u ON a.user_id = u.user_id WHERE a.timestamp >= %s GROUP BY u.full_name ORDER BY cnt DESC LIMIT 10", (limit_date.strftime("%Y-%m-%d %H:%M:%S"),))
            rows = cursor.fetchall()
    text = "🏆 <b>Топ активных:</b>\n\n" + ("\n".join([f"{i}. {r[0]} — {r[1]} сообщ." for i, r in enumerate(rows, 1)]) if rows else "Нет активности.")
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="←️ Назад", callback_data="adm_top")]])
    await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")


@dp.callback_query(F.data == "adm_texts")
async def adm_texts_menu(call: types.CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Приветствие", callback_data="edit_txt_welcome")],
        [InlineKeyboardButton(text="Правила", callback_data="edit_txt_rules")],
        [InlineKeyboardButton(text="←️ Назад", callback_data="adm_back")],
    ])
    await call.message.edit_text("✏️ Редактирование текстов:", reply_markup=kb, parse_mode="HTML")


@dp.callback_query(F.data == "edit_txt_welcome")
async def edit_welcome_start(call: types.CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.edit_welcome)
    await call.message.edit_text("Пришли новый текст приветствия 🥀:")


@dp.message(AdminStates.edit_welcome)
async def edit_welcome_save(message: types.Message, state: FSMContext):
    set_setting("welcome", message.text or "")
    await state.clear()
    await message.answer("✅ Приветствие обновлено!", reply_markup=get_admin_panel_kb())


@dp.callback_query(F.data == "edit_txt_rules")
async def edit_rules_start(call: types.CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.edit_rules)
    await call.message.edit_text("Пришли новый текст правил 🥀:")


@dp.message(AdminStates.edit_rules)
async def edit_rules_save(message: types.Message, state: FSMContext):
    set_setting("rules", message.text or "")
    await state.clear()
    await message.answer("✅ Правила обновлены!", reply_markup=get_admin_panel_kb())


@dp.callback_query(F.data == "adm_tag_admins")
async def adm_tag_admins_list(call: types.CallbackQuery):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT user_id, admin_tag FROM admins")
            rows = cursor.fetchall()
    text = "🏷️ <b>Админы с тегами:</b>\n\n" + ("\n".join([f"• ID: <code>{r[0]}</code> — <b>{html.escape(r[1])}</b>" for r in rows]) if rows else "Нет тегов.")
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="←️ Назад", callback_data="adm_back")]])
    await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")

# --- ЗАПУСК БОТА ---

async def main():
    logging.basicConfig(level=logging.INFO)
    
    # Проверка подключения к PostgreSQL через asyncpg
    if DATABASE_URL:
        try:
            conn = await asyncpg.connect(DATABASE_URL)
            await conn.close()
            print("🖤 Успешное подключение к PostgreSQL через asyncpg!")
        except Exception as e:
            print(f"⚠️ Ошибка подключения к базе данных: {e}")

    # Инициализация базы данных и команд
    init_db()
    await set_bot_commands(bot)
    
    # Фоновая задача
    asyncio.create_task(check_streaks_daily_task())
    
    print("🥀 Бот успешно запущен!")
    
    # Запуск polling для бота без веб-сервера (подходит для VPS / Wispbyte)
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("🌑 Бот остановлен.")