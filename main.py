import asyncio
import logging
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, FSInputFile
import aiosqlite
from yookassa import Configuration, Payment
from remnawave import Remnawave # Импорт SDK

# --- КОНФИГУРАЦИЯ ---
BOT_TOKEN = "8676202349:AAE41BDCEZH-umAArDXxWV5ihuM6Vq9NnB8"
YOOKASSA_SHOP_ID = "1189951"
YOOKASSA_SECRET_KEY = "live_qGlOT48V-6XAdzTA35GP2wEfC5fZ6sLgiCsxIDIv6MY"
CRYPTOPAY_TOKEN = "537930:AAct27bQ2rg15R3nXNZKW4PR7xl2EYhDYju"

REMNAWAVE_URL = "https://bombompanel.mooo.com"
REMNAWAVE_API_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1dWlkIjoiM2FkMzlkZmYtMjMwNi00YmJkLWI1NzAtMmI4ZWQzN2JiYWM2IiwidXNlcm5hbWUiOm51bGwsInJvbGUiOiJBUEkiLCJpYXQiOjE3NzE5NDAzNjksImV4cCI6MTA0MTE4NTM5Njl9.FTSBSlyTzFDjaGIHv7N0SZGW2SRsRzywO9Pk8viSbaw"

Configuration.account_id = YOOKASSA_SHOP_ID
Configuration.secret_key = YOOKASSA_SECRET_KEY

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Инициализация клиента Remnawave
# (Точные методы зависят от версии SDK sm1ky, здесь приведен стандартный подход)
remnawave_client = Remnawave(url=REMNAWAVE_URL, api_key=REMNAWAVE_API_KEY)

# --- БАЗА ДАННЫХ ---
async def init_db():
    async with aiosqlite.connect("vpn_bot.db") as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                tg_id INTEGER PRIMARY KEY,
                username TEXT,
                sub_end TIMESTAMP,
                balance INTEGER DEFAULT 0,
                devices_total INTEGER DEFAULT 3,
                trial_used INTEGER DEFAULT 0,
                sub_link TEXT
            )
        """)
        await db.commit()

# --- КЛАВИАТУРЫ (Все кнопки внизу экрана) ---
def get_main_keyboard(trial_used: bool):
    buttons = [
        [KeyboardButton(text="👤 Профиль"), KeyboardButton(text="🛒 Тарифы")]
    ]
    if not trial_used:
        buttons.append([KeyboardButton(text="🎁 Начать пробный период 3 дня")])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

def get_profile_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="💳 Пополнить баланс"), KeyboardButton(text="📱 Доп. устройство (+50₽)")],
            [KeyboardButton(text="⬅️ Назад в меню")]
        ], resize_keyboard=True
    )

def get_tariffs_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="1 месяц - 150р"), KeyboardButton(text="3 месяца - 350р")],
            [KeyboardButton(text="6 месяцев - 600р")],
            [KeyboardButton(text="⬅️ Назад в меню")]
        ], resize_keyboard=True
    )

# --- ЛОГИКА REMNAWAVE ---
async def create_vpn_subscription(tg_id: int, username: str, expire_days: int):
    """
    Создает инбаунд в Remnawave. Имя = ник тг, в заметки/ID идет tg_id.
    """
    # ПРИМЕР вызова SDK (зависит от точной реализации remnawave-api):
    # try:
    #     response = await remnawave_client.create_user(
    #         username=username or str(tg_id),
    #         telegram_id=str(tg_id),
    #         expire_date=int((datetime.now() + timedelta(days=expire_days)).timestamp())
    #     )
    #     return response.sub_url
    # except Exception as e:
    #     logging.error(f"Remnawave Error: {e}")
    #     return "Ошибка_генерации_ссылки"
    return f"https://vpn-sub-link.com/{tg_id}" # Заглушка

# --- ХЭНДЛЕРЫ ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    tg_id = message.from_user.id
    username = message.from_user.username or f"user_{tg_id}"
    
    async with aiosqlite.connect("vpn_bot.db") as db:
        # Регистрация пользователя, если его нет
        await db.execute(
            "INSERT OR IGNORE INTO users (tg_id, username) VALUES (?, ?)", 
            (tg_id, username)
        )
        await db.commit()
        
        async with db.execute("SELECT trial_used FROM users WHERE tg_id = ?", (tg_id,)) as cursor:
            row = await cursor.fetchone()
            trial_used = bool(row[0]) if row else False

    welcome_text = (
        "👋 Добро пожаловать в лучший VPN сервис!\n\n"
        "🌍 **Наши локации:**\n"
        "🇳🇱 Нидерланды\n"
        "🇩🇪 Германия\n"
        "🇫🇮 Финляндия\n\n"
        "Выберите действие ниже:"
    )
    
    # ПОДСКАЗКА: Как вставить изображение.
    # Положи файл banner.jpg в ту же папку, где лежит скрипт.
    try:
        photo = FSInputFile("banner.jpg")
        await message.answer_photo(
            photo=photo, 
            caption=welcome_text, 
            reply_markup=get_main_keyboard(trial_used),
            parse_mode="Markdown"
        )
    except Exception as e:
        # Если картинки нет, отправляем просто текст
        await message.answer(welcome_text, reply_markup=get_main_keyboard(trial_used), parse_mode="Markdown")

@dp.message(F.text == "🎁 Начать пробный период 3 дня")
async def start_trial(message: types.Message):
    tg_id = message.from_user.id
    username = message.from_user.username or f"user_{tg_id}"

    async with aiosqlite.connect("vpn_bot.db") as db:
        async with db.execute("SELECT trial_used FROM users WHERE tg_id = ?", (tg_id,)) as cursor:
            row = await cursor.fetchone()
            if row and row[0] == 1:
                await message.answer("⚠️ Вы уже использовали пробный период!", reply_markup=get_main_keyboard(True))
                return

        # Создаем подписку через SDK
        sub_link = await create_vpn_subscription(tg_id, username, expire_days=3)
        end_date = datetime.now() + timedelta(days=3)

        await db.execute("""
            UPDATE users SET trial_used = 1, sub_end = ?, sub_link = ? WHERE tg_id = ?
        """, (end_date, sub_link, tg_id))
        await db.commit()

    await message.answer(
        f"✅ Пробный период на 3 дня успешно активирован!\n\n"
        f"🔗 Ваша ссылка для подключения:\n`{sub_link}`",
        reply_markup=get_main_keyboard(trial_used=True),
        parse_mode="Markdown"
    )

@dp.message(F.text == "👤 Профиль")
async def show_profile(message: types.Message):
    tg_id = message.from_user.id
    async with aiosqlite.connect("vpn_bot.db") as db:
        async with db.execute("SELECT * FROM users WHERE tg_id = ?", (tg_id,)) as cursor:
            user = await cursor.fetchone()

    if not user:
        return await message.answer("Пользователь не найден. Напишите /start")

    # Распаковка данных (согласно структуре БД)
    _, _, sub_end, balance, devices, _, sub_link = user
    
    status = "Неактивна"
    if sub_end:
        sub_end_date = datetime.strptime(sub_end, '%Y-%m-%d %H:%M:%S.%f')
        if sub_end_date > datetime.now():
            status = f"Активна до {sub_end_date.strftime('%d.%m.%Y')}"
            
    link_text = f"`{sub_link}`" if sub_link else "Отсутствует"

    profile_text = (
        f"👤 **Ваш профиль**\n"
        f"├ 🆔 Telegram ID: `{tg_id}`\n"
        f"├ ⏳ Подписка: {status}\n"
        f"├ 💰 Баланс: {balance} руб.\n"
        f"├ 📱 Доступно устройств: {devices}\n"
        f"└ 🔗 Ссылка: {link_text}"
    )

    await message.answer(profile_text, reply_markup=get_profile_keyboard(), parse_mode="Markdown")

@dp.message(F.text == "⬅️ Назад в меню")
async def back_to_menu(message: types.Message):
    async with aiosqlite.connect("vpn_bot.db") as db:
        async with db.execute("SELECT trial_used FROM users WHERE tg_id = ?", (message.from_user.id,)) as cursor:
            row = await cursor.fetchone()
            trial_used = bool(row[0]) if row else False
    await message.answer("Главное меню", reply_markup=get_main_keyboard(trial_used))

# --- ПРИМЕР ЛОГИКИ ОПЛАТЫ (ЮКАССА) ---
# Для полноценного WebHook ЮKassa нужен веб-сервер (aiohttp/FastAPI). 
# Здесь представлена логика генерации ссылки на оплату.
@dp.message(F.text == "💳 Пополнить баланс")
async def add_funds_prompt(message: types.Message):
    # В реальном боте здесь нужно сделать StateMachine для ввода суммы
    await message.answer("Функция пополнения. Выставьте счет через ЮKassa или CryptoBot. (Логика генерации платежа).")

async def main():
    logging.basicConfig(level=logging.INFO)
    await init_db()
    
    # Удаляем вебхуки, если они были, чтобы использовать long-polling для Telegram
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
    