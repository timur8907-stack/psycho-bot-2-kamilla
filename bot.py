import asyncio
import csv
from datetime import datetime
import html
import io
import logging
import os
import re
import aiohttp
import aiosqlite
from aiogram import Bot, Dispatcher, F, types
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import InlineKeyboardBuilder

# Токен нового бота, ваш постоянный ADMIN_ID и новые платежные данные
BOT_TOKEN = os.getenv("BOT_TOKEN", "8401540210:AAHVVVmQbSbcI9Fod-eirg7pWzqs8ioOHpM")
ADMIN_ID = int(os.getenv("ADMIN_ID", "688074424"))

PAYMENT_DETAILS = (
    "💳 <b>Реквизиты для оплаты:</b>\n\n"
    "• <b>Юmoney карта:</b>\n<code>4048 4150 4423 7697</code>\n\n"
    "• <b>Юmoney кошелек:</b>\n<code>410014059308061</code>\n\n"
    "• <b>ВТБ:</b>\n<code>2200240251506917</code>\n\n"
    "<i>(нажмите на номер карты или кошелька, чтобы скопировать)</i>"
)

DB_PATH = "courses.db"

# Ссылка на вашу вторую таблицу
GOOGLE_SHEET_URL = "https://docs.google.com/spreadsheets/d/115ZCC2QywKXR2ZQlfbvdqeVMpEIpZB9DO07RgR4U6V0/edit?usp=sharing"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())


class OrderFSM(StatesGroup):
    waiting_for_receipt = State()


def get_export_url(share_url: str) -> str:
    match = re.search(r"/d/([a-zA-Z0-9-_]+)", share_url)
    if not match:
        return share_url
    sheet_id = match.group(1)
    return f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv"


async def sync_courses_from_sheets():
    url = get_export_url(GOOGLE_SHEET_URL)
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            if resp.status != 200:
                return 0
            content = await resp.text()

    reader = csv.DictReader(io.StringIO(content))
    data = []
    for row in reader:
        clean_row = {k.strip().lower() if k else "": v for k, v in row.items()}
        c_id = clean_row.get("id")
        title = clean_row.get("title")
        price = clean_row.get("price")
        link = clean_row.get("link", "")

        if c_id and title and price:
            clean_price = re.sub(r"\D", "", str(price))
            clean_id = re.sub(r"\D", "", str(c_id))
            if clean_price and clean_id:
                data.append((
                    int(clean_id),
                    str(title).strip(),
                    int(clean_price),
                    str(link).strip() if link else ""
                ))

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM courses")
        await db.executemany(
            "INSERT INTO courses (id, title, price, link) VALUES (?, ?, ?, ?)",
            data
        )
        await db.commit()
    return len(data)


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS courses (
                id INTEGER PRIMARY KEY,
                title TEXT,
                price INTEGER,
                link TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                course_ids TEXT,
                total_price INTEGER,
                status TEXT DEFAULT 'pending'
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                val_text TEXT
            )
        """)
        await db.execute("INSERT OR IGNORE INTO settings (key, val_text) VALUES ('promo_active', '0')")
        await db.execute("INSERT OR IGNORE INTO settings (key, val_text) VALUES ('promo_percent', '20')")
        await db.execute("INSERT OR IGNORE INTO settings (key, val_text) VALUES ('promo_min_sum', '1000')")
        await db.execute("INSERT OR IGNORE INTO settings (key, val_text) VALUES ('promo_until', '')")
        await db.commit()
    await sync_courses_from_sheets()


async def get_promo_config():
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT key, val_text FROM settings WHERE key LIKE 'promo_%'") as cur:
            cfg = dict(await cur.fetchall())

    is_active = cfg.get("promo_active") == "1"
    until_str = cfg.get("promo_until", "").strip()

    if is_active and until_str:
        try:
            until_date = datetime.strptime(until_str, "%d.%m.%Y")
            if datetime.now() > until_date.replace(hour=23, minute=59, second=59, microsecond=999999):
                is_active = False
                async with aiosqlite.connect(DB_PATH) as db:
                    await db.execute("UPDATE settings SET val_text = '0' WHERE key = 'promo_active'")
                    await db.commit()
        except ValueError:
            pass

    return {
        "active": is_active,
        "percent": int(cfg.get("promo_percent", 20)),
        "min_sum": int(cfg.get("promo_min_sum", 1000)),
        "until": until_str
    }


# Управление скидками (только для вас)
@dp.message(Command("promo"))
async def promo_control(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return

    parts = message.text.split()
    async with aiosqlite.connect(DB_PATH) as db:
        if len(parts) == 1:
            cfg = await get_promo_config()
            status = "🟢 ВКЛЮЧЕНА" if cfg["active"] else "🔴 ВЫКЛЮЧЕНА"
            date_info = f"\nДействует до: {cfg['until']}" if cfg["until"] else ""
            await message.answer(
                f"📊 <b>Статус скидки:</b> {status}\n"
                f"Размер скидки: {cfg['percent']}%\n"
                f"Порог суммы: от {cfg['min_sum']} руб.{date_info}\n\n"
                f"<b>Команды:</b>\n"
                f"<code>/promo on 20 1000</code> — включить 20% от 1000 руб.\n"
                f"<code>/promo on 30 500 31.12.2026</code> — акция со сроком\n"
                f"<code>/promo off</code> — выключить скидку",
                parse_mode=ParseMode.HTML
            )
            return

        action = parts[1].lower()
        if action == "off":
            await db.execute("UPDATE settings SET val_text = '0' WHERE key = 'promo_active'")
            await db.commit()
            await message.answer("🔴 Праздничная скидка отключена.")
        elif action == "on":
            percent = int(parts[2]) if len(parts) > 2 else 20
            min_sum = int(parts[3]) if len(parts) > 3 else 1000
            until_date = parts[4] if len(parts) > 4 else ""

            if until_date:
                try:
                    datetime.strptime(until_date, "%d.%m.%Y")
                except ValueError:
                    await message.answer("⚠️ Неверный формат даты! Указывайте как <code>01.12.2026</code>", parse_mode=ParseMode.HTML)
                    return

            await db.execute("UPDATE settings SET val_text = '1' WHERE key = 'promo_active'")
            await db.execute("UPDATE settings SET val_text = ? WHERE key = 'promo_percent'", (str(percent),))
            await db.execute("UPDATE settings SET val_text = ? WHERE key = 'promo_min_sum'", (str(min_sum),))
            await db.execute("UPDATE settings SET val_text = ? WHERE key = 'promo_until'", (until_date,))
            await db.commit()

            until_msg = f" до {until_date}" if until_date else ""
            await message.answer(f"🟢 Акция запущена: скидка {percent}% на заказы от {min_sum} руб.{until_msg}!")


# Принудительная синхронизация с таблицей
@dp.message(Command("sync"))
async def sync_cmd(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    count = await sync_courses_from_sheets()
    await message.answer(f"✅ База обновлена из Google Таблицы: {count} курсов.")


# Вывод каталога покупателю
@dp.message(Command("catalog", "courses"))
async def catalog_cmd(message: types.Message):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT id, title, price FROM courses ORDER BY id ASC") as cur:
            courses = await cur.fetchall()

    if not courses:
        await message.answer("❌ Каталог курсов временно пуст или обновляется.")
        return

    # До 25 позиций — сообщением в чат
    if len(courses) <= 25:
        items = "\n".join([f"<code>{c[0]}</code> — {html.escape(str(c[1]))} (<b>{c[2]} руб.</b>)" for c in courses])
        await message.answer(
            f"📚 <b>Список доступных курсов:</b>\n\n"
            f"{items}\n\n"
            f"💡 <i>Чтобы оформить заказ, отправьте боту номера курсов через запятую.</i>",
            parse_mode=ParseMode.HTML
        )
    else:
        # Более 25 позиций — аккуратным файлом без спама
        content = "КАТАЛОГ КУРСОВ\n" + "=" * 40 + "\n\n"
        content += "\n".join([f"№{c[0]} — {c[1]} — {c[2]} руб." for c in courses])
        content += "\n\n" + "=" * 40 + "\nДля заказа скопируйте нужные номера и отправьте их боту через запятую."

        doc = types.BufferedInputFile(content.encode("utf-8"), filename="catalog_kursov.txt")
        await message.answer_document(
            document=doc,
            caption=(
                f"📚 <b>Полный перечень курсов ({len(courses)} шт.)</b>\n\n"
                f"Файл прикреплен выше. Откройте его, выберите нужные номера и отправьте их в чат боту!"
            ),
            parse_mode=ParseMode.HTML
        )


@dp.message(CommandStart())
async def start_cmd(message: types.Message, state: FSMContext):
    await state.clear()
    promo = await get_promo_config()

    promo_text = ""
    if promo["active"]:
        date_text = f" до {promo['until']}" if promo["until"] else ""
        promo_text = f"\n\n🎁 <b>Праздничная акция:</b> действует скидка {promo['percent']}% на заказы от {promo['min_sum']} руб.{date_text}!"

    await message.answer(
        "👋 Здравствуйте!\n\n"
        "Для заказа отправьте <b>номера (артикулы) курсов</b> через запятую или пробел.\n\n"
        "Пример: <code>1, 4, 12</code>\n\n"
        "📖 Посмотреть весь перечень курсов: /catalog"
        f"{promo_text}",
        parse_mode=ParseMode.HTML
    )


@dp.message(F.text, ~F.text.startswith("/"))
async def process_articles(message: types.Message, state: FSMContext):
    raw_ids = re.findall(r"\b\d+\b", message.text)
    if not raw_ids:
        await message.answer("Пожалуйста, отправьте номера курсов цифрами (например: <code>1, 2, 5</code>).", parse_mode=ParseMode.HTML)
        return

    unique_ids = list(dict.fromkeys([int(i) for i in raw_ids]))
    placeholders = ",".join("?" for _ in unique_ids)

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(f"SELECT id, title, price FROM courses WHERE id IN ({placeholders})", unique_ids) as cur:
            found_courses = await cur.fetchall()

    if not found_courses:
        await message.answer("❌ Ни один курс по указанным номерам не найден в базе.")
        return

    promo = await get_promo_config()
    raw_total = sum(c[2] for c in found_courses)
    final_total = raw_total
    discount_info = f"💰 <b>Итого к оплате:</b> {final_total} руб."

    if promo["active"] and raw_total >= promo["min_sum"]:
        discount = int(raw_total * (promo["percent"] / 100))
        final_total = raw_total - discount
        discount_info = (
            f"🏷 Сумма: {raw_total} руб.\n"
            f"🔥 Праздничная скидка {promo['percent']}%: -{discount} руб.\n"
            f"💰 <b>Итого к оплате:</b> {final_total} руб."
        )

    saved_ids = ",".join(str(c[0]) for c in found_courses)
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO orders (user_id, course_ids, total_price) VALUES (?, ?, ?)",
            (message.from_user.id, saved_ids, final_total)
        )
        order_id = cursor.lastrowid
        await db.commit()

    await state.update_data(order_id=order_id)
    await state.set_state(OrderFSM.waiting_for_receipt)

    summary = "\n".join([f"• №{c[0]} {html.escape(str(c[1]))} — {c[2]} руб." for c in found_courses[:10]])
    if len(found_courses) > 10:
        summary += f"\n...и еще {len(found_courses) - 10} позиций"

    await message.answer(
        f"🧾 <b>Заказ #{order_id} сформирован</b>\n\n"
        f"{summary}\n\n"
        f"Выбрано: <b>{len(found_courses)} шт.</b>\n"
        f"{discount_info}\n\n"
        f"{PAYMENT_DETAILS}\n\n"
        f"📸 <b>Пришлите скриншот, фото чека или PDF-выписку в этот чат.</b>",
        parse_mode=ParseMode.HTML
    )


# Прием чеков (фото или PDF) с защитой от перезагрузок сервера
@dp.message(F.photo | F.document)
async def process_receipt(message: types.Message, state: FSMContext):
    data = await state.get_data()
    order_id = data.get("order_id")

    async with aiosqlite.connect(DB_PATH) as db:
        if not order_id:
            async with db.execute(
                "SELECT id FROM orders WHERE user_id = ? AND status = 'pending' ORDER BY id DESC LIMIT 1",
                (message.from_user.id,)
            ) as cur:
                last_order = await cur.fetchone()
                if last_order:
                    order_id = last_order[0]

        if not order_id:
            await message.answer("⚠️ Не найден активный заказ. Пожалуйста, отправьте номера курсов заново.")
            return

        async with db.execute("SELECT course_ids, total_price FROM orders WHERE id = ?", (order_id,)) as cur:
            ord_data = await cur.fetchone()
            if not ord_data:
                await message.answer("Ошибка: заказ не найден.")
                await state.clear()
                return
            c_ids = [int(x) for x in ord_data[0].split(",")]
            order_price = ord_data[1]

        placeholders = ",".join("?" for _ in c_ids)
        async with db.execute(f"SELECT id, title FROM courses WHERE id IN ({placeholders})", c_ids) as cur:
            c_info = await cur.fetchall()

    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Подтвердить", callback_data=f"adm_approve_{order_id}")
    kb.button(text="❌ Отклонить", callback_data=f"adm_reject_{order_id}")
    kb.adjust(2)

    user = f"@{message.from_user.username}" if message.from_user.username else f"ID: {message.from_user.id}"
    courses_brief = "\n".join([f"• №{c[0]} {html.escape(str(c[1]))}" for c in c_info[:7]])
    if len(c_info) > 7:
        courses_brief += f"\n...и еще {len(c_info) - 7} шт."

    caption_text = (
        f"🧾 <b>Оплата заказа #{order_id}</b>\n"
        f"👤 Клиент: {html.escape(user)}\n"
        f"💰 Сумма: <b>{order_price} руб.</b>\n\n"
        f"📚 <b>Курсы ({len(c_info)} шт.):</b>\n"
        f"{courses_brief}"
    )

    try:
        if message.photo:
            await bot.send_photo(
                chat_id=ADMIN_ID,
                photo=message.photo[-1].file_id,
                caption=caption_text,
                reply_markup=kb.as_markup(),
                parse_mode=ParseMode.HTML
            )
        elif message.document:
            await bot.send_document(
                chat_id=ADMIN_ID,
                document=message.document.file_id,
                caption=caption_text,
                reply_markup=kb.as_markup(),
                parse_mode=ParseMode.HTML
            )

        await message.answer("✅ Чек отправлен на проверку. Ссылки придут сюда сразу после подтверждения.")
        await state.clear()
    except Exception as e:
        logging.error(f"Ошибка отправки чека админу: {e}")
        await message.answer("⚠️ Не удалось переслать чек. Пожалуйста, напишите администратору напрямую.")


@dp.callback_query(F.data.startswith("adm_approve_"))
async def admin_approve(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    order_id = int(callback.data.split("_")[2])

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT user_id, course_ids, status FROM orders WHERE id = ?", (order_id,)) as cur:
            order = await cur.fetchone()

        if not order or order[2] == "paid":
            await callback.answer("Заказ уже обработан.")
            return

        user_id, ids = order[0], [int(x) for x in order[1].split(",")]
        placeholders = ",".join("?" for _ in ids)
        async with db.execute(f"SELECT title, link FROM courses WHERE id IN ({placeholders})", ids) as cur:
            courses = await cur.fetchall()

        await db.execute("UPDATE orders SET status = 'paid' WHERE id = ?", (order_id,))
        await db.commit()

    try:
        if len(courses) > 10:
            content = f"ВАШИ КУРСЫ (ЗАКАЗ #{order_id})\n" + "=" * 35 + "\n\n"
            content += "\n\n".join([f"{c[0]}:\n{c[1]}" for c in courses])
            doc = types.BufferedInputFile(content.encode("utf-8"), filename=f"Order_{order_id}.txt")
            await bot.send_document(
                chat_id=user_id,
                document=doc,
                caption="🎉 Оплата подтверждена! Ваши курсы собраны в файле выше."
            )
        else:
            lines = [f"🎉 <b>Оплата подтверждена! Заказ #{order_id}:</b>\n"]
            lines.extend([f"• <b>{html.escape(str(c[0]))}</b>\n👉 {str(c[1]).strip()}" for c in courses])
            await bot.send_message(chat_id=user_id, text="\n\n".join(lines), parse_mode=ParseMode.HTML)
    except Exception as e:
        logging.error(f"Ошибка выдачи ссылок клиенту {user_id}: {e}")

    base_caption = callback.message.caption or ""
    try:
        await callback.message.edit_caption(
            caption=base_caption + "\n\n🟢 <b>ОДОБРЕНО</b>",
            reply_markup=None,
            parse_mode=ParseMode.HTML
        )
    except Exception:
        pass
    await callback.answer("Доступ отправлен")


@dp.callback_query(F.data.startswith("adm_reject_"))
async def admin_reject(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    order_id = int(callback.data.split("_")[2])
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT user_id FROM orders WHERE id = ?", (order_id,)) as cur:
            order = await cur.fetchone()
    if order:
        try:
            await bot.send_message(chat_id=order[0], text=f"❌ Оплата по заказу #{order_id} отклонена.")
        except Exception:
            pass
    base_caption = callback.message.caption or ""
    try:
        await callback.message.edit_caption(
            caption=base_caption + "\n\n🔴 <b>ОТКЛОНЕНО</b>",
            reply_markup=None,
            parse_mode=ParseMode.HTML
        )
    except Exception:
        pass
    await callback.answer("Отклонено")


async def main():
    await init_db()
    logging.basicConfig(level=logging.INFO)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
