import sqlite3
import datetime
import requests
import json
import uuid
import asyncio
import base64

from aiohttp import web 
from aiogram import Bot, Dispatcher, types
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    CallbackQuery
)
from aiogram.filters import Command
from requests.auth import HTTPBasicAuth

auth = HTTPBasicAuth('your_shop_id', 'your_secret_key')
response = requests.post('https://api.yookassa.ru/v3/payments', auth=auth, json=payload)


# --- 1. Основные Константы Бота, Платежей и Webhook ---
BOT_TOKEN = "8398090520:AAFkaOvgYP7_01u88XOHGclvC6gKPOxQkXQ"
DB_NAME = 'vpn_sales.db'
XUI_INBOUND_ID = 9

# --- КЛЮЧИ ЮKASSA ---
YOOKASSA_SHOP_ID = "1189951" 
YOOKASSA_SECRET_KEY = "390540012:LIVE:80778" 
YOOKASSA_WEBHOOK_PORT = 8443 
YOOKASSA_WEBHOOK_URL = "/yookassa_webhook" 

# --- 2. Константы 3x-ui Панели ---
XUI_PANEL_HOST = "http://185.114.73.28:9421"
XUI_USERNAME = "T0IoWo99kh"
XUI_PASSWORD = "MDNoJDxu3D"

# --- 3. Тарифы (Цена указывается в копейках!) ---
TARIFS = {
    '3_day': {'label': '3 дня', 'days': 3, 'price': 300},
    '1_month': {'label': '1 Месяц', 'days': 30, 'price': 9000},
    '3_months': {'label': '3 Месяца', 'days': 90, 'price': 23000},
    '6_months': {'label': '6 Месяцев', 'days': 180, 'price': 40500}
}

# --- Инициализация ---
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
api_session = requests.Session() 

# Глобальная переменная для username бота
BOT_USERNAME = None

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

# --- Логика 3x-ui API (Синхронная) ---

def login_3xui():
    """Авторизуется в 3x-ui и возвращает объект сессии с куками."""
    try:
        login_url = f"{XUI_PANEL_HOST}/login"
        response = api_session.post(
            login_url,
            data={'username': XUI_USERNAME, 'password': XUI_PASSWORD}
        )
        response.raise_for_status()
        if response.status_code == 200:
            return api_session
        return None
    except requests.exceptions.RequestException as e:
        print(f"Ошибка авторизации в 3x-ui: {e}")
        return None

def create_3xui_user(user_email: str, expiry_days: int, inbound_id: int):
    """Создает нового клиента в 3x-ui и возвращает его конфигурационную ссылку."""
    client_uuid = str(uuid.uuid4())
    expiry_timestamp_ms = int((datetime.datetime.now() + datetime.timedelta(days=expiry_days)).timestamp() * 1000)
    
    session = login_3xui()
    if not session:
        return None, "Ошибка авторизации в 3x-ui."

    client_settings = {
        "id": client_uuid,
        "email": user_email,
        "flow": "", "limitIp": 0, "totalGB": 0,
        "expiryTime": expiry_timestamp_ms,
        "enable": True, "tgId": "", "subId": ""
    }
    
    add_client_url = f"{XUI_PANEL_HOST}/panel/inbound/addClient"
    
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

# --- Логика ЮKassa API (Синхронная) ---

def create_yookassa_payment(user_id: int, tariff_key: str, amount: int, bot_username: str):
    """Создает платеж через API ЮKassa и возвращает URL для оплаты."""
    payment_url = "https://api.yookassa.ru/v3/payments"
    
    # Кодирование в Base64 для заголовка Authorization
    auth_string = f"{YOOKASSA_SHOP_ID}:{YOOKASSA_SECRET_KEY}"
    encoded_auth = base64.b64encode(auth_string.encode('utf-8')).decode('utf-8')
    
    headers = {
        "Authorization": f"Basic {encoded_auth}",
        "Content-Type": "application/json",
        "Idempotence-Key": str(uuid.uuid4())
    }
    
    payload = {
        "amount": {
            "value": f"{amount / 100:.2f}",
            "currency": "RUB"
        },
        "confirmation": {
            "type": "redirect",
            "return_url": f"https://t.me/{bot_username}"
        },
        "capture": True,
        "description": f"Подписка VPN {TARIFS[tariff_key]['label']}",
        "metadata": {
            "tg_user_id": str(user_id),
            "tariff_key": tariff_key
        }
    }
    
    try:
        response = api_session.post(payment_url, headers=headers, data=json.dumps(payload))
        response.raise_for_status()
        result = response.json()
        
        if result.get('confirmation', {}).get('confirmation_url'):
            return result['confirmation']['confirmation_url'], None
        
        return None, f"Ошибка ЮKassa: {result.get('description', 'Неизвестная ошибка')}"
        
    except requests.exceptions.RequestException as e:
        return None, f"Ошибка подключения к API ЮKassa: {e}"


# --- 4. АСИНХРОННАЯ ЛОГИКА ВЫДАЧИ КЛЮЧА (для Webhook) ---

async def issue_vpn_key_and_notify(user_id: int, tariff_key: str):
    """Асинхронно обрабатывает успешную оплату и выдает ключ."""
    
    tariff = TARIFS.get(tariff_key)
    if not tariff:
        print(f"Ошибка Webhook: Неизвестный тариф {tariff_key}")
        return
        
    expiry_days = tariff['days']
    
    # 1. Генерация ключа VPN (через Executor для синхронного вызова)
    loop = asyncio.get_event_loop()
    config_link, error_msg = await loop.run_in_executor(
        None, 
        create_3xui_user, 
        f"tg-{user_id}", expiry_days, XUI_INBOUND_ID
    )
    
    # 2. Обработка ошибок и уведомление
    if error_msg:
        await bot.send_message(user_id, f"❌ **Критическая ошибка!** Оплата прошла, но не удалось создать ключ VPN (код: {error_msg}). Свяжитесь с поддержкой.")
        return

    # 3. Обновление Базы Данных (через Executor)
    end_date = (datetime.date.today() + datetime.timedelta(days=expiry_days)).isoformat()
    await loop.run_in_executor(None, update_subscription, user_id, end_date, config_link)
    
    # 4. Отправка ключа пользователю
    await bot.send_message(
        user_id,
        f"✅ **Оплата подтверждена!**\n"
        f"🎉 Подписка на **{tariff['label']}** активна до: **{end_date}**.\n\n"
        f"🔗 **Ваша VPN-конфигурация:**\n`{config_link}`"
    )

# --- 5. ОБРАБОТЧИК WEBHOOK ЮKASSA (AIOHTTP) ---

async def yookassa_webhook_handler(request):
    """Принимает уведомления от ЮKassa."""
    try:
        data = await request.json()
    except json.JSONDecodeError:
        return web.Response(status=400, text="Invalid JSON")

    if data.get('event') == 'payment.succeeded':
        metadata = data.get('object', {}).get('metadata', {})
        user_id_str = metadata.get('tg_user_id')
        tariff_key = metadata.get('tariff_key')
        
        if user_id_str and tariff_key:
            try:
                user_id = int(user_id_str)
                # Запускаем асинхронную логику выдачи ключа
                asyncio.create_task(issue_vpn_key_and_notify(user_id, tariff_key))
                return web.Response(status=200) 
            except ValueError:
                print(f"Ошибка Webhook: Неверный user_id {user_id_str}")
                return web.Response(status=400)
    
    return web.Response(status=200)

# --- Обработчики Telegram ---

def get_tariffs_keyboard():
    """Создает клавиатуру с тарифами (Callback для запуска платежа)."""
    builder = InlineKeyboardBuilder() 
    
    for key, data in TARIFS.items():
        button_text = f"{data['label']} - {data['price'] / 100:.2f} RUB"
        builder.row(InlineKeyboardButton(text=button_text, callback_data=f"start_yookassa_{key}")) 
        
    return builder.as_markup()

@dp.message(Command("start", "buy"))
async def cmd_buy(message: types.Message):
    await message.answer("Выберите подходящий тариф:", reply_markup=get_tariffs_keyboard())

# --- Обработчик запуска платежа ЮKassa (Callback) ---
@dp.callback_query(lambda c: c.data and c.data.startswith('start_yookassa_'))
async def process_tariff_selection(callback_query: types.CallbackQuery):
    # Сразу отвечаем на callback query чтобы избежать ошибки "query is too old"
    await bot.answer_callback_query(callback_query.id)
    
    user_id = callback_query.from_user.id
    # ПРАВИЛЬНОЕ извлечение ключа тарифа из callback_data
    PREFIX = 'start_yookassa_'
    tariff_key = callback_query.data[len(PREFIX):]
    
    print(f"DEBUG: callback_data={callback_query.data}, tariff_key={tariff_key}")
    
    tariff = TARIFS.get(tariff_key)
    
    if not tariff:
        await bot.send_message(user_id, f"Неизвестный тариф: {tariff_key}")
        return

    # Асинхронно вызываем синхронную функцию создания платежа
    loop = asyncio.get_event_loop()
    payment_url, error_msg = await loop.run_in_executor(
        None, 
        create_yookassa_payment, 
        user_id, tariff_key, tariff['price'], BOT_USERNAME  # Передаем username как параметр
    )
    
    if error_msg:
        await bot.send_message(user_id, f"Ошибка создания платежа: {error_msg}")
        return

    # Отправляем пользователю ссылку для оплаты
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Перейти к оплате", url=payment_url)]
    ])
    await bot.send_message(
        user_id, 
        f"Чтобы оплатить **{tariff['label']}**, перейдите по ссылке ниже. После успешной оплаты, ключ будет выдан автоматически.", 
        reply_markup=keyboard
    )


# --- ЗАПУСК БОТА И WEBHOOK-СЕРВЕРА ---

async def main():
    """Основная функция запуска бота и Webhook-сервера."""
    global BOT_USERNAME

    # 1. Явно получаем информацию о боте и устанавливаем BOT_USERNAME
    try:
        me = await bot.get_me()
        BOT_USERNAME = me.username
        print(f"Бот авторизован как @{BOT_USERNAME}")
    except Exception as e:
        print(f"Критическая ошибка: Не удалось получить имя пользователя бота! {e}")
        return

    # 2. Настройка Webhook-сервера AioHTTP
    app = web.Application()
    app.router.add_post(YOOKASSA_WEBHOOK_URL, yookassa_webhook_handler)

    runner = web.AppRunner(app)
    await runner.setup()
    
    # Запуск на 0.0.0.0, чтобы слушать все внешние IP
    site = web.TCPSite(runner, '0.0.0.0', YOOKASSA_WEBHOOK_PORT) 
    
    print(f"Webhook-сервер запущен на порту {YOOKASSA_WEBHOOK_PORT}...")
    await site.start()
    
    # 3. Запуск бота (Polling)
    print("Бот запущен...")
    await dp.start_polling(bot, skip_updates=True)

if __name__ == '__main__':
    try:
        init_db()
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Бот остановлен.")
    except Exception as e:
        print(f"Критическая ошибка при запуске: {e}")
