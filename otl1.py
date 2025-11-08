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

# --- 1. Основные Константы Бота, Платежей и Webhook ---
BOT_TOKEN = "8270650286:AAGG3eWhr8jB5DrC5HnPoJ4NxMbJYMUFEos"
DB_NAME = 'vpn_sales.db'
XUI_INBOUND_ID = 9 

# --- Глобальная переменная для имени пользователя бота (для return_url ЮKassa) ---
BOT_USERNAME = None 

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

# --- База Данных ---
def init_db():
    """Инициализация базы данных и создание таблицы пользователей."""
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
    """Обновляет или создает запись о подписке пользователя."""
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
        if response.status_code == 200 and 'session' in api_session.cookies:
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
            # Формирование VLESS-ссылки. 
            config_link = f"vless://{client_uuid}@184.114.73.28:11?security=reality&type=tcp&headerType=none#TelegramBot-{user_email}"
            return config_link, None
        else:
            return None, f"Ошибка API 3x-ui: {result.get('msg', 'Неизвестная ошибка')}"

    except requests.exceptions.RequestException as e:
        return None, f"Ошибка подключения к 3x-ui панели: {e}"

# --- Логика ЮKassa API (Синхронная) ---

def create_yookassa_payment(user_id: int, tariff_key: str, amount: int):
    """Создает платеж через API ЮKassa и возвращает URL для оплаты."""
    payment_url = "https://api.yookassa.ru/v3/payments"
    
    # Использование глобального BOT_USERNAME, который гарантированно установлен в main()
    if not BOT_USERNAME:
        return None, "Ошибка: Имя пользователя бота недоступно."

    # Кодирование в Base64 для заголовка Authorization (ShopID:SecretKey)
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
            "type":
        }
