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
    '3_day': {'label': '3 дня', 'days': 3, 'price': 300},
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

# --- УНИВЕРСАЛЬНЫЙ КЛАСС ДЛЯ РАБОТЫ С X-UI ПАНЕЛЬЮ ---

class UniversalXUIPanel:
    def __init__(self, host, username, password):
        self.host = host.rstrip('/')
        self.username = username
        self.password = password
        self.session = None
        self.panel_type = None
        
    def login(self):
        """Универсальный метод авторизации"""
        try:
            self.session = requests.Session()
            self.session.headers.update({
                'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36',
                'Accept': '*/*',
                'Content-Type': 'application/x-www-form-urlencoded'
            })
            
            # Пробуем разные endpoint'ы и методы
            login_methods = [
                self._try_standard_login,
                self._try_json_login,
                self._try_with_csrf,
                self._try_ajax_endpoints
            ]
            
            for method in login_methods:
                logger.info(f"Пробуем метод: {method.__name__}")
                success = method()
                if success:
                    logger.info(f"✅ Авторизация успешна через {method.__name__}")
                    return True
            
            logger.error("❌ Все методы авторизации не сработали")
            return False
            
        except Exception as e:
            logger.error(f"❌ Ошибка авторизации: {e}")
            return False
    
    def _try_standard_login(self):
        """Стандартный логин через form data"""
        try:
            endpoints = [
                "/login",
                "/xui/login",
                "/api/login",
                "/auth/login",
                "/user/login"
            ]
            
            for endpoint in endpoints:
                login_data = {
                    'username': self.username,
                    'password': self.password
                }
                
                resp = self.session.post(
                    self.host + endpoint, 
                    data=login_data, 
                    timeout=15,
                    verify=False,
                    allow_redirects=True
                )
                
                logger.info(f"Endpoint {endpoint}: статус {resp.status_code}")
                
                if self._check_login_success(resp):
                    return True
                    
            return False
        except Exception as e:
            logger.error(f"Ошибка стандартного логина: {e}")
            return False
    
    def _try_json_login(self):
        """Логин через JSON"""
        try:
            endpoints = [
                "/login",
                "/api/login",
                "/xui/api/login"
            ]
            
            for endpoint in endpoints:
                login_data = {
                    'username': self.username,
                    'password': self.password
                }
                
                # Временно меняем заголовки для JSON
                original_headers = self.session.headers.copy()
                self.session.headers.update({'Content-Type': 'application/json'})
                
                resp = self.session.post(
                    self.host + endpoint,
                    json=login_data,
                    timeout=15,
                    verify=False
                )
                
                # Возвращаем оригинальные заголовки
                self.session.headers = original_headers
                
                logger.info(f"JSON {endpoint}: статус {resp.status_code}")
                
                if self._check_login_success(resp):
                    return True
                    
            return False
        except Exception as e:
            logger.error(f"Ошибка JSON логина: {e}")
            return False
    
    def _try_with_csrf(self):
        """Логин с получением CSRF токена"""
        try:
            # Сначала получаем страницу логина
            resp = self.session.get(self.host + "/login", timeout=10, verify=False)
            
            # Ищем CSRF токен в разных форматах
            csrf_patterns = [
                r'name=[\'"]_token[\'"]\s+value=[\'"]([^\'"]*)[\'"]',
                r'name=[\'"]csrf_token[\'"]\s+value=[\'"]([^\'"]*)[\'"]',
                r'csrf-token[\'"]\s+content=[\'"]([^\'"]*)[\'"]',
                r'"_token"\s*:\s*"([^"]+)"'
            ]
            
            csrf_token = None
            for pattern in csrf_patterns:
                match = re.search(pattern, resp.text, re.IGNORECASE)
                if match:
                    csrf_token = match.group(1)
                    break
            
            login_data = {
                'username': self.username,
                'password': self.password
            }
            
            if csrf_token:
                login_data['_token'] = csrf_token
                login_data['csrf_token'] = csrf_token
            
            resp = self.session.post(
                self.host + "/login",
                data=login_data,
                timeout=15,
                verify=False,
                allow_redirects=True
            )
            
            return self._check_login_success(resp)
            
        except Exception as e:
            logger.error(f"Ошибка CSRF логина: {e}")
            return False
    
    def _try_ajax_endpoints(self):
        """Пробуем AJAX endpoint'ы"""
        try:
            endpoints = [
                "/xui/API/inbound/add",
                "/api/v1/login",
                "/ajax/login"
            ]
            
            for endpoint in endpoints:
                login_data = {
                    'username': self.username,
                    'password': self.password
                }
                
                resp = self.session.post(
                    self.host + endpoint,
                    data=login_data,
                    timeout=15,
                    verify=False
                )
                
                if self._check_login_success(resp):
                    return True
                    
            return False
        except Exception as e:
            logger.error(f"Ошибка AJAX логина: {e}")
            return False
    
    def _check_login_success(self, response):
        """Проверяем успешность авторизации"""
        try:
            # Проверяем статус код
            if response.status_code != 200:
                return False
            
            # Проверяем текст ответа
            text_lower = response.text.lower()
            
            # Признаки успеха
            success_indicators = [
                'success' in text_lower,
                'true' in text_lower and 'false' not in text_lower,
                'dashboard' in text_lower,
                'welcome' in text_lower,
                'panel' in text_lower,
                '"success":true' in text_lower,
                '"code":0' in text_lower,
                '登录成功' in text_lower,  # Китайский
                '登录成功' in response.text  # Китайский UTF-8
            ]
            
            # Проверяем JSON ответ
            try:
                json_data = response.json()
                if json_data.get('success') or json_data.get('code') == 0:
                    return True
            except:
                pass
            
            # Проверяем редирект на dashboard
            if response.history and any('dashboard' in url.lower() for url in [r.url for r in response.history]):
                return True
            
            return any(success_indicators)
            
        except Exception as e:
            logger.error(f"Ошибка проверки успешности: {e}")
            return False
    
    def create_client(self, email, expiry_days, inbound_id):
        """Создает клиента в панели"""
        try:
            if not self.session:
                if not self.login():
                    return None, "Не удалось авторизоваться в панели"
            
            # Генерируем UUID
            client_uuid = str(uuid.uuid4())
            
            # Вычисляем timestamp
            expiry_date = datetime.datetime.now() + datetime.timedelta(days=expiry_days)
            expiry_timestamp = int(expiry_date.timestamp() * 1000)
            
            # Пробуем разные методы создания клиента
            creation_methods = [
                self._create_client_standard,
                self._create_client_direct,
                self._create_client_ajax
            ]
            
            for method in creation_methods:
                logger.info(f"Пробуем метод создания: {method.__name__}")
                config_link, error = method(email, client_uuid, expiry_timestamp, inbound_id)
                if config_link:
                    return config_link, None
            
            return None, "Все методы создания клиента не сработали"
            
        except Exception as e:
            error_msg = f"Ошибка создания клиента: {str(e)}"
            logger.error(error_msg)
            return None, error_msg
    
    def _create_client_standard(self, email, client_uuid, expiry_timestamp, inbound_id):
        """Стандартный метод создания клиента"""
        try:
            # Получаем текущие настройки инбаунда
            inbound_url = f"{self.host}/xui/inbound/list"
            resp = self.session.get(inbound_url, timeout=10, verify=False)
            
            if resp.status_code != 200:
                return None, "Не удалось получить список инбаундов"
            
            inbound_data = resp.json()
            target_inbound = None
            
            for inbound in inbound_data.get('obj', []):
                if inbound.get('id') == inbound_id:
                    target_inbound = inbound
                    break
            
            if not target_inbound:
                return None, f"Инбаунд с ID {inbound_id} не найден"
            
            # Парсим настройки
            inbound_settings = json.loads(target_inbound['settings'])
            clients = inbound_settings.get('clients', [])
            
            # Создаем нового клиента
            new_client = {
                "id": client_uuid,
                "email": email,
                "enable": True,
                "flow": "",
                "limitIp": 0,
                "totalGB": 0,
                "expiryTime": expiry_timestamp,
                "tgId": "",
                "subId": ""
            }
            
            # Проверяем на дубликат
            for client in clients:
                if client.get('email') == email:
                    return None, f"Клиент с email {email} уже существует"
            
            clients.append(new_client)
            inbound_settings['clients'] = clients
            
            # Обновляем инбаунд
            update_url = f"{self.host}/xui/inbound/update/{inbound_id}"
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
            
            resp = self.session.post(update_url, json=update_data, timeout=15, verify=False)
            
            if resp.status_code == 200:
                result = resp.json()
                if result.get('success', False):
                    config_link = f"{self.host}/sub/{client_uuid}"
                    return config_link, None
                else:
                    return None, f"Ошибка обновления: {result.get('msg', 'Unknown error')}"
            else:
                return None, f"HTTP ошибка: {resp.status_code}"
                
        except Exception as e:
            return None, f"Ошибка стандартного метода: {str(e)}"
    
    def _create_client_direct(self, email, client_uuid, expiry_timestamp, inbound_id):
        """Прямое создание клиента через API"""
        try:
            client_data = {
                "id": client_uuid,
                "email": email,
                "flow": "",
                "limitIp": 0,
                "totalGB": 0,
                "expiryTime": expiry_timestamp,
                "enable": True,
                "tgId": "",
                "subId": ""
            }
            
            endpoints = [
                f"/xui/inbound/addClient",
                f"/api/inbound/addClient",
                f"/inbound/addClient"
            ]
            
            for endpoint in endpoints:
                payload = {
                    "id": inbound_id,
                    "settings": json.dumps({"clients": [client_data]})
                }
                
                resp = self.session.post(
                    self.host + endpoint,
                    json=payload,
                    timeout=15,
                    verify=False
                )
                
                if resp.status_code == 200:
                    result = resp.json()
                    if result.get('success') or result.get('code') == 0:
                        config_link = f"{self.host}/sub/{client_uuid}"
                        return config_link, None
            
            return None, "Прямое создание не сработало"
            
        except Exception as e:
            return None, f"Ошибка прямого метода: {str(e)}"
    
    def _create_client_ajax(self, email, client_uuid, expiry_timestamp, inbound_id):
        """Создание через AJAX"""
        try:
            endpoints = [
                "/xui/API/inbound/add",
                "/api/v1/client/add"
            ]
            
            for endpoint in endpoints:
                client_data = {
                    "inboundId": inbound_id,
                    "email": email,
                    "uuid": client_uuid,
                    "expiryTime": expiry_timestamp,
                    "enable": True
                }
                
                resp = self.session.post(
                    self.host + endpoint,
                    data=client_data,
                    timeout=15,
                    verify=False
                )
                
                if resp.status_code == 200:
                    try:
                        result = resp.json()
                        if result.get('success') or result.get('code') == 0:
                            config_link = f"{self.host}/sub/{client_uuid}"
                            return config_link, None
                    except:
                        if 'success' in resp.text.lower():
                            config_link = f"{self.host}/sub/{client_uuid}"
                            return config_link, None
            
            return None, "AJAX метод не сработал"
            
        except Exception as e:
            return None, f"Ошибка AJAX метода: {str(e)}"

# Глобальный экземпляр панели
xui_panel = UniversalXUIPanel(XUI_PANEL_HOST, XUI_USERNAME, XUI_PASSWORD)

# --- Логика 3x-ui API (использует универсальный класс) ---

def create_3xui_user(user_email: str, expiry_days: int, inbound_id: int):
    """
    Создаёт клиента в 3x-ui используя универсальный класс
    """
    try:
        logger.info(f"Создаем пользователя {user_email} на {expiry_days} дней")
        
        config_link, error_msg = xui_panel.create_client(user_email, expiry_days, inbound_id)
        
        if error_msg:
            logger.error(f"Ошибка создания пользователя: {error_msg}")
            return None, error_msg
        
        logger.info(f"Успешно создан пользователь {user_email}, ссылка: {config_link}")
        return config_link, None
        
    except Exception as e:
        error_msg = f"Неожиданная ошибка: {str(e)}"
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

@dp.message(Command("test_panel"))
async def cmd_test_panel(message: types.Message):
    """Команда для тестирования подключения к панели"""
    await message.answer("🔧 Тестирую подключение к панели...")
    
    try:
        # Тестируем подключение
        loop = asyncio.get_event_loop()
        success = await loop.run_in_executor(None, xui_panel.login)
        
        if success:
            await message.answer("✅ Подключение к панели успешно!")
        else:
            await message.answer("❌ Не удалось подключиться к панели. Проверьте настройки.")
    except Exception as e:
        await message.answer(f"💥 Ошибка тестирования: {e}")

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

        # Тестируем подключение к панели
        logger.info("Тестируем подключение к 3x-ui панели...")
        panel_success = await asyncio.get_event_loop().run_in_executor(None, xui_panel.login)
        
        if panel_success:
            logger.info("✅ Подключение к 3x-ui панели успешно")
        else:
            logger.warning("❌ Не удалось подключиться к 3x-ui панели. Проверьте настройки.")

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