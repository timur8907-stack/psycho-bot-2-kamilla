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

ADMIN_ID = int(os.getenv("ADMIN_ID", "688074424"))[span_0](start_span)[span_0](end_span)

# Конфигурация двух ботов
BOT_CONFIGS = [
    {
        "name": "Основной канал",
        "token": "8784163183:AAFXRAsNp9t1dz3Of3vgkadog_xgel59Y34",
        "db_path": "courses_bot1.db",
        "sheet_url": "https://docs.google.com/spreadsheets/d/14Yav2_wV-jUWWji6iOBZVBykJh1anvDWEoUZwTUWxD4/edit?usp=drivesdk",
        "default_payments": [
            ("ВТБ", "2200 2402 5150 6917"),
            ("Яндекс Пэй", "2204 3107 2587 7388"),
            ("Сбербанк", "2202 2068 1402 4274")
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
            ("ВТБ", "2200240251506917")
        ]
    }
]

# Кнопки меню для исключения из обработки артикулов
MENU_BUTTONS = {
    "📚 Каталог курсов", "🎁 Акции и скидки", "ℹ️ Как сделать заказ",
    "📢 Сделать рассылку", "👥 Список клиентов", "💳 Реквизиты",
    "🔄 Обновить курсы", "🏷 Скидки и акции", "📊 Статистика базы", "❌ Отмена"
}

class OrderFSM(StatesGroup):
    waiting_for_receipt = State()

class BroadcastFSM(StatesGroup):
    waiting_for_message = State()

class PaymentFSM(StatesGroup):
    waiting_for_title = State()
    waiting_for_details = State()

def get_export_url(share_url: str) -> str:
    match = re.search(r"/d/([a-zA-Z0-9-_]+)", share_url)[span_1](start_span)[span_1](end_span)
    if not match:
        return share_url
    sheet_id = match.group(1)[span_2](start_span)[span_2](end_span)
    return f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv[span_3](start_span)"[span_3](end_span)

def get_client_kb():
    builder = ReplyKeyboardBuilder()
    builder.button(text="📚 Каталог курсов")
    builder.button(text="🎁 Акции и скидки")
    builder.button(text="ℹ️ Как сделать заказ")
    builder.adjust(2, 1)
    return builder.as_markup(resize_keyboard=True)

def get_admin_kb():
    builder = ReplyKeyboardBuilder()
    builder.button(text="📚 Каталог курсов")
    builder.button(text="📢 Сделать рассылку")
    builder.button(text="👥 Список клиентов")
    builder.button(text="💳 Реквизиты")
    builder.button(text="🔄 Обновить курсы")
    builder.button(text="🏷 Скидки и акции")
    builder.button(text="📊 Статистика базы")
    builder.button(text="ℹ️ Как сделать заказ")
    builder.adjust(2, 2, 2, 2)
    return builder.as_markup(resize_keyboard=True)

def create_bot_app(cfg: dict):
    token = cfg["token"]
    db_path = cfg["db_path"]
    sheet_url = cfg["sheet_url"]
    default_payments = cfg["default_payments"]
    bot_name = cfg["name"]

    bot = Bot(token=token)[span_4](start_span)[span_4](end_span)
    dp = Dispatcher(storage=MemoryStorage())[span_5](start_span)[span_5](end_span)

    async def record_user(u: types.User):
        username = f"@{u.username}" if u.username else "[span_6](start_span)"[span_6](end_span)
        full_name = u.full_name or ""
        async with aiosqlite.connect(db_path) as db:
            await db.execute("""
                INSERT INTO users (user_id, username, full_name)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    username = excluded.username,
                    full_name = excluded.full_name
            """, (u.id, username, full_name))
            await db.commit()

    async def sync_courses_from_sheets():
        url = get_export_url(sheet_url)[span_7](start_span)[span_7](end_span)
        try:
            async with aiohttp.ClientSession() as session:[span_8](start_span)[span_8](end_span)
                async with session.get(url) as resp:[span_9](start_span)[span_9](end_span)
                    if resp.status != 200:[span_10](start_span)[span_10](end_span)
                        return 0[span_11](start_span)[span_11](end_span)
                    content = await resp.text()[span_12](start_span)[span_12](end_span)

            reader = csv.DictReader(io.StringIO(content))[span_13](start_span)[span_13](end_span)
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

            async with aiosqlite.connect(db_path) as db:[span_14](start_span)[span_14](end_span)
                await db.execute("DELETE FROM courses")[span_15](start_span)[span_15](end_span)
                await db.executemany([span_16](start_span)[span_16](end_span)
                    "INSERT INTO courses (id, title, price, link) VALUES (?, ?, ?, ?)",[span_17](start_span)[span_17](end_span)
                    data[span_18](start_span)[span_18](end_span)
                )
                await db.commit()[span_19](start_span)[span_19](end_span)
            return len(data)[span_20](start_span)[span_20](end_span)
        except Exception as e:
            logging.error(f"[{bot_name}] Ошибка синхронизации: {e}")
            return 0

    async def init_db():
        async with aiosqlite.connect(db_path) as db:[span_21](start_span)[span_21](end_span)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS courses (
                    id INTEGER PRIMARY KEY,
                    title TEXT,
                    price INTEGER,
                    link TEXT
                )
            """)[span_22](start_span)[span_22](end_span)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    course_ids TEXT,
                    total_price INTEGER,
                    status TEXT DEFAULT 'pending'
                )
            """)[span_23](start_span)[span_23](end_span)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    val_text TEXT
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    full_name TEXT
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS payment_methods (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT,
                    details TEXT
                )
            """)

            # Добавляем колонки при обновлении существующей базы
            try:
                await db.execute("ALTER TABLE users ADD COLUMN username TEXT")
            except Exception:
                pass
            try:
                await db.execute("ALTER TABLE users ADD COLUMN full_name TEXT")
            except Exception:
                pass

            await db.execute("INSERT OR IGNORE INTO users (user_id) SELECT DISTINCT user_id FROM orders")
            await db.execute("INSERT OR IGNORE INTO settings (key, val_text) VALUES ('promo_active', '0')")
            await db.execute("INSERT OR IGNORE INTO settings (key, val_text) VALUES ('promo_percent', '20')")
            await db.execute("INSERT OR IGNORE INTO settings (key, val_text) VALUES ('promo_min_sum', '1000')")
            await db.execute("INSERT OR IGNORE INTO settings (key, val_text) VALUES ('promo_until', '')")

            # Начальное наполнение реквизитов по умолчанию при первом запуске
            async with db.execute("SELECT COUNT(*) FROM payment_methods") as cur:
                pm_count = (await cur.fetchone())[0]
            if pm_count == 0:
                await db.executemany(
                    "INSERT INTO payment_methods (title, details) VALUES (?, ?)",
                    default_payments
                )

            await db.commit()[span_24](start_span)[span_24](end_span)

        try:
            await bot.set_my_commands([
                BotCommand(command="start", description="Главное меню"),
                BotCommand(command="catalog", description="Каталог курсов"),
                BotCommand(command="help", description="Как сделать заказ"),
            ])
        except Exception:
            pass

        await sync_courses_from_sheets()[span_25](start_span)[span_25](end_span)

    async def get_payment_details_text() -> str:
        async with aiosqlite.connect(db_path) as db:
            async with db.execute("SELECT title, details FROM payment_methods ORDER BY id ASC") as cur:
                methods = await cur.fetchall()

        if not methods:
            return "💳 <i>Реквизиты для оплаты уточняйте у администратора.</i>"

        lines = ["💳 <b>Реквизиты для оплаты:</b>\n"]
        for title, details in methods:
            lines.append(f"• <b>{html.escape(title)}:</b>\n<code>{html.escape(details)}</code>\n")
        lines.append("<i>(нажмите на номер карты или кошелька, чтобы скопировать)</i>")
        return "\n".join(lines)

    async def render_payment_methods_ui():
        async with aiosqlite.connect(db_path) as db:
            async with db.execute("SELECT id, title, details FROM payment_methods ORDER BY id ASC") as cur:
                methods = await cur.fetchall()

        kb = InlineKeyboardBuilder()
        if methods:
            text = f"💳 <b>[{bot_name}] Управление реквизитами:</b>\n\n"
            for m_id, m_title, m_details in methods:
                text += f"• <b>{html.escape(m_title)}:</b> <code>{html.escape(m_details)}</code>\n"
                kb.button(text=f"❌ Удалить {m_title[:14]}", callback_data=f"del_pm_{m_id}")
            text += "\n<i>Нажмите кнопку ниже, чтобы удалить реквизит или добавить новый:</i>"
        else:
            text = f"💳 <b>[{bot_name}] Управление реквизитами:</b>\n\n<i>Список реквизитов пуст. Покупатели сейчас не видят карты для перевода!</i>"

        kb.button(text="➕ Добавить реквизит", callback_data="add_pm")
        kb.adjust(1)
        return text, kb.as_markup()

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

    # 1. СТАРТ И МЕНЮ
    @dp.message(CommandStart())
    async def start_cmd(message: types.Message, state: FSMContext):
        await state.clear()[span_26](start_span)[span_26](end_span)
        await record_user(message.from_user)
        promo = await get_promo_config()

        promo_text = ""
        if promo["active"]:
            date_text = f" до {promo['until']}" if promo["until"] else ""
            promo_text = f"\n\n🎁 <b>Праздничная акция:</b> скидка {promo['percent']}% на заказы от {promo['min_sum']} руб.{date_text}!"

        is_admin = (message.from_user.id == ADMIN_ID)[span_27](start_span)[span_27](end_span)
        kb = get_admin_kb() if is_admin else get_client_kb()
        admin_note = "\n\n<i>👑 Вы вошли как администратор. Панель управления закреплена на кнопках внизу.</i>" if is_admin else ""

        await message.answer(
            "👋 Здравствуйте!\n\n"
            "Для заказа отправьте <b>номера (артикулы) курсов</b> через запятую или пробел.\n\n"
            "Пример: <code>1, 4, 12</code>\n\n"
            "Воспользуйтесь кнопками меню внизу для выбора действий."
            f"{promo_text}{admin_note}",
            parse_mode=ParseMode.HTML,
            reply_markup=kb
        )

    # 2. РЕКВИЗИТЫ ОПЛАТЫ (МЕНЮ АДМИНИСТРАТОРА)
    @dp.message(F.text.in_({"💳 Реквизиты", "/payments"}))
    async def payment_settings_cmd(message: types.Message):
        if message.from_user.id != ADMIN_ID:[span_28](start_span)[span_28](end_span)
            return
        text, kb = await render_payment_methods_ui()
        await message.answer(text, parse_mode=ParseMode.HTML, reply_markup=kb)

    @dp.callback_query(F.data.startswith("del_pm_"))
    async def del_payment_cb(callback: types.CallbackQuery):
        if callback.from_user.id != ADMIN_ID:[span_29](start_span)[span_29](end_span)
            return
        pm_id = int(callback.data.split("_")[2])
        async with aiosqlite.connect(db_path) as db:
            await db.execute("DELETE FROM payment_methods WHERE id = ?", (pm_id,))
            await db.commit()
        await callback.answer("Реквизит удален")
        text, kb = await render_payment_methods_ui()
        try:
            await callback.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
        except Exception:
            pass

    @dp.callback_query(F.data == "add_pm")
    async def add_payment_cb(callback: types.CallbackQuery, state: FSMContext):
        if callback.from_user.id != ADMIN_ID:[span_30](start_span)[span_30](end_span)
            return
        await state.set_state(PaymentFSM.waiting_for_title)
        kb = InlineKeyboardBuilder()
        kb.button(text="❌ Отмена", callback_data="cancel_pm")
        await callback.message.answer(
            "💳 <b>Добавление нового реквизита (Шаг 1 из 2)</b>\n\n"
            "Введите название банка или системы (например: <code>Т-Банк</code>, <code>Сбер</code> или <code>Юmoney</code>):",
            parse_mode=ParseMode.HTML,
            reply_markup=kb.as_markup()
        )
        await callback.answer()

    @dp.message(PaymentFSM.waiting_for_title)
    async def add_payment_title(message: types.Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID:[span_31](start_span)[span_31](end_span)
            return
        if message.text in ["/cancel", "❌ Отмена", "Отмена"]:
            await state.clear()[span_32](start_span)[span_32](end_span)
            await message.answer("❌ Добавление реквизита отменено.", reply_markup=get_admin_kb())
            return
        title = message.text.strip()
        await state.update_data(new_pm_title=title)
        await state.set_state(PaymentFSM.waiting_for_details)
        kb = InlineKeyboardBuilder()
        kb.button(text="❌ Отмена", callback_data="cancel_pm")
        await message.answer(
            f"Банк/система: <b>{html.escape(title)}</b>\n\n"
            "💳 <b>Шаг 2 из 2:</b>\n"
            "Отправьте номер карты, кошелька или телефона для перевода:",
            parse_mode=ParseMode.HTML,
            reply_markup=kb.as_markup()
        )

    @dp.message(PaymentFSM.waiting_for_details)
    async def add_payment_details(message: types.Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID:[span_33](start_span)[span_33](end_span)
            return
        if message.text in ["/cancel", "❌ Отмена", "Отмена"]:
            await state.clear()[span_34](start_span)[span_34](end_span)
            await message.answer("❌ Добавление реквизита отменено.", reply_markup=get_admin_kb())
            return
        details = message.text.strip()
        data = await state.get_data()[span_35](start_span)[span_35](end_span)
        title = data.get("new_pm_title", "Реквизиты")
        await state.clear()[span_36](start_span)[span_36](end_span)

        async with aiosqlite.connect(db_path) as db:
            await db.execute(
                "INSERT INTO payment_methods (title, details) VALUES (?, ?)",
                (title, details)
            )
            await db.commit()

        await message.answer(
            f"✅ <b>Реквизит успешно добавлен!</b>\n\n"
            f"• <b>{html.escape(title)}:</b> <code>{html.escape(details)}</code>",
            parse_mode=ParseMode.HTML,
            reply_markup=get_admin_kb()
        )
        text, kb = await render_payment_methods_ui()
        await message.answer(text, parse_mode=ParseMode.HTML, reply_markup=kb)

    @dp.callback_query(F.data == "cancel_pm")
    async def cancel_pm_cb(callback: types.CallbackQuery, state: FSMContext):
        if callback.from_user.id != ADMIN_ID:[span_37](start_span)[span_37](end_span)
            return
        await state.clear()[span_38](start_span)[span_38](end_span)
        await callback.message.edit_text("❌ Добавление реквизита отменено.")
        await callback.answer()

    # 3. ПРОСМОТР СПИСКА КЛИЕНТОВ (ТОЛЬКО АДМИНУ)
    @dp.message(F.text.in_({"👥 Список клиентов", "/users"}))
    async def users_list_cmd(message: types.Message):
        if message.from_user.id != ADMIN_ID:[span_39](start_span)[span_39](end_span)
            return

        async with aiosqlite.connect(db_path) as db:
            async with db.execute("SELECT user_id, username, full_name FROM users ORDER BY user_id DESC") as cur:
                users = await cur.fetchall()

        if not users:
            await message.answer(f"ℹ️ [{bot_name}] В базе пока нет пользователей.")
            return

        async with aiosqlite.connect(db_path) as db:
            async with db.execute("SELECT DISTINCT user_id FROM orders WHERE status = 'paid'") as cur:
                buyers = {row[0] for row in await cur.fetchall()}

        lines = []
        for i, (u_id, u_name, f_name) in enumerate(users, start=1):
            name_str = html.escape(f_name) if f_name else "Имя не указано"
            user_nick = f" ({html.escape(u_name)})" if u_name else ""
            buyer_badge = " 💰" if u_id in buyers else ""
            lines.append(f"{i}. <b>{name_str}</b>{user_nick}{buyer_badge} — <code>{u_id}</code>")

        if len(lines) <= 30:
            text = (
                f"👥 <b>[{bot_name}] Пользователи базы ({len(users)} чел.):</b>\n"
                f"<i>(Значком 💰 отмечены покупатели)</i>\n\n" +
                "\n".join(lines)
            )
            await message.answer(text, parse_mode=ParseMode.HTML)
        else:
            file_lines = []
            for i, (u_id, u_name, f_name) in enumerate(users, start=1):
                name_str = f_name if f_name else "Имя не указано"
                user_nick = f" ({u_name})" if u_name else ""
                buyer_badge = " [Покупатель]" if u_id in buyers else ""
                file_lines.append(f"{i}. {name_str}{user_nick}{buyer_badge} — ID: {u_id}")

            content = f"СПИСОК ПОЛЬЗОВАТЕЛЕЙ ({bot_name})\n" + "=" * 40 + "\n\n"
            content += "\n".join(file_lines)

            doc = types.BufferedInputFile(content.encode("utf-8"), filename="users_list.txt")
            await message.answer_document(
                document=doc,
                caption=f"👥 <b>[{bot_name}] Полный список пользователей ({len(users)} чел.)</b>\n\nФайл прикреплен выше.",
                parse_mode=ParseMode.HTML
            )

    # 4. КАТАЛОГ КУРСОВ
    @dp.message(F.text.in_({"📚 Каталог курсов", "/catalog", "/courses"}))
    async def catalog_cmd(message: types.Message):
        await record_user(message.from_user)
        async with aiosqlite.connect(db_path) as db:[span_40](start_span)[span_40](end_span)
            async with db.execute("SELECT id, title, price FROM courses ORDER BY id ASC") as cur:
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
            content += "\n".join([f"№{c[0]} — {c[1]} — {c[2]} руб." for c in courses])
            content += "\n\n" + "=" * 40 + "\nОтправьте выбранные номера через запятую боту."

            doc = types.BufferedInputFile(content.encode("utf-8"), filename="catalog_kursov.txt")
            await message.answer_document(
                document=doc,
                caption=f"📚 <b>Полный перечень курсов ({len(courses)} шт.)</b>\n\nФайл прикреплен выше.",
                parse_mode=ParseMode.HTML
            )

    # 5. ИНСТРУКЦИЯ
    @dp.message(F.text.in_({"ℹ️ Как сделать заказ", "/help"}))
    async def help_cmd(message: types.Message):
        await record_user(message.from_user)
        await message.answer(
            "🛒 <b>Как сделать заказ:</b>\n\n"
            "1️⃣ Нажмите <b>«📚 Каталог курсов»</b> или выберите номер в канале.\n"
            "2️⃣ Отправьте в этот чат номера курсов через запятую (например: <code>1, 4, 12</code>).\n"
            "3️⃣ Бот рассчитает сумму со скидкой и выдаст актуальные реквизиты.\n"
            "4️⃣ Оплатите и отправьте фото/скриншот чека прямо сюда.\n"
            "5️⃣ Ссылки поступят моментально после проверки чека!",
            parse_mode=ParseMode.HTML
        )

    # 6. УПРАВЛЕНИЕ СКИДКАМИ
    @dp.message(F.text.in_({"🏷 Скидки и акции", "🎁 Акции и скидки", "/promo"}))[span_41](start_span)[span_41](end_span)
    async def promo_control(message: types.Message):
        cfg = await get_promo_config()
        is_admin = (message.from_user.id == ADMIN_ID)[span_42](start_span)[span_42](end_span)

        if not is_admin:
            if cfg["active"]:
                d_msg = f" до {cfg['until']}" if cfg['until'] else ""
                await message.answer(
                    f"🎁 <b>Действующая акция:</b>\n\n"
                    f"Скидка <b>{cfg['percent']}%</b> на все заказы от <b>{cfg['min_sum']} руб.</b>{d_msg}!\n\n"
                    f"Скидка применяется автоматически при заказе.",
                    parse_mode=ParseMode.HTML
                )
            else:
                await message.answer("ℹ️ В данный момент спец-акций нет, действуют базовые цены из каталога.")
            return

        status = "🟢 ВКЛЮЧЕНА" if cfg["active"] else "🔴 ВЫКЛЮЧЕНА[span_43](start_span)"[span_43](end_span)
        date_info = f"\nДействует до: {cfg['until']}" if cfg["until"] else ""

        kb = InlineKeyboardBuilder()
        if cfg["active"]:
            kb.button(text="🔴 Выключить скидку", callback_data="promo_toggle_off")
        else:
            kb.button(text="🟢 Включить 20% от 1000₽", callback_data="promo_toggle_on")
        kb.adjust(1)

        await message.answer(
            f"📊 <b>[{bot_name}] Управление скидками:</b>\n\n"
            f"Статус: <b>{status}</b>\n"
            f"Размер: <b>{cfg['percent']}%</b>\n"
            f"Порог: от <b>{cfg['min_sum']} руб.</b>{date_info}\n\n"
            f"<i>Переключайте скидку кнопкой ниже в 1 клик:</i>",
            parse_mode=ParseMode.HTML,
            reply_markup=kb.as_markup()
        )

    @dp.callback_query(F.data.startswith("promo_toggle_"))
    async def promo_toggle_cb(callback: types.CallbackQuery):
        if callback.from_user.id != ADMIN_ID:[span_44](start_span)[span_44](end_span)
            return
        act = callback.data.split("_")[2]
        async with aiosqlite.connect(db_path) as db:
            if act == "off":
                await db.execute("UPDATE settings SET val_text = '0' WHERE key = 'promo_active'")
                await db.commit()
                await callback.answer("Скидка выключена")
            else:
                await db.execute("UPDATE settings SET val_text = '1' WHERE key = 'promo_active'")
                await db.execute("UPDATE settings SET val_text = '20' WHERE key = 'promo_percent'")
                await db.execute("UPDATE settings SET val_text = '1000' WHERE key = 'promo_min_sum'")
                await db.commit()
                await callback.answer("Скидка 20% включена")

        cfg = await get_promo_config()
        status = "🟢 ВКЛЮЧЕНА" if cfg["active"] else "🔴 ВЫКЛЮЧЕНА[span_45](start_span)"[span_45](end_span)
        kb = InlineKeyboardBuilder()
        if cfg["active"]:
            kb.button(text="🔴 Выключить скидку", callback_data="promo_toggle_off")
        else:
            kb.button(text="🟢 Включить 20% от 1000₽", callback_data="promo_toggle_on")
        kb.adjust(1)

        await callback.message.edit_text(
            f"📊 <b>[{bot_name}] Управление скидками:</b>\n\n"
            f"Статус: <b>{status}</b>\n"
            f"Размер: <b>{cfg['percent']}%</b>\n"
            f"Порог: от <b>{cfg['min_sum']} руб.</b>\n\n"
            f"<i>Переключайте скидку кнопкой ниже в 1 клик:</i>",
            parse_mode=ParseMode.HTML,
            reply_markup=kb.as_markup()
        )

    # 7. СИНХРОНИЗАЦИЯ ТАБЛИЦЫ
    @dp.message(F.text.in_({"🔄 Обновить курсы", "/sync"}))
    async def sync_cmd(message: types.Message):
        if message.from_user.id != ADMIN_ID:[span_46](start_span)[span_46](end_span)
            return
        count = await sync_courses_from_sheets()[span_47](start_span)[span_47](end_span)
        await message.answer(f"✅ [{bot_name}] База обновлена из Google Таблицы: <b>{count} курсов</b>.", parse_mode=ParseMode.HTML)[span_48](start_span)[span_48](end_span)

    # 8. СТАТИСТИКА БАЗЫ
    @dp.message(F.text == "📊 Статистика базы")
    async def stats_cmd(message: types.Message):
        if message.from_user.id != ADMIN_ID:[span_49](start_span)[span_49](end_span)
            return
        async with aiosqlite.connect(db_path) as db:
            async with db.execute("SELECT COUNT(*) FROM users") as cur:
                users_count = (await cur.fetchone())[0]
            async with db.execute("SELECT COUNT(*) FROM courses") as cur:
                courses_count = (await cur.fetchone())[0]
            async with db.execute("SELECT COUNT(*), COALESCE(SUM(total_price), 0) FROM orders WHERE status = 'paid'") as cur:
                p_row = await cur.fetchone()
                paid_orders, paid_sum = p_row[0], p_row[1]
            async with db.execute("SELECT COUNT(*) FROM orders WHERE status = 'pending'") as cur:
                pending_orders = (await cur.fetchone())[0]

        await message.answer(
            f"📊 <b>Статистика [{bot_name}]:</b>\n\n"
            f"👥 Пользователей в базе: <b>{users_count}</b>\n"
            f"📚 Курсов в наличии: <b>{courses_count}</b>\n\n"
            f"💰 Оплаченных заказов: <b>{paid_orders}</b> (на <b>{paid_sum} руб.</b>)\n"
            f"⏳ Заказов ожидает проверки: <b>{pending_orders}</b>\n\n"
            f"👉 <i>Чтобы посмотреть список людей по именам, нажмите кнопку <b>«👥 Список клиентов»</b></i>",
            parse_mode=ParseMode.HTML
        )

    # 9. РАССЫЛКА
    @dp.message(F.text.in_({"📢 Сделать рассылку", "/broadcast"}))
    async def broadcast_start(message: types.Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID:[span_50](start_span)[span_50](end_span)
            return
        await state.set_state(BroadcastFSM.waiting_for_message)
        kb = InlineKeyboardBuilder()
        kb.button(text="❌ Отмена", callback_data="cancel_broadcast")
        await message.answer(
            "📢 <b>Режим создания рассылки</b>\n\n"
            "Пришлите боту сообщение для рассылки:\n"
            "• Текст со ссылкой на новую группу\n"
            "• Фото или картинку с описанием\n"
            "• Готовый пересланный пост из канала\n\n"
            "<i>Если передумали — нажмите кнопку «Отмена» ниже.</i>",
            parse_mode=ParseMode.HTML,
            reply_markup=kb.as_markup()
        )

    @dp.message(BroadcastFSM.waiting_for_message)
    async def broadcast_incoming(message: types.Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID:[span_51](start_span)[span_51](end_span)
            return
        if message.text in ["/cancel", "❌ Отмена", "Отмена"]:
            await state.clear()[span_52](start_span)[span_52](end_span)
            await message.answer("❌ Рассылка отменена.", reply_markup=get_admin_kb())
            return

        async with aiosqlite.connect(db_path) as db:
            async with db.execute("SELECT COUNT(*) FROM users") as cur:
                count = (await cur.fetchone())[0]

        await state.update_data(broadcast_msg_id=message.message_id, broadcast_chat_id=message.chat.id)

        kb = InlineKeyboardBuilder()
        kb.button(text=f"🚀 Отправить ({count} чел.)", callback_data="confirm_broadcast")
        kb.button(text="❌ Отмена", callback_data="cancel_broadcast")
        kb.adjust(1, 1)

        await message.reply(
            f"📋 <b>Сообщение принято!</b>\n\n"
            f"👥 Адресатов в базе: <b>{count}</b>\n\n"
            f"Нажмите кнопку для подтверждения отправки:",
            parse_mode=ParseMode.HTML,
            reply_markup=kb.as_markup()
        )

    @dp.callback_query(F.data == "confirm_broadcast")
    async def broadcast_confirm(callback: types.CallbackQuery, state: FSMContext):
        if callback.from_user.id != ADMIN_ID:[span_53](start_span)[span_53](end_span)
            return
        data = await state.get_data()[span_54](start_span)[span_54](end_span)
        b_mid = data.get("broadcast_msg_id")
        b_cid = data.get("broadcast_chat_id")
        await state.clear()[span_55](start_span)[span_55](end_span)

        if not b_mid or not b_cid:
            await callback.message.edit_text("⚠️ Ошибка: сообщение не найдено.")
            return

        async with aiosqlite.connect(db_path) as db:
            async with db.execute("SELECT user_id FROM users") as cur:
                users = await cur.fetchall()

        if not users:
            await callback.message.edit_text("ℹ️ База пользователей пуста.")
            return

        status_msg = await callback.message.edit_text(f"⏳ Рассылка запущена на {len(users)} пользователей...")
        success, blocked, errors = 0, 0, 0

        for row in users:
            u_id = row[0]
            try:
                await bot.copy_message(chat_id=u_id, from_chat_id=b_cid, message_id=b_mid)
                success += 1
            except TelegramForbiddenError:
                blocked += 1
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
            f"👥 Всего адресатов: <b>{len(users)}</b>\n"
            f"✅ Успешно доставлено: <b>{success}</b>\n"
            f"🚫 Заблокировали бота: <b>{blocked}</b>\n"
            f"⚠️ Ошибок: <b>{errors}</b>",
            parse_mode=ParseMode.HTML
        )
        await callback.answer("Готово!")

    # 10. ОБРАБОТКА ВВОДА НОМЕРОВ КУРСОВ ПОКУПАТЕЛЕМ
    @dp.message(
        ~StateFilter(BroadcastFSM.waiting_for_message, PaymentFSM.waiting_for_title, PaymentFSM.waiting_for_details),
        F.text,
        ~F.text.startswith("/")
    )
    async def process_articles(message: types.Message, state: FSMContext):
        if message.text in MENU_BUTTONS:
            return
        await record_user(message.from_user)

        raw_ids = re.findall(r"\b\d+\b", message.text)[span_56](start_span)[span_56](end_span)
        if not raw_ids:
            await message.answer("Пожалуйста, укажите номера курсов цифрами (например: <code>1, 2, 5</code>).", parse_mode=ParseMode.HTML)[span_57](start_span)[span_57](end_span)
            return

        unique_ids = list(dict.fromkeys([int(i) for i in raw_ids]))[span_58](start_span)[span_58](end_span)
        placeholders = ",".join("?" for _ in unique_ids)[span_59](start_span)[span_59](end_span)

        async with aiosqlite.connect(db_path) as db:[span_60](start_span)[span_60](end_span)
            async with db.execute(f"SELECT id, title, price FROM courses WHERE id IN ({placeholders})", unique_ids) as cur:[span_61](start_span)[span_61](end_span)
                found_courses = await cur.fetchall()[span_62](start_span)[span_62](end_span)

        if not found_courses:
            await message.answer("❌ Ни один курс по указанным номерам не найден.")[span_63](start_span)[span_63](end_span)
            return

        promo = await get_promo_config()
        raw_total = sum(c[2] for c in found_courses)[span_64](start_span)[span_64](end_span)
        final_total = raw_total
        discount_info = f"💰 <b>Итого к оплате:</b> {final_total} руб.[span_65](start_span)"[span_65](end_span)

        if promo["active"] and raw_total >= promo["min_sum"]:
            discount = int(raw_total * (promo["percent"] / 100))[span_66](start_span)[span_66](end_span)
            final_total = raw_total - discount[span_67](start_span)[span_67](end_span)
            discount_info = (
                f"🏷 Сумма: {raw_total} руб.\n[span_68](start_span)"[span_68](end_span)
                f"🔥 Скидка {promo['percent']}%: -{discount} руб.\n"
                f"💰 <b>Итого к оплате:</b> {final_total} руб.[span_69](start_span)"[span_69](end_span)
            )

        saved_ids = ",".join(str(c[0]) for c in found_courses)[span_70](start_span)[span_70](end_span)
        async with aiosqlite.connect(db_path) as db:[span_71](start_span)[span_71](end_span)
            cursor = await db.execute([span_72](start_span)[span_72](end_span)
                "INSERT INTO orders (user_id, course_ids, total_price) VALUES (?, ?, ?)",[span_73](start_span)[span_73](end_span)
                (message.from_user.id, saved_ids, final_total)[span_74](start_span)[span_74](end_span)
            )
            order_id = cursor.lastrowid[span_75](start_span)[span_75](end_span)
            await db.commit()[span_76](start_span)[span_76](end_span)

        await state.update_data(order_id=order_id)[span_77](start_span)[span_77](end_span)
        await state.set_state(OrderFSM.waiting_for_receipt)[span_78](start_span)[span_78](end_span)

        summary = "\n".join([f"• №{c[0]} {html.escape(str(c[1]))} — {c[2]} руб." for c in found_courses[:10]])
        if len(found_courses) > 10:
            summary += f"\n...и еще {len(found_courses) - 10} позиций[span_79](start_span)"[span_79](end_span)

        payment_details_text = await get_payment_details_text()

        await message.answer(
            f"🧾 <b>Заказ #{order_id} сформирован</b>\n\n[span_80](start_span)"[span_80](end_span)
            f"{summary}\n\n"
            f"Выбрано: <b>{len(found_courses)} шт.</b>\n[span_81](start_span)"[span_81](end_span)
            f"{discount_info}\n\n"
            f"{payment_details_text}\n\n"
            f"📸 <b>Пришлите скриншот чека или PDF в этот чат.</b>",
            parse_mode=ParseMode.HTML
        )

    # 11. ПРИЕМ ЧЕКОВ
    @dp.message(
        ~StateFilter(BroadcastFSM.waiting_for_message, PaymentFSM.waiting_for_title, PaymentFSM.waiting_for_details),
        F.photo | F.document[span_82](start_span)[span_82](end_span)
    )
    async def process_receipt(message: types.Message, state: FSMContext):
        data = await state.get_data()[span_83](start_span)[span_83](end_span)
        order_id = data.get("order_id")[span_84](start_span)[span_84](end_span)

        async with aiosqlite.connect(db_path) as db:[span_85](start_span)[span_85](end_span)
            if not order_id:
                async with db.execute(
                    "SELECT id FROM orders WHERE user_id = ? AND status = 'pending' ORDER BY id DESC LIMIT 1",
                    (message.from_user.id,)
                ) as cur:
                    last_order = await cur.fetchone()
                    if last_order:
                        order_id = last_order[0]

            if not order_id:
                await message.answer("⚠️ Не найден активный заказ. Отправьте номера курсов заново.")
                return

            async with db.execute("SELECT course_ids, total_price FROM orders WHERE id = ?", (order_id,)) as cur:[span_86](start_span)[span_86](end_span)
                ord_data = await cur.fetchone()[span_87](start_span)[span_87](end_span)
                if not ord_data:
                    return
                c_ids = [int(x) for x in ord_data[0].split(",")][span_88](start_span)[span_88](end_span)
                order_price = ord_data[1]

            placeholders = ",".join("?" for _ in c_ids)[span_89](start_span)[span_89](end_span)
            async with db.execute(f"SELECT id, title FROM courses WHERE id IN ({placeholders})", c_ids) as cur:[span_90](start_span)[span_90](end_span)
                c_info = await cur.fetchall()[span_91](start_span)[span_91](end_span)

        kb = InlineKeyboardBuilder()[span_92](start_span)[span_92](end_span)
        kb.button(text="✅ Подтвердить", callback_data=f"adm_appr_{order_id}")
        kb.button(text="❌ Отклонить", callback_data=f"adm_rejc_{order_id}")
        kb.adjust(2)[span_93](start_span)[span_93](end_span)

        user = f"@{message.from_user.username}" if message.from_user.username else f"ID: {message.from_user.id}[span_94](start_span)"[span_94](end_span)
        courses_brief = "\n".join([f"• №{c[0]} {html.escape(str(c[1]))}" for c in c_info[:7]])
        if len(c_info) > 7:
            courses_brief += f"\n...и еще {len(c_info) - 7} шт.[span_95](start_span)"[span_95](end_span)

        caption_text = (
            f"🧾 <b>[{bot_name}] Оплата заказа #{order_id}</b>\n"
            f"👤 Клиент: {html.escape(user)}\n"
            f"💰 Сумма: <b>{order_price} руб.</b>\n\n"
            f"📚 <b>Курсы ({len(c_info)} шт.):</b>\n"
            f"{courses_brief}"
        )

        try:
            if message.photo:[span_96](start_span)[span_96](end_span)
                await bot.send_photo([span_97](start_span)[span_97](end_span)
                    chat_id=ADMIN_ID,[span_98](start_span)[span_98](end_span)
                    photo=message.photo[-1].file_id,[span_99](start_span)[span_99](end_span)
                    caption=caption_text,
                    reply_markup=kb.as_markup(),[span_100](start_span)[span_100](end_span)
                    parse_mode=ParseMode.HTML
                )
            elif message.document:[span_101](start_span)[span_101](end_span)
                await bot.send_document([span_102](start_span)[span_102](end_span)
                    chat_id=ADMIN_ID,[span_103](start_span)[span_103](end_span)
                    document=message.document.file_id,[span_104](start_span)[span_104](end_span)
                    caption=caption_text,
                    reply_markup=kb.as_markup(),[span_105](start_span)[span_105](end_span)
                    parse_mode=ParseMode.HTML
                )
            await message.answer("✅ Чек отправлен на проверку. Ссылки придут сразу после одобрения.")
            await state.clear()[span_106](start_span)[span_106](end_span)
        except Exception as e:
            logging.error(f"[{bot_name}] Ошибка пересылки чека: {e}")

    # 12. ОДОБРЕНИЕ И ОТКЛОНЕНИЕ ЧЕКОВ
    @dp.callback_query(F.data.startswith("adm_appr_"))
    async def admin_approve(callback: types.CallbackQuery):
        if callback.from_user.id != ADMIN_ID:[span_107](start_span)[span_107](end_span)
            return
        order_id = int(callback.data.split("_")[2])

        async with aiosqlite.connect(db_path) as db:[span_108](start_span)[span_108](end_span)
            async with db.execute("SELECT user_id, course_ids, status FROM orders WHERE id = ?", (order_id,)) as cur:[span_109](start_span)[span_109](end_span)
                order = await cur.fetchone()[span_110](start_span)[span_110](end_span)

            if not order or order[2] == "paid":[span_111](start_span)[span_111](end_span)
                await callback.answer("Заказ уже обработан.")[span_112](start_span)[span_112](end_span)
                return[span_113](start_span)[span_113](end_span)

            user_id, ids = order[0], [int(x) for x in order[1].split(",")][span_114](start_span)[span_114](end_span)
            placeholders = ",".join("?" for _ in ids)[span_115](start_span)[span_115](end_span)
            async with db.execute(f"SELECT title, link FROM courses WHERE id IN ({placeholders})", ids) as cur:[span_116](start_span)[span_116](end_span)
                courses = await cur.fetchall()[span_117](start_span)[span_117](end_span)

            await db.execute("UPDATE orders SET status = 'paid' WHERE id = ?", (order_id,))[span_118](start_span)[span_118](end_span)
            await db.commit()[span_119](start_span)[span_119](end_span)

        try:
            if len(courses) > 10:[span_120](start_span)[span_120](end_span)
                content = f"ВАШИ КУРСЫ (ЗАКАЗ #{order_id})\n" + "=" * 35 + "\n\n[span_121](start_span)"[span_121](end_span)
                content += "\n\n".join([f"{c[0]}:\n{c[1]}" for c in courses])[span_122](start_span)[span_122](end_span)
                doc = types.BufferedInputFile(content.encode("utf-8"), filename=f"Order_{order_id}.txt")[span_123](start_span)[span_123](end_span)
                await bot.send_document([span_124](start_span)[span_124](end_span)
                    chat_id=user_id,[span_125](start_span)[span_125](end_span)
                    document=doc,[span_126](start_span)[span_126](end_span)
                    caption="🎉 Оплата подтверждена! Ваши курсы в файле выше.[span_127](start_span)"[span_127](end_span)
                )
            else:
                lines = [f"🎉 <b>Оплата подтверждена! Заказ #{order_id}:</b>\n"]
                lines.extend([f"• <b>{html.escape(str(c[0]))}</b>\n👉 {str(c[1]).strip()}" for c in courses])
                await bot.send_message(chat_id=user_id, text="\n\n".join(lines), parse_mode=ParseMode.HTML)
        except Exception as e:
            logging.error(f"[{bot_name}] Ошибка отправки ссылок: {e}")

        base_caption = callback.message.caption or "[span_128](start_span)"[span_128](end_span)
        try:
            await callback.message.edit_caption([span_129](start_span)[span_129](end_span)
                caption=base_caption + "\n\n🟢 <b>ОДОБРЕНО</b>",
                reply_markup=None,[span_130](start_span)[span_130](end_span)
                parse_mode=ParseMode.HTML
            )
        except Exception:
            pass
        await callback.answer("Доступ отправлен")[span_131](start_span)[span_131](end_span)

    @dp.callback_query(F.data.startswith("adm_rejc_"))
    async def admin_reject(callback: types.CallbackQuery):
        if callback.from_user.id != ADMIN_ID:[span_132](start_span)[span_132](end_span)
            return
        order_id = int(callback.data.split("_")[2])
        async with aiosqlite.connect(db_path) as db:[span_133](start_span)[span_133](end_span)
            async with db.execute("SELECT user_id FROM orders WHERE id = ?", (order_id,)) as cur:[span_134](start_span)[span_134](end_span)
                order = await cur.fetchone()[span_135](start_span)[span_135](end_span)
        if order:
            try:
                await bot.send_message(chat_id=order[0], text=f"❌ Оплата по заказу #{order_id} отклонена.")[span_136](start_span)[span_136](end_span)
            except Exception:
                pass
        base_caption = callback.message.caption or "[span_137](start_span)"[span_137](end_span)
        try:
            await callback.message.edit_caption([span_138](start_span)[span_138](end_span)
                caption=base_caption + "\n\n🔴 <b>ОТКЛОНЕНО</b>",
                reply_markup=None,[span_139](start_span)[span_139](end_span)
                parse_mode=ParseMode.HTML
            )
        except Exception:
            pass
        await callback.answer("Отклонено")[span_140](start_span)[span_140](end_span)

    return bot, dp, init_db

async def main():
    logging.basicConfig(level=logging.INFO)[span_141](start_span)[span_141](end_span)
    tasks = []
    for cfg in BOT_CONFIGS:
        bot_inst, dp_inst, init_fn = create_bot_app(cfg)
        await init_fn()
        tasks.append(dp_inst.start_polling(bot_inst))

    logging.info("Оба бота успешно инициализированы и запущены!")
    await asyncio.gather(*tasks)

if __name__ == "__main__":
    asyncio.run(main())[span_142](start_span)[span_142](end_span)
