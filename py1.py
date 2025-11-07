import sqlite3
import datetime
import requests
import json
import uuid
import asyncio

from aiogram import Bot, Dispatcher, types
from aiogram.utils.keyboard import InlineKeyboardBuilder # Добавить этот импорт
from aiogram.types import LabeledPrice, PreCheckoutQuery, InlineKeyboardMarkup, InlineKeyboardButton, Message, CallbackQuery
from aiogram.filters import Command
# F и другие ненужные импорты удалены

# --- 1. Основные Константы Бота и Платежей ---
BOT_TOKEN = "8270650286:AAGG3eWhr8jB5DrC5HnPoJ4NxMbJYMUFEos"
PAYMENTS_TOKEN = "390540012:LIVE:80778"
DB_NAME = 'vpn_sales.db'
XUI_INBOUND_ID = 11 # ID Входящего соединения (Inbound) в 3x-ui, который будет использоваться (например, VLESS).

# --- 2. Константы 3x-ui Панели (для автоматизации) ---
XUI_PANEL_HOST = "http://185.114.73.28:9421" # Пример: http://123.45.67.89:54321
XUI_USERNAME = "T0IoWo99kh"
XUI_PASSWORD = "MDNoJDxu3D"

# --- 3. Тарифы (Цена указывается в копейках!) ---
TARIFS = {
    '3 day': {'label': '3 дня', 'days': 3, 'price': 300},
    '1_month': {'label': '1 Месяц', 'days': 30, 'price': 9000},
    '3_months': {'label': '3 Месяца', 'days': 90, 'price': 23000},
    '6_months': {'label': '6 Месяцев', 'days': 180, 'price': 40500}
}

# --- Инициализация ---
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# --- База Данных ---
def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            subscription_end_date TEXT,
            config_link TEXT
        )
    """)
    conn.commit()
    conn.close()

def update_subscription(user_id, end_date, config_link):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        "REPLACE INTO users (user_id, subscription_end_date, config_link) VALUES (?, ?, ?)",
        (user_id, end_date, config_link)
    )
    conn.commit()
    conn.close()

# --- Логика 3x-ui API ---

def login_3xui():
    """Авторизуется в 3x-ui и возвращает объект сессии с куками."""
    try:
        session = requests.Session()
        login_url = f"{XUI_PANEL_HOST}/login"
        
        response = session.post(
            login_url,
            data={'username': XUI_USERNAME, 'password': XUI_PASSWORD}
        )
        response.raise_for_status()
        
        if response.status_code == 200:
            return session
        
        return None
    except requests.exceptions.RequestException as e:
        print(f"Ошибка авторизации в 3x-ui: {e}")
        return None

def create_3xui_user(user_email: str, expiry_days: int, inbound_id: int):
    """Создает нового клиента в 3x-ui и возвращает его конфигурационную ссылку."""
    
    # Генерация UUID и времени до авторизации/API-запросов
    client_uuid = str(uuid.uuid4())
    expiry_timestamp_ms = int((datetime.datetime.now() + datetime.timedelta(days=expiry_days)).timestamp() * 1000)
    
    session = login_3xui()
    if not session:
        return None, "Ошибка авторизации в 3x-ui."

    client_settings = {
        "id": client_uuid,
        "email": user_email,
        "flow": "",
        "limitIp": 0,
        "totalGB": 0,
        "expiryTime": expiry_timestamp_ms,
        "enable": True,
        "tgId": "",
        "subId": ""
    }
    
    add_client_url = f"{XUI_PANEL_HOST}/panel/inbound/addClient"
    
    payload = {
        "id": inbound_id,
        "settings": json.dumps({"clients": [client_settings]})
    }

    try:
        response = session.post(
            add_client_url,
            data={"inboundId": inbound_id, "settings": json.dumps({"clients": [client_settings]})},
            headers={'Content-Type': 'application/x-www-form-urlencoded'}
        )
        response.raise_for_status()
        result = response.json()

        if result.get("success"):
            config_link = f"vless://{client_uuid}@184.114.73.28:11?security=reality&type=tcp&headerType=none#TelegramBot-{user_email}"
            return config_link, None
        else:
            return None, f"Ошибка API 3x-ui: {result.get('msg', 'Неизвестная ошибка')}"

    except requests.exceptions.RequestException as e:
        return None, f"Ошибка подключения к 3x-ui панели: {e}"

# --- Обработчики Telegram ---

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def get_tariffs_keyboard():
    """Создает клавиатуру с четырьмя кнопками-ссылками."""
    
    # Инициализируем Builder
    builder = InlineKeyboardBuilder() 
     
    # --- Кнопка 1: 1m ---
    builder.row(
        InlineKeyboardButton(
            text="3 дня", 
            url='https://yookassa.ru/my/i/aQ5D948uFTGN/l' 
        )
    ) 
    # --- Кнопка 1: 1m ---
    builder.row(
        InlineKeyboardButton(
            text="1 месяц", 
            url='https://yookassa.ru/my/i/aPp3zCBtV6Ay/l' 
        )
    ) 
        
    # --- Кнопка 2: 3m ---
    builder.row(
        InlineKeyboardButton(
            text="3 месяца", 
            url='https://yookassa.ru/my/i/aPp6BSUj9gDQ/l'
        )
    )

    # --- Кнопка 3: 6m---
    builder.row(
        InlineKeyboardButton(
            text="6 месяцев", 
            url='https://yookassa.ru/my/i/aPp6LGRV67Kw/l'
        )
    )
     # --- Кнопка 4: Наш Канал ---
    builder.row(
        InlineKeyboardButton(
            text="📢 Наш Канал", 
            url='https://t.me/urr_VPN'
        )
    )
    # Возвращаем готовую клавиатуру
    return builder.as_markup()
@dp.message(Command("start", "buy"))
async def cmd_buy(message: types.Message):
    await message.answer("Выберите подходящий тариф:", reply_markup=get_tariffs_keyboard())

# --- Обработчик выбора тарифа (Callback) ---
@dp.callback_query(lambda c: c.data and c.data.startswith('buy_tariff_'))
async def process_tariff_selection(callback_query: types.CallbackQuery):
    tariff_key = callback_query.data.split('_')[-1]
    tariff = TARIFS.get(tariff_key)
    
    if not tariff:
        await bot.answer_callback_query(callback_query.id, "Неизвестный тариф.", show_alert=True)
        return
        
    await bot.answer_callback_query(callback_query.id)
    
    if PAYMENTS_TOKEN.split(':')[1] == 'TEST':
        await bot.send_message(callback_query.from_user.id, "Внимание! Используется **ТЕСТОВЫЙ** платеж.", parse_mode="Markdown")

    # Создаем инвойс для Telegram Payments
    await bot.send_invoice(
        chat_id=callback_query.from_user.id,
        title=tariff['label'],
        description=tariff['label'] + " подписка на VPN.",
        payload=f'vpn_{tariff_key}_{callback_query.from_user.id}',
        provider_token=PAYMENTS_TOKEN,
        currency='RUB',
        prices=[
            LabeledPrice(label=tariff['label'], amount=tariff['price'])
        ],
        start_parameter=f'purchase_{tariff_key}',
        is_flexible=False
    )

# --- Обработка Pre-Checkout (Обязательно для всех платежей) ---
@dp.pre_checkout_query(lambda query: True)
async def process_pre_checkout_query(pre_checkout_query: PreCheckoutQuery):
    await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)

# --- Обработка успешного платежа ---
# Проверяем, что объект successful_payment существует
@dp.message(lambda m: m.successful_payment)
async def process_successful_payment(message: types.Message):
    user_id = message.from_user.id
    payload = message.successful_payment.invoice_payload
    
    # Извлекаем тариф и количество дней из payload
    try:
        tariff_key = payload.split('_')[1]
        tariff = TARIFS.get(tariff_key)
        expiry_days = tariff['days']
    except Exception:
        expiry_days = 30
        tariff = {'label': 'Неизвестный', 'days': 30}
        
    # 1. Генерация ключа VPN (Интеграция с 3x-ui)
    user_email = f"tg-{user_id}"
    config_link, error_msg = create_3xui_user(user_email, expiry_days, XUI_INBOUND_ID)
    
    if error_msg:
        await bot.send_message(user_id, f"❌ **Критическая ошибка!** Оплата прошла, но не удалось создать ключ VPN (код: {error_msg}). Пожалуйста, свяжитесь со службой поддержки для ручной выдачи ключа.")
        return

    # 2. Обновление Базы Данных
    end_date = (datetime.date.today() + datetime.timedelta(days=expiry_days)).isoformat()
    update_subscription(user_id, end_date, config_link)
    
    # 3. Отправка ключа пользователю
    await bot.send_message(
        user_id,
        f"✅ **Оплата прошла успешно!**\n\n"
        f"🎉 Вы приобрели подписку на **{tariff['label']}**.\n"
        f"Подписка активна до: **{end_date}**.\n\n"
        f"🔗 **Ваша VPN-конфигурация (VLESS/VMESS):**\n"
        f"`{config_link}`\n\n"
        f"Используйте эту ссылку для подключения в приложении (V2RayNG, Shadowrocket и т.д.)."
    )

if __name__ == '__main__':
    print("Бот запущен...")
    init_db()

    asyncio.run(dp.start_polling(bot))
