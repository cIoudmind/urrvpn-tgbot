
# Full patched bot.py (Variant 1: original full code + integrated fixes)

import sqlite3
import datetime
import requests
import json
import uuid
import asyncio
import base64
import traceback
import logging
import re
import time
from urllib.parse import urljoin, urlparse

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

# Disable SSL verification globally
requests.packages.urllib3.disable_warnings()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

BOT_TOKEN = "8398090520:AAFkaOvgYP7_01u88XOHGclvC6gKPOxQkXQ"
DB_NAME = 'vpn_sales.db'
XUI_INBOUND_ID = 9

YOOKASSA_SHOP_ID = "1189951" 
YOOKASSA_SECRET_KEY = "live_qGlOT48V-6XAdzTA35GP2wEfC5fZ6sLgiCsxIDIv6MY"
YOOKASSA_WEBHOOK_PORT = 8443 
YOOKASSA_WEBHOOK_URL = "/yookassa_webhook" 

XUI_PANEL_BASE = "http://185.114.73.28:9421"
XUI_USERNAME = "T0IoWo99kh"
XUI_PASSWORD = "MDNoJDxu3D"

TARIFS = {
    '3_day': {'label': '3 дня', 'days': 3, 'price': 300},
    '1_month': {'label': '1 Месяц', 'days': 30, 'price': 9000},
    '3_months': {'label': '3 Месяца', 'days': 90, 'price': 23000},
    '6_months': {'label': '6 Месяцев', 'days': 180, 'price': 40500}
}

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
BOT_USERNAME = None

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


# Patched SmartXUIPanel
class SmartXUIPanel:
    def __init__(self, base_url, username, password):
        self.base_url = base_url.rstrip('/')
        self.username = username
        self.password = password
        self.session = requests.Session()
        self.session.verify = False
        self.login_path = "/login"
        self.api_add_client = "/xui/inbound/addClient"

    def discover_panel(self):
        logger.info("Discovering real 3x-ui panel structure...")
        url = urlparse(self.base_url)
        host = url.hostname
        scheme = url.scheme
        ports = [url.port, 54321, 443, 8443, 80]
        paths = ["", "/xui"]

        for p in paths:
            for prt in ports:
                if not prt:
                    continue
                test = f"{scheme}://{host}:{prt}{p}"
                try:
                    r = requests.get(test, timeout=4, verify=False)
                    if r.status_code == 200 and ("username" in r.text.lower() and "password" in r.text.lower()):
                        logger.info(f"Panel found: {test}")
                        self.base_url = test
                        return True
                except:
                    pass

        logger.error("Panel not found")
        return False

    def login(self):
        logger.info("Login to panel...")
        login_url = self.base_url + self.login_path
        payload = {
            "username": self.username,
            "password": self.password
        }
        try:
            r = self.session.post(login_url, data=payload, timeout=10, verify=False, allow_redirects=True)
            if r.status_code in (200, 302):
                logger.info("Login OK")
                return True
            logger.error("Login failed")
            return False
        except Exception as e:
            logger.error(f"Login error: {e}")
            return False

    def create_client(self, email, expiry_days, inbound_id):
        if not self.login():
            return None, "Login failed"

        uuid_str = str(uuid.uuid4())
        expiry_ts = int((datetime.datetime.now() + datetime.timedelta(days=expiry_days)).timestamp() * 1000)

        payload = {
            "id": inbound_id,
            "settings": json.dumps({
                "clients": [
                    {
                        "id": uuid_str,
                        "email": email,
                        "enable": True,
                        "flow": "",
                        "limitIp": 0,
                        "totalGB": 0,
                        "expiryTime": expiry_ts
                    }
                ]
            })
        }

        url = self.base_url + self.api_add_client
        try:
            r = self.session.post(url, json=payload, timeout=10, verify=False)
            if r.status_code == 200 and ("success" in r.text or '"code":0' in r.text):
                return f"{self.base_url}/sub/{uuid_str}", None
            return None, "Error creating client"
        except Exception as e:
            return None, str(e)


xui_panel = SmartXUIPanel(XUI_PANEL_BASE, XUI_USERNAME, XUI_PASSWORD)


def create_3xui_user(user_email: str, expiry_days: int, inbound_id: int):
    try:
        config_link, err = xui_panel.create_client(user_email, expiry_days, inbound_id)
        return config_link, err
    except Exception as e:
        return None, str(e)


def create_yookassa_payment(user_id: int, tariff_key: str, amount: int, bot_username: str):
    try:
        auth = HTTPBasicAuth(YOOKASSA_SHOP_ID, YOOKASSA_SECRET_KEY)
        headers = {"Content-Type": "application/json", "Idempotence-Key": str(uuid.uuid4())}
        payload = {
            "amount": {"value": f"{amount / 100:.2f}", "currency": "RUB"},
            "confirmation": {"type": "redirect", "return_url": f"https://t.me/{bot_username}"},
            "capture": True,
            "description": f"Подписка VPN {TARIFS[tariff_key]['label']}",
            "metadata": {"tg_user_id": str(user_id), "tariff_key": tariff_key}
        }
        resp = requests.post("https://api.yookassa.ru/v3/payments", auth=auth, headers=headers, data=json.dumps(payload), timeout=10)
        resp.raise_for_status()
        result = resp.json()
        return result["confirmation"]["confirmation_url"], None
    except Exception as e:
        return None, str(e)


async def issue_vpn_key_and_notify(user_id: int, tariff_key: str):
    tariff = TARIFS[tariff_key]
    expiry_days = tariff['days']
    loop = asyncio.get_event_loop()

    config_link, err = await loop.run_in_executor(None, create_3xui_user, f"tg-{user_id}", expiry_days, XUI_INBOUND_ID)
    if err:
        await bot.send_message(user_id, f"Ошибка: {err}")
        return

    end_date = (datetime.date.today() + datetime.timedelta(days=expiry_days)).isoformat()
    await loop.run_in_executor(None, update_subscription, user_id, end_date, config_link)

    await bot.send_message(user_id, f"Ваш ключ: `{config_link}`")


async def yookassa_webhook_handler(request):
    try:
        data = await request.json()
        if data.get("event") == "payment.succeeded" or data.get("type") == "payment.succeeded":
            md = data.get("object", {}).get("metadata", {})
            user_id = int(md.get("tg_user_id"))
            tariff_key = md.get("tariff_key")
            asyncio.create_task(issue_vpn_key_and_notify(user_id, tariff_key))
    except:
        pass
    return web.Response(status=200)


def get_tariffs_keyboard():
    builder = InlineKeyboardBuilder()
    for key, data in TARIFS.items():
        builder.row(InlineKeyboardButton(text=f"{data['label']} - {data['price']/100:.2f} RUB", callback_data=f"start_yookassa_{key}"))
    return builder.as_markup()


@dp.message(Command("start", "buy"))
async def cmd_buy(message: types.Message):
    await message.answer("Выберите тариф:", reply_markup=get_tariffs_keyboard())


@dp.callback_query(lambda c: c.data and c.data.startswith('start_yookassa_'))
async def process(callback_query: CallbackQuery):
    await bot.answer_callback_query(callback_query.id)
    user_id = callback_query.from_user.id
    tariff_key = callback_query.data.split("_", 2)[2]
    tariff = TARIFS[tariff_key]

    loop = asyncio.get_event_loop()
    payment_url, err = await loop.run_in_executor(None, create_yookassa_payment, user_id, tariff_key, tariff['price'], BOT_USERNAME)

    if err:
        await bot.send_message(user_id, "Ошибка платежа")
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Оплатить", url=payment_url)]])
    await bot.send_message(user_id, "Перейдите к оплате:", reply_markup=kb)


@dp.message(Command("test_panel"))
async def cmd_test_panel(message: types.Message):
    ok = await asyncio.get_event_loop().run_in_executor(None, xui_panel.login)
    await message.answer("OK" if ok else "Fail")


async def main():
    global BOT_USERNAME
    init_db()
    me = await bot.get_me()
    BOT_USERNAME = me.username

    app = web.Application()
    app.router.add_post(YOOKASSA_WEBHOOK_URL, yookassa_webhook_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', YOOKASSA_WEBHOOK_PORT)
    await site.start()

    await dp.start_polling(bot, skip_updates=True)


if __name__ == '__main__':
    asyncio.run(main())

