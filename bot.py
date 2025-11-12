import sqlite3
import datetime
import requests
import json
import uuid
import asyncio
import base64
import traceback
import logging

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

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

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
XUI_PANEL_HOST = "http://185.114.73.28:9421"
XUI_USERNAME = "T0IoWo99kh"
XUI_PASSWORD = "MDNoJDxu3D"

# --- 3. Тарифы (Цена указывается в копейках!) ---
TARIFS = {
    '3_day': {'label': '3 дня', 'days': 3, 'price': 100},
    '1_month': {'label': '1 Месяц', 'days': 30, 'price': 9000},
    '3_months': {'label': '3 Месяца', 'days': 90, 'price': 23000},
    '6_months': {'label': '6 Месяцев', 'days': 180, 'price': 40500}
}

# --- Инициализация ---
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
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

# --- ИСПРАВЛЕННАЯ Логика 3x-ui API ---

def login_3xui_session(timeout=10):
    """
    Авторизуется в 3x-ui и возвращает requests.Session() с cookies.
    """
    try:
        session = requests.Session()
        login_url = f"{XUI_PANEL_HOST}/login"
        
        # Для 3x-ui обычно нужен POST с form data
        login_data = {
            'username': XUI_USERNAME,
            'password': XUI_PASSWORD
        }
        
        resp = session.post(login_url, data=login_data, timeout=timeout)
        resp.raise_for_status()

        # Проверяем успешность авторизации
        if resp.status_code == 200:
            logger.info("Успешная авторизация в 3x-ui")
            return session
        else:
            logger.error(f"Ошибка авторизации: {resp.status_code}")
            return None

    except requests.exceptions.RequestException as e:
        logger.error(f"Ошибка авторизации в 3x-ui: {e}")
        return None

def create_3xui_user(user_email: str, expiry_days: int, inbound_id: int):
    """
    Создаёт клиента в 3x-ui и возвращает (config_link, None) при успешном создании,
    или (None, error_message).
    """
    try:
        session = login_3xui_session()
        if not session:
            return None, "Ошибка авторизации в 3x-ui."

        # Генерируем UUID для клиента
        client_uuid = str(uuid.uuid4())
        
        # Вычисляем timestamp в миллисекундах
        expiry_date = datetime.datetime.now() + datetime.timedelta(days=expiry_days)
        expiry_timestamp_ms = int(expiry_date.timestamp() * 1000)

        # Получаем текущие настройки инбаунда
        inbound_list_url = f"{XUI_PANEL_HOST}/xui/inbound/list"
        resp = session.get(inbound_list_url, timeout=10)
        resp.raise_for_status()
        inbound_list = resp.json()

        # Находим нужный инбаунд
        target_inbound = None
        for inbound in inbound_list.get('obj', []):
            if inbound.get('id') == inbound_id:
                target_inbound = inbound
                break

        if not target_inbound:
            return None, f"Инбаунд с ID {inbound_id} не найден"

        # Парсим настройки инбаунда
        inbound_settings = json.loads(target_inbound['settings'])
        clients = inbound_settings.get('clients', [])

        # Проверяем, нет ли уже пользователя с таким email
        for client in clients:
            if client.get('email') == user_email:
                return None, f"Пользователь с email {user_email} уже существует"

        # Создаем нового клиента
        new_client = {
            "id": client_uuid,
            "email": user_email,
            "enable": True,
            "flow": "",
            "limitIp": 0,
            "totalGB": 0,
            "expiryTime": expiry_timestamp_ms,
            "tgId": "",
            "subId": ""
        }

        clients.append(new_client)
        inbound_settings['clients'] = clients

        # Обновляем инбаунд
        update_url = f"{XUI_PANEL_HOST}/xui/inbound/update/{inbound_id}"
        update_data = {
            "id": inbound_id,
            "settings": json.dumps(inbound_settings),
            "streamSettings": target_inbound.get('streamSettings', ''),
            "sniffing": target_inbound.get('sniffing', ''),
            "remark": target_inbound.get('remark', ''),
            "up": target_inbound.get('up', 0),
            "down": target_inbound.get('down', 0),
            "protocol": target_inbound.get('protocol', ''),
            "port": target_inbound.get('port', '')
        }

        resp = session.post(update_url, json=update_data, timeout=10)
        resp.raise_for_status()
        result = resp.json()

        if result.get('success', False):
            # Генерируем ссылку подписки
            config_link = f"{XUI_PANEL_HOST}/sub/{client_uuid}"
            logger.info(f"Успешно создан пользователь {user_email} с ссылкой {config_link}")
            return config_link, None
        else:
            error_msg = f"Ошибка создания пользователя: {result.get('msg', 'Unknown error')}"
            logger.error(error_msg)
            return None, error_msg

    except requests.exceptions.RequestException as e:
        error_msg = f"Ошибка сети при создании пользователя в 3x-ui: {str(e)}"
        logger.error(error_msg)
        return None, error_msg
    except Exception as e:
        error_msg = f"Неожиданная ошибка при создании пользователя в 3x-ui: {str(e)}"
        logger.error(error_msg)
        traceback.print_exc()
        return None, error_msg

# --- Логика ЮKassa API (Синхронная) ---

def create_yookassa_payment(user_id: int, tariff_key: str, amount: int, bot_username: str):
    """Создаёт платеж через YooKassa и возвращает (payment_url, None) или (None, error_msg)."""
    payment_url = "https://api.yookassa.ru/v3/payments"
    try:
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
            logger.info(f"Создан платеж для пользователя {user_id}, сумма: {amount/100} RUB")
            return confirmation_url, None

        return None, f"Ошибка ЮKassa: {result.get('description') or json.dumps(result)}"

    except requests.exceptions.RequestException as e:
        error_msg = f"Ошибка подключения к API ЮKassa: {e}"
        logger.error(error_msg)
        return None, error_msg

# --- АСИНХРОННАЯ ЛОГИКА ВЫДАЧИ КЛЮЧА (для Webhook) ---

async def issue_vpn_key_and_notify(user_id: int, tariff_key: str):
    """Асинхронно обрабатывает успешную оплату и выдает ключ."""
    try:
        tariff = TARIFS.get(tariff_key)
        if not tariff:
            logger.error(f"Ошибка Webhook: Неизвестный тариф {tariff_key}")
            return

        expiry_days = tariff['days']
        loop = asyncio.get_event_loop()

        # Создаём клиента в XUI
        config_link, error_msg = await loop.run_in_executor(
            None,
            create_3xui_user,
            f"tg-{user_id}",
            expiry_days,
            XUI_INBOUND_ID
        )

        if error_msg:
            logger.error(f"create_3xui_user error для пользователя {user_id}: {error_msg}")
            try:
                await bot.send_message(
                    user_id, 
                    f"❌ **Ошибка создания ключа!**\n\n"
                    f"Оплата прошла успешно, но возникла проблема с созданием VPN-ключа.\n"
                    f"Пожалуйста, свяжитесь с поддержкой.\n\n"
                    f"Код ошибки: {error_msg}"
                )
            except Exception as e:
                logger.error(f"Не удалось отправить сообщение пользователю {user_id}: {e}")
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
                f"🔗 **Ваша VPN-конфигурация:**\n`{config_link}`\n\n"
                f"💡 **Инструкция:**\n"
                f"1. Скопируйте ссылку выше\n"
                f"2. Вставьте в ваше VPN-приложение\n"
                f"3. Наслаждайтесь стабильным подключением!"
            )
            logger.info(f"Успешно выдан ключ пользователю {user_id}: {config_link}")
        except Exception as e:
            logger.error(f"Ошибка отправки сообщения с ключом пользователю {user_id}: {e}")

    except Exception as e:
        logger.error(f"Ошибка в issue_vpn_key_and_notify для пользователя {user_id}: {e}")
        traceback.print_exc()

# --- 5. ОБРАБОТЧИК WEBHOOK ЮKASSA (AIOHTTP) ---

async def yookassa_webhook_handler(request):
    """Принимает уведомления от ЮKassa."""
    try:
        data = await request.json()
        logger.info(f"Получен webhook от ЮKassa: {json.dumps(data, ensure_ascii=False)}")
    except Exception as e:
        logger.error(f"Ошибка парсинга JSON из webhook: {e}")
        return web.Response(status=400, text="Invalid JSON")

    try:
        if data.get('event') == 'payment.succeeded' or data.get('type') == 'payment.succeeded':
            metadata = data.get('object', {}).get('metadata', {}) if data.get('object') else data.get('metadata', {})
            user_id_str = metadata.get('tg_user_id')
            tariff_key = metadata.get('tariff_key')

            if user_id_str and tariff_key:
                try:
                    user_id = int(user_id_str)
                    logger.info(f"Обработка успешного платежа для пользователя {user_id}, тариф: {tariff_key}")
                    
                    # Запускаем асинхронную логику выдачи ключа
                    asyncio.create_task(issue_vpn_key_and_notify(user_id, tariff_key))
                    return web.Response(status=200, text="Webhook processed successfully")
                except ValueError:
                    logger.error(f"Ошибка Webhook: Неверный user_id {user_id_str}")
                    return web.Response(status=400, text="Invalid user_id")
            else:
                logger.warning(f"Webhook без user_id или tariff_key: {data}")
                return web.Response(status=400, text="Missing user_id or tariff_key")
                
    except Exception as e:
        logger.error(f"Ошибка обработки webhook payload: {e}")
        traceback.print_exc()

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
    await message.answer(
        "🔒 **Добро пожаловать в VPN сервис!**\n\n"
        "Выберите подходящий тариф:",
        reply_markup=get_tariffs_keyboard()
    )

@dp.callback_query(lambda c: c.data and c.data.startswith('start_yookassa_'))
async def process_tariff_selection(callback_query: types.CallbackQuery):
    await bot.answer_callback_query(callback_query.id)

    user_id = callback_query.from_user.id
    PREFIX = 'start_yookassa_'
    tariff_key = callback_query.data[len(PREFIX):]

    tariff = TARIFS.get(tariff_key)
    if not tariff:
        await bot.send_message(user_id, f"❌ Неизвестный тариф: {tariff_key}")
        return

    loop = asyncio.get_event_loop()
    payment_url, error_msg = await loop.run_in_executor(
        None,
        create_yookassa_payment,
        user_id, tariff_key, tariff['price'], BOT_USERNAME
    )

    if error_msg:
        await bot.send_message(
            user_id, 
            f"❌ **Ошибка создания платежа:**\n{error_msg}\n\n"
            f"Пожалуйста, попробуйте позже или свяжитесь с поддержкой."
        )
        return

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Перейти к оплате", url=payment_url)],
        [InlineKeyboardButton(text="🔄 Проверить оплату", callback_data=f"check_payment_{tariff_key}")]
    ])
    
    await bot.send_message(
        user_id, 
        f"💳 **Оплата тарифа: {tariff['label']}**\n"
        f"💰 Сумма: **{tariff['price'] / 100:.2f} RUB**\n\n"
        f"Для оплаты перейдите по ссылке ниже. После успешной оплаты ключ будет выдан автоматически в этом чате.", 
        reply_markup=keyboard
    )

@dp.callback_query(lambda c: c.data and c.data.startswith('check_payment_'))
async def check_payment_handler(callback_query: types.CallbackQuery):
    await bot.answer_callback_query(callback_query.id, "Проверяем статус оплаты...")
    await bot.send_message(callback_query.from_user.id, "ℹ️ Функция проверки оплаты в разработке. Ключ будет выдан автоматически после успешной оплаты.")

@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    await message.answer(
        "🤖 **Помощь по боту VPN сервиса**\n\n"
        "📋 **Доступные команды:**\n"
        "/start - Начать работу с ботом\n"
        "/buy - Выбрать тариф и оплатить\n"
        "/help - Показать эту справку\n\n"
        "❓ **Если возникли проблемы:**\n"
        "• После оплаты ключ приходит автоматически в течение 1-2 минут\n"
        "• Если ключ не пришел, свяжитесь с поддержкой\n"
        "• Сохраните вашу конфигурационную ссылку в надежном месте"
    )

# --- ЗАПУСК БОТА И WEBHOOK-СЕРВЕРА ---

async def main():
    global BOT_USERNAME

    try:
        # Инициализация базы данных
        init_db()
        logger.info("База данных инициализирована")

        # Получаем информацию о боте
        me = await bot.get_me()
        BOT_USERNAME = me.username
        logger.info(f"Бот авторизован как @{BOT_USERNAME}")

        # Проверяем подключение к 3x-ui
        test_session = login_3xui_session()
        if test_session:
            logger.info("Подключение к 3x-ui панели успешно")
        else:
            logger.warning("Не удалось подключиться к 3x-ui панели")

    except Exception as e:
        logger.error(f"Критическая ошибка при инициализации: {e}")
        return

    # AioHTTP webhook server
    app = web.Application()
    app.router.add_post(YOOKASSA_WEBHOOK_URL, yookassa_webhook_handler)

    runner = web.AppRunner(app)
    await runner.setup()

    try:
        site = web.TCPSite(runner, '0.0.0.0', YOOKASSA_WEBHOOK_PORT)
        logger.info(f"Webhook-сервер запущен на порту {YOOKASSA_WEBHOOK_PORT}...")
        await site.start()
    except Exception as e:
        logger.error(f"Ошибка запуска webhook-сервера: {e}")
        return

    logger.info("Бот запущен (polling)...")
    try:
        await dp.start_polling(bot, skip_updates=True)
    except Exception as e:
        logger.error(f"Ошибка при запуске polling: {e}")

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен по запросу пользователя")
    except Exception as e:
        logger.error(f"Критическая ошибка при запуске: {e}")
        traceback.print_exc()