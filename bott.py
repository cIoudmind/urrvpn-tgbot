"""
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


text = "Список платежей:


" + "
".join([
f"ID: {oid}
User: {p['user_id']}
Tariff: {p['tariff']}
Amount: {p['amount']}₽
Status: {p['status']}
PaymentID: {p['payment_id']}
"
for oid, p in PAYMENTS.items()
])
await message.answer(text)




@dp.message(lambda m: m.text == "Админ: Пользователи" and m.from_user.id == ADMIN_ID)
async def admin_users(message: types.Message):
if not USERS:
await message.answer("Пользователей нет")
return


text = "Пользователи:


" + "
".join([
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
