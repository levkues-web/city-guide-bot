import asyncio
import logging
import os
import csv
from typing import Optional, List, Tuple

import aiosqlite
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import (Message, CallbackQuery, InlineKeyboardMarkup, KeyboardButton,
                           ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineQuery, InlineQueryResultArticle, InputTextMessageContent,
                           InlineKeyboardButton)

from aiogram.utils.keyboard import InlineKeyboardBuilder
from dotenv import load_dotenv

from utils.haversine import haversine_km

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID", "0"))
DEFAULT_CITY = os.getenv("DEFAULT_CITY", "Batumi")
DB_PATH = os.path.join(os.path.dirname(__file__), "db", "guide.db")
I18N_DIR = os.path.join(os.path.dirname(__file__), "i18n")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("city_guide_pro")

router = Router()

CATEGORIES = ["Питание", "Достопримечательности", "Музеи", "События", "Парки", "Спортзалы"]

# --- i18n helpers ---
import json
with open(os.path.join(I18N_DIR, "ru.json"), "r", encoding="utf-8") as f:
    RU = json.load(f)
with open(os.path.join(I18N_DIR, "en.json"), "r", encoding="utf-8") as f:
    EN = json.load(f)

def t(user_id: int, key: str, **kwargs) -> str:
    # fetch lang from user_prefs
    lang = "ru"
    try:
        lang = user_prefs_cache.get(user_id, {}).get("lang", "ru")
    except:
        pass
    dct = RU if lang == "ru" else EN
    return dct.get(key, key).format(**kwargs)

# --- DB helpers ---
async def get_db():
    return await aiosqlite.connect(DB_PATH)

async def list_cities() -> List[str]:
    async with await get_db() as db:
        rows = await db.execute_fetchall("SELECT name FROM cities ORDER BY name")
        return [r[0] for r in rows]

async def get_city_id(name: str) -> Optional[int]:
    async with await get_db() as db:
        row = await db.execute_fetchone("SELECT id FROM cities WHERE name=?", (name,))
        return row[0] if row else None

def apply_filters_clause():
    return " AND ( (p.kids_friendly>=? ) AND (p.dog_friendly>=? ) AND ( (?=0) OR (p.price_level=?)) ) "

async def search_places(city: Optional[str], q: str, prefs: dict, limit: int = 10):
    sql = """
        SELECT p.id, p.name, p.category, p.description, p.address, p.hours, p.rating, p.lat, p.lon, p.url, c.name,
               p.kids_friendly, p.dog_friendly, p.price_level
        FROM places p
        JOIN cities c ON c.id = p.city_id
        WHERE (p.name LIKE ? OR p.description LIKE ?)
    """
    args = [f"%{q}%", f"%{q}%"]
    if city:
        sql += " AND c.name = ?"
        args.append(city)
    # filters
    sql += apply_filters_clause()
    args += [prefs.get("kids_friendly", 0), prefs.get("dog_friendly", 0), prefs.get("price_level", 0), prefs.get("price_level", 0)]
    sql += " ORDER BY p.rating DESC LIMIT ?"
    args.append(limit)
    async with await get_db() as db:
        rows = await db.execute_fetchall(sql, args)
        return rows

async def places_by_category(city: str, category: str, prefs: dict, limit: int = 10):
    sql = """
        SELECT p.id, p.name, p.category, p.description, p.address, p.hours, p.rating, p.lat, p.lon, p.url,
               p.kids_friendly, p.dog_friendly, p.price_level
        FROM places p
        JOIN cities c ON c.id = p.city_id
        WHERE c.name=? AND p.category=?
    """
    args = [city, category]
    sql += apply_filters_clause()
    args += [prefs.get("kids_friendly", 0), prefs.get("dog_friendly", 0), prefs.get("price_level", 0), prefs.get("price_level", 0)]
    sql += " ORDER BY p.rating DESC LIMIT ?"
    args.append(limit)
    async with await get_db() as db:
        rows = await db.execute_fetchall(sql, args)
        return rows

async def random_place(city: str, prefs: dict):
    sql = """
        SELECT p.id, p.name, p.category, p.description, p.address, p.hours, p.rating, p.lat, p.lon, p.url,
               p.kids_friendly, p.dog_friendly, p.price_level
        FROM places p
        JOIN cities c ON c.id = p.city_id
        WHERE c.name=?
    """
    args = [city]
    sql += apply_filters_clause()
    args += [prefs.get("kids_friendly", 0), prefs.get("dog_friendly", 0), prefs.get("price_level", 0), prefs.get("price_level", 0)]
    sql += " ORDER BY RANDOM() LIMIT 1"
    async with await get_db() as db:
        row = await db.execute_fetchone(sql, args)
        return row

async def nearby_places(lat: float, lon: float, prefs: dict, radius_km: float = 3.0, limit: int = 10):
    sql = """
        SELECT p.id, p.name, p.category, p.description, p.address, p.hours, p.rating, p.lat, p.lon, p.url, c.name,
               p.kids_friendly, p.dog_friendly, p.price_level
        FROM places p
        JOIN cities c ON c.id = p.city_id
    """
    results = []
    async with await get_db() as db:
        async with db.execute(sql) as cursor:
            async for pid, name, cat, descr, addr, hours, rating, plat, plon, url, city_name, kids, dog, price in cursor:
                # filter
                if kids < prefs.get("kids_friendly", 0): continue
                if dog < prefs.get("dog_friendly", 0): continue
                desired_price = prefs.get("price_level", 0)
                if desired_price and price != desired_price: continue
                d = haversine_km(lat, lon, plat, plon)
                if d <= radius_km:
                    results.append((d, pid, name, cat, descr, addr, hours, rating, plat, plon, url, city_name, kids, dog, price))
    results.sort(key=lambda x: x[0])
    return results[:limit]

async def get_place_by_id(pid: int):
    async with await get_db() as db:
        row = await db.execute_fetchone("""
            SELECT id, name, category, description, address, hours, rating, lat, lon, url, kids_friendly, dog_friendly, price_level
            FROM places WHERE id=?
        """, (pid,))
        return row

async def get_user_prefs(user_id: int) -> dict:
    async with await get_db() as db:
        row = await db.execute_fetchone("SELECT lang, kids_friendly, dog_friendly, price_level FROM user_prefs WHERE user_id=?", (user_id,))
        if not row:
            await db.execute("INSERT OR IGNORE INTO user_prefs(user_id) VALUES(?)", (user_id,))
            await db.commit()
            return {"lang":"ru", "kids_friendly":0, "dog_friendly":0, "price_level":0}
        lang, kids, dog, price = row
        return {"lang":lang, "kids_friendly":kids, "dog_friendly":dog, "price_level":price}

async def set_user_lang(user_id: int, lang: str):
    async with await get_db() as db:
        await db.execute("INSERT INTO user_prefs(user_id, lang) VALUES(?, ?) ON CONFLICT(user_id) DO UPDATE SET lang=excluded.lang", (user_id, lang))
        await db.commit()

async def toggle_pref(user_id: int, field: str, cycle_vals: Tuple[int, ...]=(0,1)):
    async with await get_db() as db:
        row = await db.execute_fetchone(f"SELECT {field} FROM user_prefs WHERE user_id=?", (user_id,))
        if not row:
            cur = cycle_vals[0]
        else:
            cur = row[0]
        idx = (cycle_vals.index(cur) + 1) % len(cycle_vals)
        nxt = cycle_vals[idx]
        await db.execute(f"INSERT INTO user_prefs(user_id,{field}) VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET {field}=excluded.{field}", (user_id, nxt))
        await db.commit()
        return nxt

async def set_price(user_id: int, level: int):
    level = max(0, min(4, level))
    async with await get_db() as db:
        await db.execute("INSERT INTO user_prefs(user_id, price_level) VALUES(?, ?) ON CONFLICT(user_id) DO UPDATE SET price_level=excluded.price_level", (user_id, level))
        await db.commit()

async def add_favorite(user_id: int, place_id: int):
    async with await get_db() as db:
        await db.execute("INSERT OR IGNORE INTO favorites(user_id, place_id) VALUES(?,?)", (user_id, place_id))
        await db.commit()

async def remove_favorite(user_id: int, place_id: int):
    async with await get_db() as db:
        await db.execute("DELETE FROM favorites WHERE user_id=? AND place_id=?", (user_id, place_id))
        await db.commit()

async def list_favorites(user_id: int):
    async with await get_db() as db:
        rows = await db.execute_fetchall("""
            SELECT p.id, p.name, p.category, p.description, p.address, p.hours, p.rating, p.lat, p.lon, p.url
            FROM favorites f JOIN places p ON p.id=f.place_id
            WHERE f.user_id=? ORDER BY p.rating DESC
        """, (user_id,))
        return rows

user_city: dict[int, str] = {}
user_prefs_cache: dict[int, dict] = {}

def place_text(i18n_user_id, name, cat, descr, addr, hours, rating, lat, lon, url, city_name=None, kids=0, dog=0, price=0):
    gmaps = f"https://maps.google.com/?q={lat},{lon}"
    parts = [f"📍 <b>{name}</b> — {cat}",
             f"⭐️ {rating:.1f}" if rating else "⭐️ —",
             f"{descr}" if descr else "",
             f"🏠 {addr}" if addr else "",
             f"🕒 {hours}" if hours else ""]
    tagline = []
    if kids: tagline.append("👶")
    if dog: tagline.append("🐶")
    if price: tagline.append("💵" + "₁₂₃₄"[price-1])
    if tagline:
        parts.append(" ".join(tagline))
    parts.append(f"🔗 <a href='{gmaps}'>{t(i18n_user_id,'open_maps')}</a>")
    if url:
        parts.append(f"🌐 <a href='{url}'>{t(i18n_user_id,'website')}</a>")
    if city_name:
        parts.append(f"🏙 {city_name}")
    return "\n".join([p for p in parts if p])

def categories_kb(city: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for cat in CATEGORIES:
        kb.button(text=cat, callback_data=f"cat:{city}:{cat}")
    kb.adjust(2)
    return kb.as_markup()

def cities_kb(cities: List[str]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for c in cities:
        kb.button(text=c, callback_data=f"city:{c}")
    kb.adjust(2)
    return kb.as_markup()

def fav_kb(place_id: int, is_fav: bool):
    kb = InlineKeyboardBuilder()
    if is_fav:
        kb.button(text="💔 Remove", callback_data=f"fav:rem:{place_id}")
    else:
        kb.button(text="❤️ Add", callback_data=f"fav:add:{place_id}")
    return kb.as_markup()

def filters_kb(user_id: int):
    prefs = user_prefs_cache.get(user_id, {"kids_friendly":0, "dog_friendly":0, "price_level":0})
    kids_val = t(user_id, "kids_on") if prefs.get("kids_friendly") else t(user_id, "kids_off")
    dog_val = t(user_id, "dog_on") if prefs.get("dog_friendly") else t(user_id, "dog_off")
    price = prefs.get("price_level", 0)
    price_txt = t(user_id, "price_label", level=price if price else 0)
    kb = InlineKeyboardBuilder()
    kb.button(text=f"👶 {kids_val}", callback_data="filt:kids")
    kb.button(text=f"🐶 {dog_val}", callback_data="filt:dog")
    for lvl in range(0,5):
        label = "💵 " + (str(lvl) if lvl else "0")
        kb.button(text=label, callback_data=f"filt:price:{lvl}")
    kb.adjust(2,3)
    return kb.as_markup()

# --- Handlers ---
@router.message(CommandStart())
async def cmd_start(message: Message):
    user_city[message.from_user.id] = DEFAULT_CITY
    prefs = await get_user_prefs(message.from_user.id)
    user_prefs_cache[message.from_user.id] = prefs
    await message.answer(t(message.from_user.id, "welcome"))

@router.message(Command("city"))
async def cmd_city(message: Message):
    cities = await list_cities()
    await message.answer(t(message.from_user.id, "choose_city"), reply_markup=cities_kb(cities))

@router.callback_query(F.data.startswith("city:"))
async def on_city_selected(cb: CallbackQuery):
    city = cb.data.split(":", 1)[1]
    user_city[cb.from_user.id] = city
    await cb.message.edit_text(t(cb.from_user.id, "city_set", city=city), reply_markup=categories_kb(city))

@router.callback_query(F.data.startswith("cat:"))
async def on_category(cb: CallbackQuery):
    _, city, category = cb.data.split(":", 2)
    prefs = user_prefs_cache.get(cb.from_user.id, await get_user_prefs(cb.from_user.id))
    rows = await places_by_category(city, category, prefs, limit=10)
    if not rows:
        await cb.answer(t(cb.from_user.id, "nothing"), show_alert=True)
        return
    text = t(cb.from_user.id, "category_top", category=category, city=city) + "\n\n"
    chunks = []
    for r in rows:
        (pid, name, cat, descr, addr, hours, rating, lat, lon, url, kids, dog, price) = r
        chunks.append(place_text(cb.from_user.id, name, cat, descr, addr, hours, rating, lat, lon, url, city, kids, dog, price))
    await cb.message.edit_text(text + "\n\n".join(chunks), disable_web_page_preview=True)

@router.message(Command("search"))
async def cmd_search(message: Message, command: CommandObject):
    q = (command.args or "").strip()
    if not q:
        await message.answer(t(message.from_user.id, "search_usage"))
        return
    prefs = user_prefs_cache.get(message.from_user.id, await get_user_prefs(message.from_user.id))
    city = user_city.get(message.from_user.id)
    rows = await search_places(city, q, prefs, limit=10)
    if not rows:
        await message.answer(t(message.from_user.id, "not_found"))
        return
    chunks = []
    for (pid, name, cat, descr, addr, hours, rating, lat, lon, url, city_name, kids, dog, price) in rows:
        chunks.append(place_text(message.from_user.id, name, cat, descr, addr, hours, rating, lat, lon, url, city_name, kids, dog, price))
    await message.answer("\n\n".join(chunks), disable_web_page_preview=True)

@router.message(Command("random"))
async def cmd_random(message: Message):
    city = user_city.get(message.from_user.id, DEFAULT_CITY)
    prefs = user_prefs_cache.get(message.from_user.id, await get_user_prefs(message.from_user.id))
    row = await random_place(city, prefs)
    if not row:
        await message.answer(t(message.from_user.id, "random_empty"))
        return
    (pid, name, cat, descr, addr, hours, rating, lat, lon, url, kids, dog, price) = row
    text = place_text(message.from_user.id, name, cat, descr, addr, hours, rating, lat, lon, url, city, kids, dog, price)
    # Check favorite
    async with await get_db() as db:
        fav = await db.execute_fetchone("SELECT 1 FROM favorites WHERE user_id=? AND place_id=?", (message.from_user.id, pid))
        is_fav = bool(fav)
    await message.answer(text, disable_web_page_preview=True, reply_markup=fav_kb(pid, is_fav))

@router.message(Command("nearby"))
async def cmd_nearby(message: Message):
    kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📍 Поделиться геолокацией", request_location=True)]],
                             resize_keyboard=True, one_time_keyboard=True)
    await message.answer(t(message.from_user.id, "nearby_prompt", km=3), reply_markup=kb)

@router.message(F.location)
async def on_location(message: Message):
    lat = message.location.latitude
    lon = message.location.longitude
    prefs = user_prefs_cache.get(message.from_user.id, await get_user_prefs(message.from_user.id))
    results = await nearby_places(lat, lon, prefs, radius_km=3.0, limit=10)
    if not results:
        await message.answer(t(message.from_user.id, "nearby_empty"))
        return
    chunks = []
    for d, pid, name, cat, descr, addr, hours, rating, plat, plon, url, city_name, kids, dog, price in results:
        txt = place_text(message.from_user.id, name, cat, descr, addr, hours, rating, plat, plon, url, city_name, kids, dog, price)
        chunks.append(f"~{d:.2f} км\n{txt}")
    await message.answer("\n\n".join(chunks), disable_web_page_preview=True, reply_markup=ReplyKeyboardRemove())

# --- Favorites buttons ---
@router.callback_query(F.data.startswith("fav:"))
async def on_fav(cb: CallbackQuery):
    _, action, pid = cb.data.split(":")
    pid = int(pid)
    if action == "add":
        await add_favorite(cb.from_user.id, pid)
        await cb.answer(t(cb.from_user.id, "fav_added"))
    else:
        await remove_favorite(cb.from_user.id, pid)
        await cb.answer(t(cb.from_user.id, "fav_removed"))

@router.message(Command("fav"))
async def cmd_fav(message: Message):
    rows = await list_favorites(message.from_user.id)
    if not rows:
        await message.answer(t(message.from_user.id, "favorites_empty"))
        return
    chunks = []
    for (pid, name, cat, descr, addr, hours, rating, lat, lon, url) in rows:
        chunks.append(place_text(message.from_user.id, name, cat, descr, addr, hours, rating, lat, lon, url))
    await message.answer(t(message.from_user.id, "favorites_title") + "\n\n" + "\n\n".join(chunks), disable_web_page_preview=True)

# --- Filters ---
@router.message(Command("filters"))
async def cmd_filters(message: Message):
    prefs = user_prefs_cache.get(message.from_user.id, await get_user_prefs(message.from_user.id))
    user_prefs_cache[message.from_user.id] = prefs
    kids_txt = t(message.from_user.id, "kids_on") if prefs.get("kids_friendly") else t(message.from_user.id, "kids_off")
    dog_txt = t(message.from_user.id, "dog_on") if prefs.get("dog_friendly") else t(message.from_user.id, "dog_off")
    price = prefs.get("price_level", 0)
    await message.answer(t(message.from_user.id, "filters_title", kids=kids_txt, dog=dog_txt, price=price),
                         reply_markup=filters_kb(message.from_user.id))

@router.callback_query(F.data.startswith("filt:"))
async def on_filter(cb: CallbackQuery):
    parts = cb.data.split(":")
    if parts[1] == "kids":
        val = await toggle_pref(cb.from_user.id, "kids_friendly", (0,1))
    elif parts[1] == "dog":
        val = await toggle_pref(cb.from_user.id, "dog_friendly", (0,1))
    elif parts[1] == "price":
        level = int(parts[2])
        await set_price(cb.from_user.id, level)
    prefs = await get_user_prefs(cb.from_user.id)
    user_prefs_cache[cb.from_user.id] = prefs
    await cb.message.edit_reply_markup(reply_markup=filters_kb(cb.from_user.id))
    await cb.answer("OK")

# --- Language ---
@router.message(Command("lang"))
async def cmd_lang(message: Message):
    kb = InlineKeyboardBuilder()
    kb.button(text="RU", callback_data="lang:ru")
    kb.button(text="EN", callback_data="lang:en")
    kb.adjust(2)
    await message.answer(t(message.from_user.id, "set_lang"), reply_markup=kb.as_markup())

@router.callback_query(F.data.startswith("lang:"))
async def on_lang(cb: CallbackQuery):
    lang = cb.data.split(":")[1]
    await set_user_lang(cb.from_user.id, lang)
    user_prefs_cache[cb.from_user.id] = await get_user_prefs(cb.from_user.id)
    await cb.answer(t(cb.from_user.id, "lang_set", lang=lang))
    await cb.message.delete()

# --- CSV import (by sending a CSV document) ---
@router.message(Command("import_csv"))
async def cmd_import_hint(message: Message):
    await message.answer(t(message.from_user.id, "import_hint"))

@router.message(F.document & (F.document.mime_type == "text/csv"))
async def on_csv_upload(message: Message):
    try:
        file = await message.bot.get_file(message.document.file_id)
        tmp_path = os.path.join(os.path.dirname(__file__), "db", "upload.csv")
        await message.bot.download_file(file.file_path, tmp_path)
        count = 0
        async with aiosqlite.connect(DB_PATH) as db:
            with open(tmp_path, newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    city = row.get("city","").strip()
                    if not city: continue
                    # ensure city exists
                    await db.execute("INSERT OR IGNORE INTO cities(name) VALUES(?)", (city,))
                    c_row = await db.execute_fetchone("SELECT id FROM cities WHERE name=?", (city,))
                    cid = c_row[0]
                    def as_float(x, default=0.0):
                        try: return float(str(x).strip())
                        except: return default
                    def as_int(x, default=0):
                        try:
                            v = int(float(str(x).strip()))
                            return v
                        except: return default
                    kids = as_int(row.get("kids_friendly",0))
                    dog = as_int(row.get("dog_friendly",0))
                    price = as_int(row.get("price_level",0))
                    await db.execute("""
                        INSERT INTO places(city_id, name, category, lat, lon, description, address, hours, rating, url, kids_friendly, dog_friendly, price_level)
                        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """, (cid, row.get("name",""), row.get("category",""), as_float(row.get("lat")), as_float(row.get("lon")),
                          row.get("description",""), row.get("address",""), row.get("hours",""), as_float(row.get("rating",0)),
                          row.get("url",""), kids, dog, price))
                    count += 1
            await db.commit()
        await message.answer(t(message.from_user.id, "import_ok", count=count))
    except Exception as e:
        await message.answer(t(message.from_user.id, "import_fail", error=str(e)))

# --- Inline mode ---
@router.inline_query()
async def inline_query_handler(inline_query: InlineQuery):
    q = (inline_query.query or "").strip()
    user_id = inline_query.from_user.id
    prefs = user_prefs_cache.get(user_id, await get_user_prefs(user_id))
    city = user_city.get(user_id, DEFAULT_CITY)
    if not q:
        q = ""  # empty → show random or top?
    rows = await search_places(city, q, prefs, limit=20)
    results = []
    for (pid, name, cat, descr, addr, hours, rating, lat, lon, url, city_name, kids, dog, price) in rows:
        text = place_text(user_id, name, cat, descr, addr, hours, rating, lat, lon, url, city_name, kids, dog, price)
        results.append(InlineQueryResultArticle(
            id=str(pid),
            title=name,
            description=f"{cat} • ⭐ {rating:.1f}" if rating else cat,
            input_message_content=InputTextMessageContent(message_text=text, parse_mode="HTML"),
        ))
    await inline_query.answer(results, cache_time=1, is_personal=True)

async def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is not set. On Replit add it in Secrets.")
    bot = Bot(BOT_TOKEN, parse_mode="HTML")
    dp = Dispatcher()
    dp.include_router(router)
    try:
        await dp.start_polling(bot, allowed_updates=["message", "callback_query", "inline_query"])
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
