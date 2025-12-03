# -*- coding: utf-8 -*-

"""
Telegram‑бот для продажи VPN с тарифами, оплатой ЮKassa и простой админ‑панелью.

Функции:
- Выбор тарифа через кнопки
- Создание платежей через Yookassa
- Простейшая админ‑панель (просмотр платежей и пользователей)
- Webhook‑подключение

Требует: aiogram 3.x, aiohttp, yookassa
"""

import os
import uuid
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart, Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web
from yookassa import Configuration, Payment

# =============== CONFIG ===============
BOT_TOKEN = os.getenv("8398090520:AAFkaOvgYP7_01u88XOHGclvC6gKPOxQkXQ")
YOOKASSA_SHOP_ID = os.getenv("1189951")
YOOKASSA_API_KEY = os.getenv("live_qGlOT48V-6XAdzTA35GP2wEfC5fZ6sLgiCsxIDIv6MY")
WEBHOOK_URL = os.getenv("https://webhook.vpnurr.com/yookassa_webhook")
ADMIN_ID = int(os.getenv("ADMIN_ID", "123456789"))

TARIFFS = {
    "vpn_week": {"name": "Неделя", "price": 100},
    "vpn_month": {"name": "Месяц", "price": 300}, 
    "vpn_year": {"name": "Год", "price": 2500},
}

Configuration.account_id = YOOKASSA_SHOP_ID
Configuration.secret_key = YOOKASSA_API_KEY

bot = Bot(BOT_TOKEN)
dp = Dispatcher()

# Хранилище покупок (демо, заменить на БД)
USERS = {}
PAYMENTS = {}

# =============== HANDLERS ===============
@dp.message(CommandStart())
async def start(message: types.Message):
    kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Купить VPN")]], resize_keyboard=True)
    await message.answer("Привет! Выберите действие:", reply_markup=kb)


@dp.message(lambda m: m.text == "Купить VPN")
async def choose_tariff(message: types.Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{t['name']} — {t['price']}₽", callback_data=f"buy_{key}")]
        for key, t in TARIFFS.items()
    ])
    await message.answer("Выберите тариф:", reply_markup=kb)


@dp.callback_query(lambda c: c.data.startswith("buy_"))
async def create_payment(callback: types.CallbackQuery):
    tariff_key = callback.data.replace("buy_", "")
    tariff = TARIFFS.get(tariff_key)

    if not tariff:
        await callback.answer("Ошибка тарифа", show_alert=True)
        return

    order_id = str(uuid.uuid4())
    price = tariff["price"]

    payment = Payment.create({
        "amount": {"value": str(price), "currency": "RUB"},
        "confirmation": {"type": "redirect", "return_url": "https://example.com/return"},
        "capture": True,
        "description": f"VPN {tariff['name']} — {order_id}"
    })

    pay_url = payment.confirmation["confirmation_url"]

    PAYMENTS[order_id] = {
        "user_id": callback.from_user.id,
        "tariff": tariff_key,
        "amount": price,
        "payment_id": payment.id,
        "status": "pending",
    }

    await callback.message.answer(f"Оплатите по ссылке:\n{pay_url}")
    await callback.answer()


# =============== ADMIN PANEL ===============
@dp.message(Command("admin"))
async def admin_panel(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return

    kb = ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="Админ: Платежи")],
        [KeyboardButton(text="Админ: Пользователи")]
    ], resize_keyboard=True)

    await message.answer("Админ панель:", reply_markup=kb)


@dp.message(lambda m: m.text == "Админ: Платежи" and m.from_user.id == ADMIN_ID)
async def admin_payments(message: types.Message):
    if not PAYMENTS:
        await message.answer("Платежей нет")
        return

    text = "Список платежей:\n\n" + "\n".join([
        f"ID: {oid}\nUser: {p['user_id']}\nTariff: {p['tariff']}\nAmount: {p['amount']}₽\nStatus: {p['status']}\nPaymentID: {p['payment_id']}" 
        for oid, p in PAYMENTS.items()
    ])
    await message.answer(text)


@dp.message(lambda m: m.text == "Админ: Пользователи" and m.from_user.id == ADMIN_ID)
async def admin_users(message: types.Message):
    if not USERS:
        await message.answer("Пользователей нет")
        return

    text = "Пользователи:\n\n" + "\n".join([
        f"UserID: {uid}, тариф: {tariff}"
        for uid, tariff in USERS.items()
    ])
    await message.answer(text)


# =============== WEBHOOK CONFIG ===============
async def on_startup(app: web.Application):
    await bot.set_webhook(WEBHOOK_URL)

async def on_shutdown(app: web.Application):
    await bot.delete_webhook()


def main():
    app = web.Application()
    SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path="/")
    setup_application(app, dp, bot=bot)

    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)

    web.run_app(app, host="0.0.0.0", port=8080)


if __name__ == "__main__":
    main()
