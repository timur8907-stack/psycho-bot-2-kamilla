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
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter

ADMIN_ID = int(os.getenv("ADMIN_ID", "688074424"))

RAW_SUPABASE_URL = os.getenv("SUPABASE_URL", "https://pecxqwyzijlgealpprcj.supabase.co").strip()
SUPABASE_URL = re.sub(r"/rest/v1/?$", "", RAW_SUPABASE_URL.rstrip("/"))
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "").strip()

BOT_CONFIGS = [
    {
        "name": "Основной канал",
        "token": "8784163183:AAFXRAsNp9t1dz3Of3vgkadog_xgel59Y34",
        "db_path": "courses_bot1.db",
        "sheet_url": "https://docs.google.com/spreadsheets/d/14Yav2_wV-jUWWji6iOBZVBykJh1anvDWEoUZwTUWxD4/edit?usp=drivesdk",
        "default_payments": [
            ("ВТБ", "2200 2402 5150 6917"),
            ("Яндекс Пэй", "2204 3107 2587 7388"),
            ("Сбербанк", "2202 2068 1402 4274"),
        ]
    },
    {
        "name": "Второй канал",
        "token": "8401540210:AAHVVVmQbSbcI9Fod-eirg7pWzqs8ioOHpM",
        "db_path": "courses_bot2.db",
        "sheet_url": "https://docs.google.com/spreadsheets/d/115ZCC2QywKXR2ZQlfbvdqeVMpEIpZB9DO07RgR4U6V0/edit?usp=sharing",
        "default_payments": [
            ("Юmoney карта", "4048 4150 4423 7697"),
            ("Юmoney кошелек", "410014059308061"),
            ("ВТБ", "2200240251506917"),
        ]
    }
]

MENU_BUTTONS = {
    "📚 Каталог курсов", "📂 Категории", "🔍 Поиск курса",
    "💬 Задать вопрос", "🎁 Акции и скидки", "ℹ️ Как сделать заказ",
    "📢 Сделать рассылку", "👥 Список клиентов", "🚫 Управление базой",
    "🔄 Обновить курсы", "🏷 Скидки и акции", "💳 Реквизиты",
    "📊 Статистика базы", "❌ Отмена"
}


class OrderFSM(StatesGroup):
    waiting_for_receipt = State()


class BroadcastFSM(StatesGroup):
    waiting_for_message = State()


class SupportFSM(StatesGroup):
    waiting_for_question = State()


class SearchFSM(StatesGroup):
    waiting_for_query = State()


class PromoFSM(StatesGroup):
    waiting_for_percent = State()
    waiting_for_min_sum = State()
    waiting_for_until = State()


class UserManageFSM(StatesGroup):
    waiting_for_user_id = State()


class PaymentFSM(StatesGroup):
    waiting_for_bank = State()
    waiting_for_number = State()


def get_export_url(share_url: str) -> str:
    match = re.search(r"/d/([a-zA-Z0-9-_]+)", share_url)
    if not match:
        return share_url
    return f"https://docs.google.com/spreadsheets/d/{match.group(1)}/export?format=csv"


def sb_headers(prefer: str = None) -> dict:
    headers = {
        "apikey": SUPABASE_KEY,
        "Content-Type": "application/json",
    }
    if SUPABASE_KEY.startswith("eyJ"):
        headers["Authorization"] = f"Bearer {SUPABASE_KEY}"
    if prefer:
        headers["Prefer"] = prefer
    return headers


def get_client_kb():
    builder = ReplyKeyboardBuilder()
    builder.button(text="📂 Категории")
    builder.button(text="🔍 Поиск курса")
    builder.button(text="📚 Каталог курсов")
    builder.button(text="💬 Задать вопрос")
    builder.button(text="🎁 Акции и скидки")
    builder.button(text="ℹ️ Как сделать заказ")
    builder.adjust(2, 2, 2)
    return builder.as_markup(resize_keyboard=True)


def get_admin_kb():
    builder = ReplyKeyboardBuilder()
    builder.button(text="📂 Категории")
    builder.button(text="🔍 Поиск курса")
    builder.button(text="📚 Каталог курсов")
    builder.button(text="📢 Сделать рассылку")
    builder.button(text="👥 Список клиентов")
    builder.button(text="🚫 Управление базой")
    builder.button(text="🔄 Обновить курсы")
    builder.button(text="🏷 Скидки и акции")
    builder.button(text="💳 Реквизиты")
    builder.button(text="📊 Статистика базы")
    builder.adjust(2, 2, 2, 2, 2)
    return builder.as_markup(resize_keyboard=True)


def create_bot_app(cfg: dict):
    token = cfg["token"]
    db_path = cfg["db_path"]
    sheet_url = cfg["sheet_url"]
    default_payments = cfg.get("default_payments", [])
    bot_name = cfg["name"]

    bot = Bot(token=token)
    dp = Dispatcher(storage=MemoryStorage())

    # --- РАБОТА С SUPABASE ---
    async def sb_request(method: str, path: str, json_data=None, prefer: str = None):
        if not SUPABASE_KEY:
            logging.error("SUPABASE_KEY не задан в Environment Variables!")
            return None
        url = f"{SUPABASE_URL}/rest/v1/{path.lstrip('/')}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.request(method, url, headers=sb_headers(prefer), json=json_data) as resp:
                    text = await resp.text()
                    if resp.status >= 400:
                        logging.error(f"[Supabase {resp.status}] {method} {path}: {text}")
                        return None
                    if not text:
                        return []
                    return await resp.json(content_type=None)
        except Exception as e:
            logging.error(f"[Supabase Error] {method} {path}: {e}")
            return None

    async def record_user(u: types.User):
        username = f"@{u.username}" if u.username else ""
        full_name = u.full_name or ""
        await sb_request(
            "POST",
            "users?on_conflict=user_id",
            json_data={"user_id": u.id, "username": username, "full_name": full_name},
            prefer="resolution=merge-duplicates"
        )

    # --- РАБОТА С РЕКВИЗИТАМИ ОПЛАТЫ ---
    async def get_payment_methods():
        async with aiosqlite.connect(db_path) as db:
            async with db.execute("SELECT id, bank_name, account_num FROM payment_methods ORDER BY id ASC") as cur:
                return await cur.fetchall()

    async def format_payment_details() -> str:
        methods = await get_payment_methods()
        if not methods:
            return (
                "💳 <b>Реквизиты для оплаты:</b>\n\n"
                "<i>Реквизиты временно не заданы. Уточните у администратора через «💬 Задать вопрос».</i>"
            )
        lines = ["💳 <b>Реквизиты для оплаты:</b>\n"]
        for _, bank, num in methods:
            lines.append(f"• <b>{html.escape(str(bank))}:</b>\n<code>{html.escape(str(num))}</code>\n")
        lines.append("<i>(нажмите на номер карты или кошелька, чтобы скопировать)</i>")
        return "\n".join(lines)

    # --- СИНХРОНИЗАЦИЯ КУРСОВ ИЗ GOOGLE ТАБЛИЦЫ ---
    async def sync_courses_from_sheets():
        url = get_export_url(sheet_url)
        try:
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
                category = clean_row.get("category", "")
                description = clean_row.get("description", "")

                if c_id and title and price:
                    clean_price = re.sub(r"\D", "", str(price))
                    clean_id = re.sub(r"\D", "", str(c_id))
                    if clean_price and clean_id:
                        cat_val = str(category).strip() if category else ""
                        data.append((
                            int(clean_id),
                            str(title).strip(),
                            int(clean_price),
                            str(link).strip() if link else "",
                            cat_val if cat_val else "Без категории",
                            str(description).strip() if description else ""
                        ))

            async with aiosqlite.connect(db_path) as db:
                await db.execute("DELETE FROM courses")
                await db.executemany(
                    "INSERT INTO courses (id, title, price, link, category, description) VALUES (?, ?, ?, ?, ?, ?)",
                    data
                )
                await db.commit()
            return len(data)
        except Exception as e:
            logging.error(f"[{bot_name}] Ошибка синхронизации: {e}")
            return 0

    async def init_db():
        async with aiosqlite.connect(db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS courses (
                    id INTEGER PRIMARY KEY,
                    title TEXT,
                    price INTEGER,
                    link TEXT,
                    category TEXT DEFAULT 'Без категории',
                    description TEXT DEFAULT ''
                )
            """)
            for col_sql in [
                "ALTER TABLE courses ADD COLUMN category TEXT DEFAULT 'Без категории'",
                "ALTER TABLE courses ADD COLUMN description TEXT DEFAULT ''"
            ]:
                try:
                    await db.execute(col_sql)
                except Exception:
                    pass

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

            await db.execute("""
                CREATE TABLE IF NOT EXISTS payment_methods (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    bank_name TEXT,
                    account_num TEXT
                )
            """)
            async with db.execute("SELECT COUNT(*) FROM payment_methods") as cur:
                pm_count = (await cur.fetchone())[0]
            if pm_count == 0 and default_payments:
                await db.executemany(
                    "INSERT INTO payment_methods (bank_name, account_num) VALUES (?, ?)",
                    default_payments
                )

            await db.commit()

        try:
            await bot.set_my_commands([
                BotCommand(command="start", description="Главное меню"),
                BotCommand(command="catalog", description="Каталог курсов"),
                BotCommand(command="help", description="Как сделать заказ"),
            ])
        except Exception:
            pass

        await sync_courses_from_sheets()

    async def get_promo_config():
        async with aiosqlite.connect(db_path) as db:
            async with db.execute("SELECT key, val_text FROM settings WHERE key LIKE 'promo_%'") as cur:
                p_cfg = dict(await cur.fetchall())

        is_active = p_cfg.get("promo_active") == "1"
        until_str = p_cfg.get("promo_until", "").strip()

        if is_active and until_str:
            try:
                until_date = datetime.strptime(until_str, "%d.%m.%Y")
                if datetime.now() > until_date.replace(hour=23, minute=59, second=59, microsecond=999999):
                    is_active = False
                    async with aiosqlite.connect(db_path) as db:
                        await db.execute("UPDATE settings SET val_text = '0' WHERE key = 'promo_active'")
                        await db.commit()
            except ValueError:
                pass

        return {
            "active": is_active,
            "percent": int(p_cfg.get("promo_percent", 20)),
            "min_sum": int(p_cfg.get("promo_min_sum", 1000)),
            "until": until_str
        }

    # --- ОБЩАЯ ФУНКЦИЯ СОЗДАНИЯ ЗАКАЗА ---
    async def create_order_for_user(message_or_chat_id: int, user_id: int, course_ids: list[int], state: FSMContext, send_fn):
        placeholders = ",".join("?" for _ in course_ids)
        async with aiosqlite.connect(db_path) as db:
            async with db.execute(f"SELECT id, title, price FROM courses WHERE id IN ({placeholders})", course_ids) as cur:
                found_courses = await cur.fetchall()

        if not found_courses:
            await send_fn("❌ Ни один курс по указанным номерам не найден.")
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
                f"🔥 Скидка {promo['percent']}%: -{discount} руб.\n"
                f"💰 <b>Итого к оплате:</b> {final_total} руб."
            )

        saved_ids = ",".join(str(c[0]) for c in found_courses)
        res = await sb_request(
            "POST",
            "orders",
            json_data={
                "user_id": user_id,
                "bot_name": bot_name,
                "course_ids": saved_ids,
                "total_price": final_total,
                "status": "pending"
            },
            prefer="return=representation"
        )
        if not res or not isinstance(res, list):
            await send_fn("⚠️ Временная ошибка базы данных. Попробуйте еще раз через минуту.")
            return

        order_id = res[0]["id"]
        await state.update_data(order_id=order_id)
        await state.set_state(OrderFSM.waiting_for_receipt)

        summary = "\n".join([f"• №{c[0]} {html.escape(str(c[1]))} — {c[2]} руб." for c in found_courses[:10]])
        if len(found_courses) > 10:
            summary += f"\n...и еще {len(found_courses) - 10} позиций"

        pay_text = await format_payment_details()

        await send_fn(
            f"🧾 <b>Заказ #{order_id} сформирован</b>\n\n"
            f"{summary}\n\n"
            f"Выбрано: <b>{len(found_courses)} шт.</b>\n"
            f"{discount_info}\n\n"
            f"{pay_text}\n\n"
            f"📸 <b>Пришлите скриншот чека или PDF в этот чат.</b>"
        )

    # --- 1. СТАРТ ---
    @dp.message(CommandStart())
    async def start_cmd(message: types.Message, state: FSMContext):
        await state.clear()
        await record_user(message.from_user)
        promo = await get_promo_config()

        promo_text = ""
        if promo["active"]:
            date_text = f" до {promo['until']}" if promo["until"] else ""
            promo_text = f"\n\n🎁 <b>Акция:</b> скидка {promo['percent']}% на заказы от {promo['min_sum']} руб.{date_text}!"

        is_admin = (message.from_user.id == ADMIN_ID)
        kb = get_admin_kb() if is_admin else get_client_kb()
        admin_note = "\n\n<i>👑 Вы вошли как администратор.</i>" if is_admin else ""

        await message.answer(
            "👋 Здравствуйте!\n\n"
            "Вы можете выбрать курсы через <b>«📂 Категории»</b>, найти по названию в <b>«🔍 Поиск курса»</b> "
            "или сразу отправить <b>номера (артикулы) курсов</b> через запятую.\n\n"
            "Пример: <code>1, 4, 12</code>"
            f"{promo_text}{admin_note}",
            parse_mode=ParseMode.HTML,
            reply_markup=kb
        )

    # --- 2. ОТВЕТ АДМИНА ЧЕРЕЗ REPLY (ДВУСТОРОННЯЯ ПОДДЕРЖКА) ---
    @dp.message(F.from_user.id == ADMIN_ID, F.reply_to_message)
    async def admin_reply_to_support(message: types.Message):
        reply_id = message.reply_to_message.message_id
        rows = await sb_request(
            "GET",
            f"support_messages?admin_msg_id=eq.{reply_id}&bot_name=eq.{bot_name}&limit=1"
        )
        if not rows:
            return

        target_user_id = rows[0]["user_id"]
        try:
            if message.text:
                await bot.send_message(
                    chat_id=target_user_id,
                    text=f"💬 <b>Ответ от поддержки:</b>\n\n{html.escape(message.text)}",
                    parse_mode=ParseMode.HTML
                )
            else:
                await bot.copy_message(
                    chat_id=target_user_id,
                    from_chat_id=message.chat.id,
                    message_id=message.message_id
                )
            await message.reply("✅ Ответ отправлен клиенту.")
        except TelegramForbiddenError:
            await message.reply("⚠️ Не удалось отправить: клиент заблокировал бота.")
        except Exception as e:
            await message.reply(f"⚠️ Ошибка отправки: {e}")

    # --- 3. ЗАДАТЬ ВОПРОС (КЛИЕНТ -> АДМИН) ---
    @dp.message(F.text == "💬 Задать вопрос")
    async def support_start(message: types.Message, state: FSMContext):
        await record_user(message.from_user)
        await state.set_state(SupportFSM.waiting_for_question)
        kb = InlineKeyboardBuilder()
        kb.button(text="❌ Отмена", callback_data="cancel_support")
        await message.answer(
            "💬 <b>Напишите ваш вопрос одним сообщением</b>\n\n"
            "Можно прикрепить текст, скриншот или файл. Мы ответим вам прямо в этот чат.",
            parse_mode=ParseMode.HTML,
            reply_markup=kb.as_markup()
        )

    @dp.callback_query(F.data == "ask_support")
    async def support_start_cb(callback: types.CallbackQuery, state: FSMContext):
        await record_user(callback.from_user)
        await state.set_state(SupportFSM.waiting_for_question)
        kb = InlineKeyboardBuilder()
        kb.button(text="❌ Отмена", callback_data="cancel_support")
        await callback.message.answer(
            "💬 <b>Напишите ваш вопрос одним сообщением</b>\n\n"
            "Можно прикрепить текст, скриншот или файл. Мы ответим вам прямо в этот чат.",
            parse_mode=ParseMode.HTML,
            reply_markup=kb.as_markup()
        )
        await callback.answer()

    @dp.callback_query(F.data == "cancel_support")
    async def support_cancel(callback: types.CallbackQuery, state: FSMContext):
        await state.clear()
        await callback.message.edit_text("❌ Обращение отменено.")
        await callback.answer()

    @dp.message(SupportFSM.waiting_for_question)
    async def support_receive(message: types.Message, state: FSMContext):
        if message.text in MENU_BUTTONS or (message.text and message.text.startswith("/")):
            await state.clear()
            return

        await state.clear()
        u = message.from_user
        u_label = f"{u.full_name or 'Без имени'}"
        if u.username:
            u_label += f" (@{u.username})"

        header = (
            f"📩 <b>[{bot_name}] Вопрос от клиента</b>\n"
            f"👤 {html.escape(u_label)} | <code>{u.id}</code>\n"
        )
        footer = "\n\n<i>↩️ Сделайте Reply (Ответить) на это сообщение, чтобы ответить клиенту.</i>"

        try:
            if message.text:
                sent = await bot.send_message(
                    chat_id=ADMIN_ID,
                    text=f"{header}\n{html.escape(message.text)}{footer}",
                    parse_mode=ParseMode.HTML
                )
            elif message.photo:
                cap = html.escape(message.caption or "")
                sent = await bot.send_photo(
                    chat_id=ADMIN_ID,
                    photo=message.photo[-1].file_id,
                    caption=f"{header}\n{cap}{footer}",
                    parse_mode=ParseMode.HTML
                )
            elif message.document:
                cap = html.escape(message.caption or "")
                sent = await bot.send_document(
                    chat_id=ADMIN_ID,
                    document=message.document.file_id,
                    caption=f"{header}\n{cap}{footer}",
                    parse_mode=ParseMode.HTML
                )
            else:
                copied = await bot.copy_message(
                    chat_id=ADMIN_ID,
                    from_chat_id=message.chat.id,
                    message_id=message.message_id
                )
                sent = await bot.send_message(
                    chat_id=ADMIN_ID,
                    text=f"{header}<i>Медиа-сообщение выше ↑</i>{footer}",
                    reply_to_message_id=copied.message_id,
                    parse_mode=ParseMode.HTML
                )

            await sb_request(
                "POST",
                "support_messages",
                json_data={
                    "admin_msg_id": sent.message_id,
                    "user_id": u.id,
                    "bot_name": bot_name
                }
            )
            await message.answer("✅ Ваше сообщение отправлено! Ответим вам в ближайшее время прямо сюда.")
        except Exception as e:
            logging.error(f"[{bot_name}] Ошибка пересылки вопроса: {e}")
            await message.answer("⚠️ Не удалось отправить сообщение. Попробуйте позже.")

    # --- 4. КАТЕГОРИИ И КАРТОЧКИ КУРСОВ ---
    async def get_sorted_categories() -> list[str]:
        async with aiosqlite.connect(db_path) as db:
            async with db.execute("SELECT DISTINCT category FROM courses") as cur:
                rows = await cur.fetchall()
        cats = sorted({r[0] or "Без категории" for r in rows})
        return cats

    @dp.message(F.text == "📂 Категории")
    async def categories_cmd(message: types.Message):
        await record_user(message.from_user)
        cats = await get_sorted_categories()
        if not cats:
            await message.answer("❌ Каталог пуст.")
            return

        if len(cats) == 1 and cats[0] == "Без категории":
            await send_courses_page(message.answer, cat_idx=0, page=0, is_edit=False)
            return

        kb = InlineKeyboardBuilder()
        for idx, cat_name in enumerate(cats):
            kb.button(text=f"📁 {cat_name}", callback_data=f"cat_{idx}_0")
        kb.adjust(1)
        await message.answer(
            "📂 <b>Выберите категорию курсов:</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=kb.as_markup()
        )

    async def send_courses_page(target_fn, cat_idx: int, page: int, is_edit: bool = True):
        cats = await get_sorted_categories()
        if cat_idx < 0 or cat_idx >= len(cats):
            return
        cat_name = cats[cat_idx]

        async with aiosqlite.connect(db_path) as db:
            async with db.execute(
                "SELECT id, title, price FROM courses WHERE category = ? ORDER BY id ASC",
                (cat_name,)
            ) as cur:
                courses = await cur.fetchall()

        per_page = 8
        total_pages = max(1, (len(courses) + per_page - 1) // per_page)
        page = max(0, min(page, total_pages - 1))
        chunk = courses[page * per_page:(page + 1) * per_page]

        kb = InlineKeyboardBuilder()
        for c_id, title, price in chunk:
            short_t = title[:38] + "…" if len(title) > 38 else title
            kb.button(text=f"№{c_id} | {short_t} ({price}₽)", callback_data=f"course_{c_id}_{cat_idx}_{page}")
        kb.adjust(1)

        nav = []
        if page > 0:
            nav.append(types.InlineKeyboardButton(text="⬅️ Назад", callback_data=f"cat_{cat_idx}_{page - 1}"))
        if page < total_pages - 1:
            nav.append(types.InlineKeyboardButton(text="Вперёд ➡️", callback_data=f"cat_{cat_idx}_{page + 1}"))
        if nav:
            kb.row(*nav)
        if len(cats) > 1 or cats[0] != "Без категории":
            kb.row(types.InlineKeyboardButton(text="🔙 Все категории", callback_data="cats_home"))

        text = (
            f"📁 <b>Категория:</b> {html.escape(cat_name)}\n"
            f"Страница {page + 1} из {total_pages} (всего {len(courses)} курсов):\n\n"
            f"<i>Нажмите на курс, чтобы открыть описание, или отправьте нужные номера через запятую.</i>"
        )
        await target_fn(text, parse_mode=ParseMode.HTML, reply_markup=kb.as_markup())

    @dp.callback_query(F.data == "cats_home")
    async def cats_home_cb(callback: types.CallbackQuery):
        cats = await get_sorted_categories()
        kb = InlineKeyboardBuilder()
        for idx, cat_name in enumerate(cats):
            kb.button(text=f"📁 {cat_name}", callback_data=f"cat_{idx}_0")
        kb.adjust(1)
        await callback.message.edit_text(
            "📂 <b>Выберите категорию курсов:</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=kb.as_markup()
        )
        await callback.answer()

    @dp.callback_query(F.data.startswith("cat_"))
    async def cat_page_cb(callback: types.CallbackQuery):
        _, c_idx, page = callback.data.split("_")
        await send_courses_page(callback.message.edit_text, int(c_idx), int(page), is_edit=True)
        await callback.answer()

    @dp.callback_query(F.data.startswith("course_"))
    async def course_card_cb(callback: types.CallbackQuery):
        parts = callback.data.split("_")
        c_id = int(parts[1])
        cat_idx = int(parts[2])
        page = int(parts[3])

        async with aiosqlite.connect(db_path) as db:
            async with db.execute(
                "SELECT id, title, price, category, description FROM courses WHERE id = ?",
                (c_id,)
            ) as cur:
                row = await cur.fetchone()

        if not row:
            await callback.answer("Курс не найден.", show_alert=True)
            return

        cid, title, price, cat, desc = row
        desc_block = f"\n\n📝 <b>Описание:</b>\n{html.escape(desc)}" if desc else ""
        cat_block = f"\n📁 Категория: {html.escape(cat)}" if cat and cat != "Без категории" else ""

        kb = InlineKeyboardBuilder()
        kb.button(text=f"🛒 Купить курс №{cid} ({price} ₽)", callback_data=f"buy1_{cid}")
        if cat_idx >= 0:
            kb.button(text="🔙 Назад к списку", callback_data=f"cat_{cat_idx}_{page}")
        kb.adjust(1)

        await callback.message.edit_text(
            f"🎓 <b>№{cid} — {html.escape(title)}</b>"
            f"{cat_block}"
            f"{desc_block}\n\n"
            f"💰 <b>Цена:</b> {price} руб.\n\n"
            f"💡 <i>Чтобы купить несколько курсов сразу со скидкой, отправьте их номера в чат через запятую (например: <code>{cid}, 2</code>).</i>",
            parse_mode=ParseMode.HTML,
            reply_markup=kb.as_markup()
        )
        await callback.answer()

    @dp.callback_query(F.data.startswith("buy1_"))
    async def buy_single_course_cb(callback: types.CallbackQuery, state: FSMContext):
        c_id = int(callback.data.split("_")[1])
        await record_user(callback.from_user)

        async def send_fn(txt):
            await callback.message.answer(txt, parse_mode=ParseMode.HTML)

        await create_order_for_user(callback.message.chat.id, callback.from_user.id, [c_id], state, send_fn)
        await callback.answer()

    # --- 5. ПОИСК КУРСА ---
    @dp.message(F.text == "🔍 Поиск курса")
    async def search_start(message: types.Message, state: FSMContext):
        await record_user(message.from_user)
        await state.set_state(SearchFSM.waiting_for_query)
        kb = InlineKeyboardBuilder()
        kb.button(text="❌ Отмена", callback_data="cancel_search")
        await message.answer(
            "🔍 <b>Поиск по каталогу</b>\n\n"
            "Введите ключевое слово из названия, автора или номер курса:",
            parse_mode=ParseMode.HTML,
            reply_markup=kb.as_markup()
        )

    @dp.callback_query(F.data == "cancel_search")
    async def search_cancel(callback: types.CallbackQuery, state: FSMContext):
        await state.clear()
        await callback.message.edit_text("❌ Поиск отменён.")
        await callback.answer()

    @dp.message(SearchFSM.waiting_for_query)
    async def search_execute(message: types.Message, state: FSMContext):
        if not message.text or message.text in MENU_BUTTONS or message.text.startswith("/"):
            await state.clear()
            return

        query = message.text.strip().lower()
        await state.clear()

        async with aiosqlite.connect(db_path) as db:
            async with db.execute("SELECT id, title, price, description FROM courses ORDER BY id ASC") as cur:
                all_courses = await cur.fetchall()

        matches = []
        for cid, title, price, desc in all_courses:
            if query == str(cid) or query in (title or "").lower() or query in (desc or "").lower():
                matches.append((cid, title, price))

        if not matches:
            kb = InlineKeyboardBuilder()
            kb.button(text="💬 Задать вопрос", callback_data="ask_support")
            await message.answer(
                "😔 По вашему запросу ничего не найдено. Попробуйте другое слово, откройте «📚 Каталог курсов» или напишите нам:",
                reply_markup=kb.as_markup()
            )
            return

        kb = InlineKeyboardBuilder()
        for cid, title, price in matches[:12]:
            short_t = title[:38] + "…" if len(title) > 38 else title
            kb.button(text=f"№{cid} | {short_t} ({price}₽)", callback_data=f"course_{cid}_-1_0")
        kb.adjust(1)

        extra = f"\n<i>Показаны первые 12 из {len(matches)} совпадений.</i>" if len(matches) > 12 else ""
        await message.answer(
            f"🔍 <b>Найдено курсов: {len(matches)}</b>{extra}\n\n"
            f"Нажмите на курс для просмотра или отправьте номера в чат для заказа:",
            parse_mode=ParseMode.HTML,
            reply_markup=kb.as_markup()
        )

    # --- 6. КАТАЛОГ И ИНСТРУКЦИЯ ---
    @dp.message(F.text.in_({"📚 Каталог курсов", "/catalog", "/courses"}))
    async def catalog_cmd(message: types.Message):
        await record_user(message.from_user)
        async with aiosqlite.connect(db_path) as db:
            async with db.execute("SELECT id, title, price, category FROM courses ORDER BY id ASC") as cur:
                courses = await cur.fetchall()

        if not courses:
            await message.answer("❌ Каталог курсов временно пуст или обновляется.")
            return

        if len(courses) <= 25:
            items = "\n".join([f"<code>{c[0]}</code> — {html.escape(str(c[1]))} (<b>{c[2]} руб.</b>)" for c in courses])
            await message.answer(
                f"📚 <b>Список доступных курсов:</b>\n\n{items}\n\n"
                f"💡 <i>Отправьте боту номера курсов через запятую для заказа.</i>",
                parse_mode=ParseMode.HTML
            )
        else:
            content = f"КАТАЛОГ КУРСОВ ({bot_name})\n" + "=" * 40 + "\n\n"
            for cid, title, price, cat in courses:
                cat_str = f"[{cat}] " if cat and cat != "Без категории" else ""
                content += f"№{cid} — {cat_str}{title} — {price} руб.\n"
            content += "\n" + "=" * 40 + "\nОтправьте выбранные номера через запятую боту."

            doc = types.BufferedInputFile(content.encode("utf-8"), filename="catalog_kursov.txt")
            await message.answer_document(
                document=doc,
                caption=f"📚 <b>Полный перечень курсов ({len(courses)} шт.)</b>\n\nОтправьте нужные номера через запятую в этот чат.",
                parse_mode=ParseMode.HTML
            )

    @dp.message(F.text.in_({"ℹ️ Как сделать заказ", "/help"}))
    async def help_cmd(message: types.Message):
        await record_user(message.from_user)
        kb = InlineKeyboardBuilder()
        kb.button(text="💬 Задать вопрос", callback_data="ask_support")
        await message.answer(
            "🛒 <b>Как сделать заказ:</b>\n\n"
            "1️⃣ Выберите курс через <b>«📂 Категории»</b>, <b>«🔍 Поиск курса»</b> или файл <b>«📚 Каталог курсов»</b>.\n"
            "2️⃣ Отправьте в этот чат номера курсов через запятую (например: <code>1, 4, 12</code>).\n"
            "3️⃣ Бот рассчитает сумму и выдаст реквизиты.\n"
            "4️⃣ Оплатите и отправьте фото, скриншот или PDF-чек прямо сюда.\n"
            "5️⃣ После подтверждения оплаты ссылки придут в этот чат!\n\n"
            "Если возник вопрос — нажмите кнопку ниже 👇",
            parse_mode=ParseMode.HTML,
            reply_markup=kb.as_markup()
        )

    # --- 7. УПРАВЛЕНИЕ РЕКВИЗИТАМИ ОПЛАТЫ (АДМИН) ---
    async def render_payments_admin_view():
        methods = await get_payment_methods()
        kb = InlineKeyboardBuilder()
        if not methods:
            text = f"💳 <b>[{bot_name}] Реквизиты оплаты пусты.</b>\n\nДобавьте карту или кошелёк кнопкой ниже:"
        else:
            lines = [f"💳 <b>[{bot_name}] Активные реквизиты:</b>\n"]
            for pm_id, bank, num in methods:
                lines.append(f"• <b>{html.escape(str(bank))}:</b> <code>{html.escape(str(num))}</code>")
                kb.button(text=f"❌ Удалить: {bank}", callback_data=f"pm_del_{pm_id}")
            text = "\n".join(lines)
        kb.button(text="➕ Добавить реквизит", callback_data="pm_add")
        kb.adjust(1)
        return text, kb.as_markup()

    @dp.message(F.text.in_({"💳 Реквизиты", "/payments"}))
    async def payments_admin_cmd(message: types.Message):
        if message.from_user.id != ADMIN_ID:
            return
        text, markup = await render_payments_admin_view()
        await message.answer(text, parse_mode=ParseMode.HTML, reply_markup=markup)

    @dp.callback_query(F.data.startswith("pm_del_"))
    async def payment_delete_cb(callback: types.CallbackQuery):
        if callback.from_user.id != ADMIN_ID:
            return
        pm_id = int(callback.data.split("_")[2])
        async with aiosqlite.connect(db_path) as db:
            await db.execute("DELETE FROM payment_methods WHERE id = ?", (pm_id,))
            await db.commit()
        text, markup = await render_payments_admin_view()
        await callback.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)
        await callback.answer("Реквизит удалён")

    @dp.callback_query(F.data == "pm_add")
    async def payment_add_start(callback: types.CallbackQuery, state: FSMContext):
        if callback.from_user.id != ADMIN_ID:
            return
        await state.set_state(PaymentFSM.waiting_for_bank)
        kb = InlineKeyboardBuilder()
        kb.button(text="❌ Отмена", callback_data="pm_cancel")
        await callback.message.answer(
            "1️⃣ Введите <b>название банка или платёжной системы</b>\n(например: <code>Т-Банк</code> или <code>Юmoney</code>):",
            parse_mode=ParseMode.HTML,
            reply_markup=kb.as_markup()
        )
        await callback.answer()

    @dp.callback_query(F.data == "pm_cancel")
    async def payment_add_cancel(callback: types.CallbackQuery, state: FSMContext):
        if callback.from_user.id != ADMIN_ID:
            return
        await state.clear()
        await callback.message.edit_text("❌ Добавление реквизита отменено.")
        await callback.answer()

    @dp.message(PaymentFSM.waiting_for_bank)
    async def payment_add_bank(message: types.Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID:
            return
        if not message.text or message.text in MENU_BUTTONS or message.text.startswith("/"):
            await state.clear()
            return
        await state.update_data(pm_bank=message.text.strip())
        await state.set_state(PaymentFSM.waiting_for_number)
        kb = InlineKeyboardBuilder()
        kb.button(text="❌ Отмена", callback_data="pm_cancel")
        await message.answer(
            "2️⃣ Введите <b>номер карты, кошелька или телефона</b>\n(например: <code>2200 1234 5678 9012</code>):",
            parse_mode=ParseMode.HTML,
            reply_markup=kb.as_markup()
        )

    @dp.message(PaymentFSM.waiting_for_number)
    async def payment_add_number(message: types.Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID:
            return
        if not message.text or message.text in MENU_BUTTONS or message.text.startswith("/"):
            await state.clear()
            return
        data = await state.get_data()
        bank_name = data.get("pm_bank", "Карта")
        account_num = message.text.strip()
        await state.clear()

        async with aiosqlite.connect(db_path) as db:
            await db.execute(
                "INSERT INTO payment_methods (bank_name, account_num) VALUES (?, ?)",
                (bank_name, account_num)
            )
            await db.commit()

        text, markup = await render_payments_admin_view()
        await message.answer(
            f"✅ Добавлено: <b>{html.escape(bank_name)}</b> — <code>{html.escape(account_num)}</code>\n\n{text}",
            parse_mode=ParseMode.HTML,
            reply_markup=markup
        )

    # --- 8. УПРАВЛЕНИЕ СКИДКАМИ ---
    @dp.message(Command("promo"))
    @dp.message(F.text.in_({"🏷 Скидки и акции", "🎁 Акции и скидки"}))
    async def promo_control(message: types.Message, state: FSMContext):
        parts = message.text.split() if message.text else []
        is_admin = (message.from_user.id == ADMIN_ID)
        cfg = await get_promo_config()

        if not is_admin:
            if cfg["active"]:
                d_msg = f" до {cfg['until']}" if cfg["until"] else ""
                await message.answer(
                    f"🎁 <b>Действующая акция:</b>\n\n"
                    f"Скидка <b>{cfg['percent']}%</b> на заказы от <b>{cfg['min_sum']} руб.</b>{d_msg}!\n\n"
                    f"Применяется автоматически.",
                    parse_mode=ParseMode.HTML
                )
            else:
                await message.answer("ℹ️ В данный момент спец-акций нет, действуют базовые цены.")
            return

        if len(parts) > 1 and parts[1].lower() == "on":
            percent = int(parts[2]) if len(parts) > 2 else 20
            min_sum = int(parts[3]) if len(parts) > 3 else 1000
            until_date = parts[4] if len(parts) > 4 else ""
            if until_date:
                try:
                    datetime.strptime(until_date, "%d.%m.%Y")
                except ValueError:
                    await message.answer("⚠️ Неверный формат даты. Пример: <code>31.12.2026</code>", parse_mode=ParseMode.HTML)
                    return
            async with aiosqlite.connect(db_path) as db:
                await db.execute("UPDATE settings SET val_text = '1' WHERE key = 'promo_active'")
                await db.execute("UPDATE settings SET val_text = ? WHERE key = 'promo_percent'", (str(percent),))
                await db.execute("UPDATE settings SET val_text = ? WHERE key = 'promo_min_sum'", (str(min_sum),))
                await db.execute("UPDATE settings SET val_text = ? WHERE key = 'promo_until'", (until_date,))
                await db.commit()
            await message.answer(f"🟢 [{bot_name}] Скидка {percent}% от {min_sum} руб. включена!")
            return

        if len(parts) > 1 and parts[1].lower() == "off":
            async with aiosqlite.connect(db_path) as db:
                await db.execute("UPDATE settings SET val_text = '0' WHERE key = 'promo_active'")
                await db.commit()
            await message.answer(f"🔴 [{bot_name}] Скидка отключена.")
            return

        await show_promo_menu(message.answer, cfg)

    async def show_promo_menu(target_fn, cfg: dict):
        status = "🟢 ВКЛЮЧЕНА" if cfg["active"] else "🔴 ВЫКЛЮЧЕНА"
        date_info = f"\nДействует до: {cfg['until']}" if cfg["until"] else "\nСрок: бессрочно"

        kb = InlineKeyboardBuilder()
        if cfg["active"]:
            kb.button(text="🔴 Выключить скидку", callback_data="promo_toggle_off")
        else:
            kb.button(text=f"🟢 Включить ({cfg['percent']}% от {cfg['min_sum']}₽)", callback_data="promo_toggle_on")
        kb.button(text="✏️ Настроить параметры", callback_data="promo_edit")
        kb.adjust(1)

        await target_fn(
            f"📊 <b>[{bot_name}] Управление скидками:</b>\n\n"
            f"Статус: <b>{status}</b>\n"
            f"Размер: <b>{cfg['percent']}%</b>\n"
            f"Порог: от <b>{cfg['min_sum']} руб.</b>{date_info}",
            parse_mode=ParseMode.HTML,
            reply_markup=kb.as_markup()
        )

    @dp.callback_query(F.data.startswith("promo_toggle_"))
    async def promo_toggle_cb(callback: types.CallbackQuery):
        if callback.from_user.id != ADMIN_ID:
            return
        act = callback.data.split("_")[2]
        async with aiosqlite.connect(db_path) as db:
            await db.execute("UPDATE settings SET val_text = ? WHERE key = 'promo_active'", ("0" if act == "off" else "1",))
            await db.commit()
        cfg = await get_promo_config()
        await show_promo_menu(callback.message.edit_text, cfg)
        await callback.answer("Обновлено")

    @dp.callback_query(F.data == "promo_edit")
    async def promo_edit_start(callback: types.CallbackQuery, state: FSMContext):
        if callback.from_user.id != ADMIN_ID:
            return
        await state.set_state(PromoFSM.waiting_for_percent)
        await callback.message.answer("1️⃣ Введите процент скидки (только число, например: <code>25</code>):", parse_mode=ParseMode.HTML)
        await callback.answer()

    @dp.message(PromoFSM.waiting_for_percent)
    async def promo_step_percent(message: types.Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID:
            return
        if not message.text or not message.text.strip().isdigit():
            await message.answer("⚠️ Введите целое число (например, 20).")
            return
        await state.update_data(p_percent=int(message.text.strip()))
        await state.set_state(PromoFSM.waiting_for_min_sum)
        await message.answer("2️⃣ Введите минимальную сумму заказа (например: <code>1000</code>):", parse_mode=ParseMode.HTML)

    @dp.message(PromoFSM.waiting_for_min_sum)
    async def promo_step_sum(message: types.Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID:
            return
        if not message.text or not message.text.strip().isdigit():
            await message.answer("⚠️ Введите целое число (например, 1000).")
            return
        await state.update_data(p_min_sum=int(message.text.strip()))
        await state.set_state(PromoFSM.waiting_for_until)
        kb = InlineKeyboardBuilder()
        kb.button(text="♾ Бессрочно", callback_data="promo_no_date")
        await message.answer(
            "3️⃣ Введите дату окончания в формате <code>ДД.ММ.ГГГГ</code> (например: <code>31.12.2026</code>) или нажмите кнопку ниже:",
            parse_mode=ParseMode.HTML,
            reply_markup=kb.as_markup()
        )

    @dp.callback_query(PromoFSM.waiting_for_until, F.data == "promo_no_date")
    async def promo_save_no_date(callback: types.CallbackQuery, state: FSMContext):
        data = await state.get_data()
        await state.clear()
        async with aiosqlite.connect(db_path) as db:
            await db.execute("UPDATE settings SET val_text = '1' WHERE key = 'promo_active'")
            await db.execute("UPDATE settings SET val_text = ? WHERE key = 'promo_percent'", (str(data["p_percent"]),))
            await db.execute("UPDATE settings SET val_text = ? WHERE key = 'promo_min_sum'", (str(data["p_min_sum"]),))
            await db.execute("UPDATE settings SET val_text = '' WHERE key = 'promo_until'")
            await db.commit()
        await callback.message.edit_text(f"🟢 Скидка {data['p_percent']}% от {data['p_min_sum']} руб. (бессрочно) включена!")
        await callback.answer()

    @dp.message(PromoFSM.waiting_for_until)
    async def promo_save_with_date(message: types.Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID:
            return
        date_str = (message.text or "").strip()
        try:
            datetime.strptime(date_str, "%d.%m.%Y")
        except ValueError:
            await message.answer("⚠️ Неверный формат. Пример: <code>31.12.2026</code>", parse_mode=ParseMode.HTML)
            return
        data = await state.get_data()
        await state.clear()
        async with aiosqlite.connect(db_path) as db:
            await db.execute("UPDATE settings SET val_text = '1' WHERE key = 'promo_active'")
            await db.execute("UPDATE settings SET val_text = ? WHERE key = 'promo_percent'", (str(data["p_percent"]),))
            await db.execute("UPDATE settings SET val_text = ? WHERE key = 'promo_min_sum'", (str(data["p_min_sum"]),))
            await db.execute("UPDATE settings SET val_text = ? WHERE key = 'promo_until'", (date_str,))
            await db.commit()
        await message.answer(f"🟢 Скидка {data['p_percent']}% от {data['p_min_sum']} руб. до {date_str} включена!")

    # --- 9. СИНХРОНИЗАЦИЯ, СТАТИСТИКА, СПИСОК И УПРАВЛЕНИЕ КЛИЕНТАМИ ---
    @dp.message(F.text.in_({"🔄 Обновить курсы", "/sync"}))
    async def sync_cmd(message: types.Message):
        if message.from_user.id != ADMIN_ID:
            return
        count = await sync_courses_from_sheets()
        await message.answer(f"✅ [{bot_name}] Каталог обновлён: <b>{count} курсов</b>.", parse_mode=ParseMode.HTML)

    @dp.message(F.text == "📊 Статистика базы")
    async def stats_cmd(message: types.Message):
        if message.from_user.id != ADMIN_ID:
            return
        users = await sb_request("GET", "users?select=user_id,is_buyer,allow_mailing,total_spent") or []
        orders = await sb_request("GET", f"orders?bot_name=eq.{bot_name}&select=status,total_price") or []

        async with aiosqlite.connect(db_path) as db:
            async with db.execute("SELECT COUNT(*) FROM courses") as cur:
                courses_count = (await cur.fetchone())[0]

        total_users = len(users)
        active_mailing = sum(1 for u in users if u.get("allow_mailing", True))
        buyers_count = sum(1 for u in users if u.get("is_buyer"))

        paid_orders = [o for o in orders if o.get("status") == "paid"]
        pending_orders = [o for o in orders if o.get("status") == "pending"]
        paid_sum = sum(o.get("total_price") or 0 for o in paid_orders)

        await message.answer(
            f"📊 <b>Статистика [{bot_name}]:</b>\n\n"
            f"👥 Всего клиентов в Supabase: <b>{total_users}</b>\n"
            f"📢 Активных для рассылки: <b>{active_mailing}</b>\n"
            f"💰 Покупателей: <b>{buyers_count}</b>\n"
            f"📚 Курсов в каталоге: <b>{courses_count}</b>\n\n"
            f"✅ Оплаченных заказов (бот): <b>{len(paid_orders)}</b> (на <b>{paid_sum} руб.</b>)\n"
            f"⏳ Ожидает проверки: <b>{len(pending_orders)}</b>",
            parse_mode=ParseMode.HTML
        )

    @dp.message(F.text.in_({"👥 Список клиентов", "/users"}))
    async def users_list_cmd(message: types.Message):
        if message.from_user.id != ADMIN_ID:
            return
        users = await sb_request(
            "GET",
            "users?select=user_id,username,full_name,is_buyer,purchased_ids,total_spent,allow_mailing&order=is_buyer.desc,user_id.desc"
        )
        if not users:
            await message.answer("ℹ️ База клиентов пуста.")
            return

        if len(users) <= 25:
            lines = []
            for i, u in enumerate(users, 1):
                f_name = html.escape(u.get("full_name") or "Без имени")
                u_name = f" ({html.escape(u['username'])})" if u.get("username") else ""
                badge = " 💰" if u.get("is_buyer") else ""
                mail_off = " 🔕" if not u.get("allow_mailing", True) else ""
                bought = f" | Курсы: {u['purchased_ids']}" if u.get("purchased_ids") else ""
                lines.append(f"{i}. <b>{f_name}</b>{u_name}{badge}{mail_off} — <code>{u['user_id']}</code>{bought}")
            await message.answer(
                f"👥 <b>Клиенты ({len(users)} чел.):</b>\n<i>💰 покупатель | 🔕 без рассылки</i>\n\n" + "\n".join(lines),
                parse_mode=ParseMode.HTML
            )
        else:
            file_lines = []
            for i, u in enumerate(users, 1):
                f_name = u.get("full_name") or "Без имени"
                u_name = f" ({u['username']})" if u.get("username") else ""
                badge = " [Покупатель]" if u.get("is_buyer") else ""
                mail = "" if u.get("allow_mailing", True) else " [Рассылка выкл]"
                bought = f" | Куплено: {u['purchased_ids']}" if u.get("purchased_ids") else ""
                spent = f" | Потрачено: {u.get('total_spent', 0)}₽" if u.get("total_spent") else ""
                file_lines.append(f"{i}. {f_name}{u_name}{badge}{mail} — ID: {u['user_id']}{bought}{spent}")

            content = "БАЗА КЛИЕНТОВ (SUPABASE)\n" + "=" * 40 + "\n\n" + "\n".join(file_lines)
            doc = types.BufferedInputFile(content.encode("utf-8"), filename="users_list.txt")
            await message.answer_document(
                document=doc,
                caption=f"👥 <b>Всего клиентов в базе: {len(users)}</b>",
                parse_mode=ParseMode.HTML
            )

    @dp.message(F.text == "🚫 Управление базой")
    async def manage_user_start(message: types.Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID:
            return
        await state.set_state(UserManageFSM.waiting_for_user_id)
        kb = InlineKeyboardBuilder()
        kb.button(text="❌ Отмена", callback_data="cancel_usermgmt")
        await message.answer(
            "🚫 <b>Управление клиентом</b>\n\n"
            "Отправьте цифровой <b>ID клиента</b> (его можно скопировать из списка клиентов), "
            "чтобы исключить его из рассылки, вернуть в рассылку или удалить из базы:",
            parse_mode=ParseMode.HTML,
            reply_markup=kb.as_markup()
        )

    @dp.callback_query(F.data == "cancel_usermgmt")
    async def manage_user_cancel(callback: types.CallbackQuery, state: FSMContext):
        await state.clear()
        await callback.message.edit_text("❌ Отменено.")
        await callback.answer()

    @dp.message(UserManageFSM.waiting_for_user_id)
    async def manage_user_lookup(message: types.Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID:
            return
        if not message.text or not message.text.strip().isdigit():
            await message.answer("⚠️ Введите только цифровой ID (например: <code>123456789</code>).", parse_mode=ParseMode.HTML)
            return

        uid = int(message.text.strip())
        await state.clear()

        rows = await sb_request("GET", f"users?user_id=eq.{uid}&limit=1")
        if not rows:
            await message.answer(f"❌ Пользователь с ID <code>{uid}</code> не найден в базе.", parse_mode=ParseMode.HTML)
            return

        u = rows[0]
        mail_status = "🟢 Включена" if u.get("allow_mailing", True) else "🔴 Отключена"
        kb = InlineKeyboardBuilder()
        if u.get("allow_mailing", True):
            kb.button(text="🔕 Исключить из рассылки", callback_data=f"um_mail_off_{uid}")
        else:
            kb.button(text="🔔 Вернуть в рассылку", callback_data=f"um_mail_on_{uid}")
        kb.button(text="🗑 Удалить из базы навсегда", callback_data=f"um_del_{uid}")
        kb.adjust(1)

        await message.answer(
            f"👤 <b>Карточка клиента:</b>\n"
            f"Имя: {html.escape(u.get('full_name') or 'Без имени')}\n"
            f"Ник: {html.escape(u.get('username') or '—')}\n"
            f"ID: <code>{uid}</code>\n"
            f"Куплено курсов: {html.escape(u.get('purchased_ids') or 'нет')}\n"
            f"Потрачено: {u.get('total_spent', 0)} руб.\n"
            f"Рассылка: <b>{mail_status}</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=kb.as_markup()
        )

    @dp.callback_query(F.data.startswith("um_"))
    async def manage_user_action(callback: types.CallbackQuery):
        if callback.from_user.id != ADMIN_ID:
            return
        parts = callback.data.split("_")
        if parts[1] == "del":
            uid = int(parts[2])
            await sb_request("DELETE", f"users?user_id=eq.{uid}")
            await callback.message.edit_text(f"🗑 Пользователь <code>{uid}</code> удалён из базы.", parse_mode=ParseMode.HTML)
        elif parts[1] == "mail":
            act = parts[2]
            uid = int(parts[3])
            val = (act == "on")
            await sb_request("PATCH", f"users?user_id=eq.{uid}", json_data={"allow_mailing": val})
            status_txt = "возвращён в рассылку 🔔" if val else "исключён из рассылки 🔕"
            await callback.message.edit_text(f"✅ Пользователь <code>{uid}</code> {status_txt}.", parse_mode=ParseMode.HTML)
        await callback.answer()

    # --- 10. РАССЫЛКА (ТОЛЬКО allow_mailing = true) ---
    @dp.message(F.text.in_({"📢 Сделать рассылку", "/broadcast"}))
    async def broadcast_start(message: types.Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID:
            return
        await state.set_state(BroadcastFSM.waiting_for_message)
        kb = InlineKeyboardBuilder()
        kb.button(text="❌ Отмена", callback_data="cancel_broadcast")
        await message.answer(
            "📢 <b>Режим создания рассылки</b>\n\n"
            "Пришлите текст, фото с описанием или перешлите пост. "
            "Сообщение получат все клиенты, у которых включена рассылка.",
            parse_mode=ParseMode.HTML,
            reply_markup=kb.as_markup()
        )

    @dp.message(BroadcastFSM.waiting_for_message)
    async def broadcast_incoming(message: types.Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID:
            return
        if message.text in ["/cancel", "❌ Отмена", "Отмена"]:
            await state.clear()
            await message.answer("❌ Рассылка отменена.", reply_markup=get_admin_kb())
            return

        users = await sb_request("GET", "users?allow_mailing=eq.true&select=user_id") or []
        count = len(users)
        await state.update_data(broadcast_msg_id=message.message_id, broadcast_chat_id=message.chat.id)

        kb = InlineKeyboardBuilder()
        kb.button(text=f"🚀 Отправить ({count} чел.)", callback_data="confirm_broadcast")
        kb.button(text="❌ Отмена", callback_data="cancel_broadcast")
        kb.adjust(1)

        await message.reply(
            f"📋 <b>Сообщение принято!</b>\n👥 Адресатов: <b>{count}</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=kb.as_markup()
        )

    @dp.callback_query(F.data == "confirm_broadcast")
    async def broadcast_confirm(callback: types.CallbackQuery, state: FSMContext):
        if callback.from_user.id != ADMIN_ID:
            return
        data = await state.get_data()
        b_mid = data.get("broadcast_msg_id")
        b_cid = data.get("broadcast_chat_id")
        await state.clear()

        if not b_mid or not b_cid:
            await callback.message.edit_text("⚠️ Ошибка: сообщение не найдено.")
            return

        users = await sb_request("GET", "users?allow_mailing=eq.true&select=user_id") or []
        if not users:
            await callback.message.edit_text("ℹ️ Нет активных адресатов.")
            return

        status_msg = await callback.message.edit_text(f"⏳ Рассылка запущена на {len(users)} пользователей...")
        success, blocked, errors = 0, 0, 0

        for row in users:
            u_id = row["user_id"]
            try:
                await bot.copy_message(chat_id=u_id, from_chat_id=b_cid, message_id=b_mid)
                success += 1
            except TelegramForbiddenError:
                blocked += 1
                await sb_request("PATCH", f"users?user_id=eq.{u_id}", json_data={"allow_mailing": False})
            except TelegramRetryAfter as e:
                await asyncio.sleep(e.retry_after)
                try:
                    await bot.copy_message(chat_id=u_id, from_chat_id=b_cid, message_id=b_mid)
                    success += 1
                except Exception:
                    errors += 1
            except Exception:
                errors += 1
            await asyncio.sleep(0.04)

        await status_msg.edit_text(
            f"📢 <b>Рассылка завершена!</b>\n\n"
            f"👥 Всего: <b>{len(users)}</b>\n"
            f"✅ Доставлено: <b>{success}</b>\n"
            f"🚫 Заблокировали бота (отключены): <b>{blocked}</b>\n"
            f"⚠️ Ошибок: <b>{errors}</b>",
            parse_mode=ParseMode.HTML
        )
        await callback.answer("Готово!")

    @dp.callback_query(F.data == "cancel_broadcast")
    async def broadcast_cancel(callback: types.CallbackQuery, state: FSMContext):
        if callback.from_user.id != ADMIN_ID:
            return
        await state.clear()
        await callback.message.edit_text("❌ Рассылка отменена.")
        await callback.answer()

    # --- 11. ОФОРМЛЕНИЕ ЗАКАЗА ПО НОМЕРАМ ---
    @dp.message(StateFilter(None, OrderFSM.waiting_for_receipt), F.text, ~F.text.startswith("/"))
    async def process_articles(message: types.Message, state: FSMContext):
        if message.text in MENU_BUTTONS:
            return
        await record_user(message.from_user)

        raw_ids = re.findall(r"\b\d+\b", message.text)
        if not raw_ids:
            await message.answer(
                "Отправьте номера курсов цифрами (например: <code>1, 2, 5</code>) или воспользуйтесь кнопками меню внизу.",
                parse_mode=ParseMode.HTML
            )
            return

        unique_ids = list(dict.fromkeys([int(i) for i in raw_ids]))

        async def send_fn(txt):
            await message.answer(txt, parse_mode=ParseMode.HTML)

        await create_order_for_user(message.chat.id, message.from_user.id, unique_ids, state, send_fn)

    # --- 12. ПРИЁМ ЧЕКОВ (ФОТО И PDF) ---
    @dp.message(StateFilter(None, OrderFSM.waiting_for_receipt), F.photo | F.document)
    async def process_receipt(message: types.Message, state: FSMContext):
        data = await state.get_data()
        order_id = data.get("order_id")

        if not order_id:
            pending = await sb_request(
                "GET",
                f"orders?user_id=eq.{message.from_user.id}&bot_name=eq.{bot_name}&status=eq.pending&order=id.desc&limit=1"
            )
            if pending:
                order_id = pending[0]["id"]

        if not order_id:
            await message.answer("⚠️ Не найден активный заказ. Выберите курс или отправьте его номер в чат.")
            return

        ord_rows = await sb_request("GET", f"orders?id=eq.{order_id}&limit=1")
        if not ord_rows:
            return
        ord_data = ord_rows[0]
        c_ids = [int(x) for x in ord_data["course_ids"].split(",") if x.strip()]
        order_price = ord_data["total_price"]

        placeholders = ",".join("?" for _ in c_ids)
        async with aiosqlite.connect(db_path) as db:
            async with db.execute(f"SELECT id, title FROM courses WHERE id IN ({placeholders})", c_ids) as cur:
                c_info = await cur.fetchall()

        kb = InlineKeyboardBuilder()
        kb.button(text="✅ Подтвердить", callback_data=f"adm_appr_{order_id}")
        kb.button(text="❌ Отклонить", callback_data=f"adm_rejc_{order_id}")
        kb.adjust(2)

        user_str = f"@{message.from_user.username}" if message.from_user.username else f"ID: {message.from_user.id}"
        courses_brief = "\n".join([f"• №{c[0]} {html.escape(str(c[1]))}" for c in c_info[:7]])
        if len(c_info) > 7:
            courses_brief += f"\n...и еще {len(c_info) - 7} шт."

        caption_text = (
            f"🧾 <b>[{bot_name}] Оплата заказа #{order_id}</b>\n"
            f"👤 Клиент: {html.escape(user_str)} (<code>{message.from_user.id}</code>)\n"
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
            await message.answer("✅ Чек отправлен на проверку. Ссылки придут сразу после одобрения.")
            await state.clear()
        except Exception as e:
            logging.error(f"[{bot_name}] Ошибка пересылки чека: {e}")

    # --- 13. ОДОБРЕНИЕ И ОТКЛОНЕНИЕ ЧЕКОВ ---
    @dp.callback_query(F.data.startswith("adm_appr_"))
    async def admin_approve(callback: types.CallbackQuery):
        if callback.from_user.id != ADMIN_ID:
            return
        order_id = int(callback.data.split("_")[2])

        ord_rows = await sb_request("GET", f"orders?id=eq.{order_id}&limit=1")
        if not ord_rows or ord_rows[0]["status"] == "paid":
            await callback.answer("Заказ уже обработан.")
            return

        order = ord_rows[0]
        user_id = order["user_id"]
        ids = [int(x) for x in order["course_ids"].split(",") if x.strip()]
        order_price = order.get("total_price") or 0

        placeholders = ",".join("?" for _ in ids)
        async with aiosqlite.connect(db_path) as db:
            async with db.execute(f"SELECT title, link FROM courses WHERE id IN ({placeholders})", ids) as cur:
                courses = await cur.fetchall()

        await sb_request("PATCH", f"orders?id=eq.{order_id}", json_data={"status": "paid"})

        # Обновляем purchased_ids, is_buyer и total_spent у клиента в Supabase
        u_rows = await sb_request("GET", f"users?user_id=eq.{user_id}&limit=1")
        if u_rows:
            old_ids = [x.strip() for x in (u_rows[0].get("purchased_ids") or "").split(",") if x.strip()]
            new_ids = list(dict.fromkeys(old_ids + [str(i) for i in ids]))
            new_spent = (u_rows[0].get("total_spent") or 0) + order_price
            await sb_request(
                "PATCH",
                f"users?user_id=eq.{user_id}",
                json_data={
                    "is_buyer": True,
                    "purchased_ids": ",".join(new_ids),
                    "total_spent": new_spent
                }
            )

        try:
            if len(courses) > 10:
                content = f"ВАШИ КУРСЫ (ЗАКАЗ #{order_id})\n" + "=" * 35 + "\n\n"
                content += "\n\n".join([f"{c[0]}:\n{c[1]}" for c in courses])
                doc = types.BufferedInputFile(content.encode("utf-8"), filename=f"Order_{order_id}.txt")
                await bot.send_document(
                    chat_id=user_id,
                    document=doc,
                    caption="🎉 Оплата подтверждена! Ваши курсы в файле выше."
                )
            else:
                lines = [f"🎉 <b>Оплата подтверждена! Заказ #{order_id}:</b>\n"]
                lines.extend([f"• <b>{html.escape(str(c[0]))}</b>\n👉 {str(c[1]).strip()}" for c in courses])
                await bot.send_message(chat_id=user_id, text="\n\n".join(lines), parse_mode=ParseMode.HTML)
        except Exception as e:
            logging.error(f"[{bot_name}] Ошибка отправки ссылок: {e}")

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

    @dp.callback_query(F.data.startswith("adm_rejc_"))
    async def admin_reject(callback: types.CallbackQuery):
        if callback.from_user.id != ADMIN_ID:
            return
        order_id = int(callback.data.split("_")[2])
        ord_rows = await sb_request("GET", f"orders?id=eq.{order_id}&limit=1")
        if ord_rows:
            await sb_request("PATCH", f"orders?id=eq.{order_id}", json_data={"status": "rejected"})
            try:
                await bot.send_message(chat_id=ord_rows[0]["user_id"], text=f"❌ Оплата по заказу #{order_id} отклонена.")
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

    return bot, dp, init_db


async def main():
    logging.basicConfig(level=logging.INFO)
    tasks = []
    for cfg in BOT_CONFIGS:
        bot_inst, dp_inst, init_fn = create_bot_app(cfg)
        await init_fn()
        tasks.append(dp_inst.start_polling(bot_inst))

    logging.info("Оба бота успешно инициализированы и запущены!")
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())
