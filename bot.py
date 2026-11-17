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
