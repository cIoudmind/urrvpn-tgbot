import sqlite3
import datetime
import requests
import json
import uuid
import asyncio
import base64
import traceback

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

# --- 1. Основные Константы Бота, Платежей и Webhook ---
BOT_TOKEN = "8398090520:AAFkaOvgYP7_01u88XOHGclvC6gKPOxQkXQ"
DB_NAME = 'vpn_sales.db'
XUI_INBOUND_ID = 9

# --- КЛЮЧИ ЮKASSA ---
YOOKASSA_SHOP_ID = "1189951" 
YOOKASSA_SECRET_KEY = "live_qGlOT48V-6XAdzTA35GP2wEfC5fZ6sLgiCsxIDIv6MY"
 
YOOKASSA_WEBHOOK_PORT = 8443 
YOOKASSA_WEBHOOK_URL = "/yookassa_webhook" 

# --- 2. Константы 3x-ui Панели ---
# Пример: http://185.114.73.28:9421
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
# здесь НЕ используем глобальную сессию для 3x-ui, будем создавать локальные сессии там, где нужно

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


# --- Логика 3x-ui API (с исправлениями) ---

def login_3xui_session(timeout=10):
    """
    Авторизуется в 3x-ui и возвращает requests.Session() с cookies (если успешно) или None.
    """
    try:
        session = requests.Session()
        login_url = f"{XUI_PANEL_HOST}/login"
        resp = session.post(login_url, data={'username': XUI_USERNAME, 'password': XUI_PASSWORD}, timeout=timeout)
        resp.raise_for_status()

        # Проверим, что получили cookie сессии (обычно есть набор cookies)
        cookies = session.cookies.get_dict()
        if not cookies:
            # возможно панель возвращает токен в JSON — попробуем проверить body
            try:
                j = resp.json()
                # если в json есть token — можно добавить в headers (вариант для разных реализаций)
                if isinstance(j, dict) and j.get('token'):
                    session.headers.update({"Authorization": f"Bearer {j['token']}"})
                else:
                    print("warning: login to 3x-ui succeeded but cookies/token not found. Response:", j)
            except Exception:
                print("warning: login to 3x-ui succeeded but no cookies and response is not json.")
        return session

    except requests.exceptions.RequestException as e:
        print("Ошибка авторизации в 3x-ui:", e)
        return None


def create_3xui_user(user_email: str, expiry_days: int, inbound_id: int):
    """
    Создаёт клиента в 3x-ui и возвращает (config_link, None) при успешном создании,
    или (None, error_message).
    """
    client_uuid = str(uuid.uuid4())
    expiry_timestamp_ms = int((datetime.datetime.now() + datetime.timedelta(days=expiry_days)).timestamp() * 1000)
    
    session = login_3xui_session()
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

    # Правильный endpoint (используем /xui/inbound/addClient)
    add_client_url = f"{XUI_PANEL_HOST}/xui/inbound/addClient"

    # Формируем payload в том виде, который ожидает XUI:
    payload = {
        "id": inbound_id,
        "settings": json.dumps({"clients": [client_settings]})
    }

    try:
        resp = session.post(add_client_url, json=payload, timeout=10)
        resp.raise_for_status()
        try:
            result = resp.json()
        except Exception:
            return None, f"3x-ui: неожиданный ответ (не JSON): {resp.text[:500]}"

        # Обычная схема: result должен содержать success=True или подобное
        if result.get("success") or result.get("code") == 0 or result.get("data") is not None:
            # Попытка получить готовую ссылку конфигурации через известные (встречающиеся) endpoint'ы
            # 1) попробуем вызвать /xui/inbound/getClientConfig (если присутствует на сервере)
            config_link = None
            try:
                get_config_url = f"{XUI_PANEL_HOST}/xui/inbound/getClientConfig"
                cfg_payload = {"inboundId": inbound_id, "clientId": client_uuid}
                r2 = session.post(get_config_url, json=cfg_payload, timeout=8)
                if r2.ok:
                    try:
                        j2 = r2.json()
                        # возможные поля: j2.get("config") или j2.get("data") и т.д.
                        if isinstance(j2, dict):
                            # ищем явную ссылку
                            for k in ("config", "uri", "link", "data"):
                                if k in j2 and isinstance(j2[k], str) and j2[k].startswith(("vmess://", "vless://", "trojan://", "ss://")):
                                    config_link = j2[k]
                                    break
                            # если data содержит вложенность
                            if not config_link and isinstance(j2.get("data"), dict):
                                for k in ("config", "uri", "link"):
                                    if k in j2["data"] and isinstance(j2["data"][k], str):
                                        config_link = j2["data"][k]
                                        break
                    except Exception:
                        pass
            except Exception:
                pass

            # 2) fallback: иногда панели используют /sub/<client_uuid>
            if not config_link:
                # Если XUI_PANEL_HOST содержит порт, возьмём только hostname:port для ссылки
                # Формируем простую подпись — лучше её заменить реальным шаблоном, если панель даёт другой формат
                config_link = f"{XUI_PANEL_HOST}/sub/{client_uuid}"

            return config_link, None

        else:
            # Попытка вернуть читаемую ошибку от панели
            msg = result.get('msg') or result.get('message') or str(result)
            return None, f"Ошибка API 3x-ui: {msg}"

    except requests.exceptions.RequestException as e:
        tb = traceback.format_exc()
        return None, f"Ошибка подключения к 3x-ui панели: {e}\n{tb}"


# --- Логика ЮKassa API (Синхронная) ---

def create_yookassa_payment(user_id: int, tariff_key: str, amount: int, bot_username: str):
    """Создаёт платеж через YooKassa и возвращает (payment_url, None) или (None, error_msg)."""
    payment_url = "https://api.yookassa.ru/v3/payments"
    try:
        # Используем HTTP Basic Auth — безопаснее и проще
        auth = HTTPBasicAuth(YOOKASSA_SHOP_ID, YOOKASSA_SECRET_KEY)
        headers = {
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

        resp = requests.post(payment_url, auth=auth, headers=headers, data=json.dumps(payload), timeout=10)
        resp.raise_for_status()
        result = resp.json()

        confirmation = result.get('confirmation', {})
        confirmation_url = confirmation.get('confirmation_url') or confirmation.get('url')
        if confirmation_url:
            return confirmation_url, None

        # Если нет confirmation_url, вернём сообщение об ошибке
        return None, f"Ошибка ЮKassa: {result.get('description') or json.dumps(result)}"

    except requests.exceptions.RequestException as e:
        return None, f"Ошибка подключения к API ЮKassa: {e}"


# --- 4. АСИНХРОННАЯ ЛОГИКА ВЫДАЧИ КЛЮЧА (для Webhook) ---

async def issue_vpn_key_and_notify(user_id: int, tariff_key: str):
    """Асинхронно обрабатывает успешную оплату и выдает ключ."""
    try:
        tariff = TARIFS.get(tariff_key)
        if not tariff:
            print(f"Ошибка Webhook: Неизвестный тариф {tariff_key}")
            return

        expiry_days = tariff['days']
        loop = asyncio.get_event_loop()

        # Создаём клиента в XUI (синхронная функция в executor)
        config_link, error_msg = await loop.run_in_executor(
            None,
            create_3xui_user,
            f"tg-{user_id}",
            expiry_days,
            XUI_INBOUND_ID
        )

        if error_msg:
            print("create_3xui_user error:", error_msg)
            try:
                await bot.send_message(user_id, f"❌ **Критическая ошибка!** Оплата прошла, но не удалось создать ключ VPN.\n\nОписание: {error_msg}\nСвяжитесь с поддержкой.")
            except Exception as e:
                print("Не удалось отправить сообщение пользователю:", e)
            return

        # Обновление БД
        end_date = (datetime.date.today() + datetime.timedelta(days=expiry_days)).isoformat()
        await loop.run_in_executor(None, update_subscription, user_id, end_date, config_link)

        # Отправка ключа пользователю
        try:
            await bot.send_message(
                user_id,
                f"✅ **Оплата подтверждена!**\n"
                f"🎉 Подписка на **{tariff['label']}** активна до: **{end_date}**.\n\n"
                f"🔗 **Ваша VPN-конфигурация:**\n`{config_link}`"
            )
        except Exception as e:
            print("Ошибка отправки сообщения с ключом:", e)

    except Exception as e:
        print("Ошибка в issue_vpn_key_and_notify:", e, traceback.format_exc())


# --- 5. ОБРАБОТЧИК WEBHOOK ЮKASSA (AIOHTTP) ---

async def yookassa_webhook_handler(request):
    """Принимает уведомления от ЮKassa."""
    try:
        data = await request.json()
    except Exception:
        return web.Response(status=400, text="Invalid JSON")

    # (Опционально) Здесь можно проверять подпись/хедер от YooKassa для безопасности

    # Обрабатываем событие успешного платежа
    try:
        if data.get('event') == 'payment.succeeded' or data.get('type') == 'payment.succeeded':
            metadata = data.get('object', {}).get('metadata', {}) if data.get('object') else data.get('metadata', {})
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
    except Exception as e:
        print("Ошибка обработки webhook payload:", e, traceback.format_exc())

    return web.Response(status=200)


# --- Обработчики Telegram ---

def get_tariffs_keyboard():
    builder = InlineKeyboardBuilder() 
    for key, data in TARIFS.items():
        button_text = f"{data['label']} - {data['price'] / 100:.2f} RUB"
        builder.row(InlineKeyboardButton(text=button_text, callback_data=f"start_yookassa_{key}")) 
    return builder.as_markup()

@dp.message(Command("start", "buy"))
async def cmd_buy(message: types.Message):
    await message.answer("Выберите подходящий тариф:", reply_markup=get_tariffs_keyboard())

@dp.callback_query(lambda c: c.data and c.data.startswith('start_yookassa_'))
async def process_tariff_selection(callback_query: types.CallbackQuery):
    await bot.answer_callback_query(callback_query.id)

    user_id = callback_query.from_user.id
    PREFIX = 'start_yookassa_'
    tariff_key = callback_query.data[len(PREFIX):]

    tariff = TARIFS.get(tariff_key)
    if not tariff:
        await bot.send_message(user_id, f"Неизвестный тариф: {tariff_key}")
        return

    loop = asyncio.get_event_loop()
    payment_url, error_msg = await loop.run_in_executor(
        None,
        create_yookassa_payment,
        user_id, tariff_key, tariff['price'], BOT_USERNAME
    )

    if error_msg:
        await bot.send_message(user_id, f"Ошибка создания платежа: {error_msg}")
        return

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
    global BOT_USERNAME

    try:
        me = await bot.get_me()
        BOT_USERNAME = me.username
        print(f"Бот авторизован как @{BOT_USERNAME}")
    except Exception as e:
        print(f"Критическая ошибка: Не удалось получить имя пользователя бота! {e}")
        return

    # AioHTTP webhook server
    app = web.Application()
    app.router.add_post(YOOKASSA_WEBHOOK_URL, yookassa_webhook_handler)

    runner = web.AppRunner(app)
    await runner.setup()

    site = web.TCPSite(runner, '0.0.0.0', YOOKASSA_WEBHOOK_PORT)
    print(f"Webhook-сервер запущен на порту {YOOKASSA_WEBHOOK_PORT}...")
    await site.start()

    print("Бот запущен (polling)...")
    await dp.start_polling(bot, skip_updates=True)


if __name__ == '__main__':
    try:
        init_db()
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Бот остановлен.")
    except Exception as e:
        print(f"Критическая ошибка при запуске: {e}", traceback.format_exc())
