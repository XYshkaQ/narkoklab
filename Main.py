import asyncio
import random
import time
import os
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart
from aiogram.fsm.storage.memory import MemoryStorage

from database import (
    init_db, get_user, get_inventory, get_upgrades,
    update_user, update_inventory, update_upgrades,
    get_leaderboard, add_xp
)

TOKEN = os.getenv("BOT_TOKEN", "ВСТАВЬ_ТОКЕН_СЮДА")

bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# ──────────────────────────────────────────
# КОНСТАНТЫ ИГРЫ
# ──────────────────────────────────────────

GOODS = {
    "synth":    {"name": "🧪 Синтетика",   "base": 800},
    "organics": {"name": "🌿 Органика",     "base": 400},
    "crystals": {"name": "💎 Кристаллы",   "base": 1500},
    "psycho":   {"name": "🍄 Психоделики", "base": 600},
    "meds":     {"name": "💊 Медикаменты", "base": 300},
}

UPGRADES_INFO = {
    "lab": {
        "name": "🔬 Лаборатория",
        "desc": "Производит Синтетику каждую минуту",
        "costs": [10000, 30000, 80000, 200000],
        "currency": "clean",
    },
    "club": {
        "name": "🎰 Ночной Клуб",
        "desc": "Капает чистый кэш каждую минуту",
        "costs": [15000, 50000, 120000, 300000],
        "currency": "clean",
    },
    "guard": {
        "name": "🛡 Охрана",
        "desc": "Снижает риск при контрабанде до 5%",
        "costs": [8000],
        "currency": "dirty",
    },
    "laundry_lvl": {
        "name": "🧼 Улучш. Прачечной",
        "desc": "Снижает комиссию: 30% → 20% → 10%",
        "costs": [20000, 60000],
        "currency": "clean",
    },
}

DELIVERY_POINTS = [
    {"name": "📦 Ближний склад",   "reward": 500,  "risk": 0.10, "xp": 20},
    {"name": "🚢 Портовая зона",   "reward": 1500, "risk": 0.20, "xp": 50},
    {"name": "✈️ Аэропорт",        "reward": 3000, "risk": 0.35, "xp": 100},
    {"name": "🌐 Зарубежный рынок","reward": 6000, "risk": 0.50, "xp": 200},
]

# ──────────────────────────────────────────
# ДИНАМИЧЕСКИЕ ЦЕНЫ
# ──────────────────────────────────────────

_prices_cache: dict = {}
_prices_ts: float = 0

def get_market_prices() -> dict:
    global _prices_cache, _prices_ts
    now = time.time()
    if now - _prices_ts > 300:  # обновляем каждые 5 минут
        _prices_cache = {
            k: int(v["base"] * random.uniform(0.7, 1.5))
            for k, v in GOODS.items()
        }
        _prices_ts = now
    return _prices_cache

# ──────────────────────────────────────────
# КЛАВИАТУРЫ
# ──────────────────────────────────────────

def main_menu_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👤 Профиль", callback_data="profile"),
         InlineKeyboardButton(text="🛒 Чёрный рынок", callback_data="market")],
        [InlineKeyboardButton(text="🚗 Контрабанда", callback_data="delivery"),
         InlineKeyboardButton(text="🧼 Прачечная", callback_data="laundry")],
        [InlineKeyboardButton(text="🚀 Улучшения", callback_data="upgrades"),
         InlineKeyboardButton(text="🏆 Лидерборд", callback_data="leaderboard")],
    ])

def back_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 В меню", callback_data="menu")]
    ])

def market_kb(mode="buy"):
    prices = get_market_prices()
    rows = []
    for key, info in GOODS.items():
        price = prices[key]
        label = f"{info['name']} — ${price:,}"
        rows.append([InlineKeyboardButton(text=label, callback_data=f"noop"),
                     InlineKeyboardButton(text="🛍 Купить", callback_data=f"buy_{key}"),
                     InlineKeyboardButton(text="💰 Продать", callback_data=f"sell_{key}")])
    rows.append([InlineKeyboardButton(text="🔙 В меню", callback_data="menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def delivery_kb(has_goods: bool):
    rows = []
    if has_goods:
        for i, dp in enumerate(DELIVERY_POINTS):
            rows.append([InlineKeyboardButton(
                text=f"{dp['name']} | +${dp['reward']:,} | риск {int(dp['risk']*100)}%",
                callback_data=f"deliver_{i}"
            )])
    else:
        rows.append([InlineKeyboardButton(text="⚠️ Нет товаров для доставки", callback_data="noop")])
    rows.append([InlineKeyboardButton(text="🔙 В меню", callback_data="menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def upgrades_kb(upg: dict):
    rows = []
    for key, info in UPGRADES_INFO.items():
        lvl = upg.get(key, 0)
        costs = info["costs"]
        if lvl >= len(costs):
            rows.append([InlineKeyboardButton(
                text=f"{info['name']} ✅ МАКС (ур.{lvl})", callback_data="noop"
            )])
        else:
            cur_cost = costs[lvl]
            cur = "💵" if info["currency"] == "dirty" else "🏦"
            rows.append([InlineKeyboardButton(
                text=f"{info['name']} ур.{lvl} → {cur}${cur_cost:,}",
                callback_data=f"buy_upg_{key}"
            )])
    rows.append([InlineKeyboardButton(text="🔙 В меню", callback_data="menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def laundry_kb(user: dict, upg: dict):
    dirty = user["dirty_cash"]
    laundry_lvl = upg.get("laundry_lvl", 0)
    commission = [0.30, 0.20, 0.10][laundry_lvl] if laundry_lvl < 3 else 0.10
    clean_get = int(dirty * (1 - commission))
    rows = [
        [InlineKeyboardButton(
            text=f"💸 Отмыть всё: ${dirty:,} → ${clean_get:,} (ком. {int(commission*100)}%)",
            callback_data="do_laundry"
        )],
        [InlineKeyboardButton(text="🔙 В меню", callback_data="menu")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)

# ──────────────────────────────────────────
# ПАССИВНЫЙ ДОХОД (фоновая задача)
# ──────────────────────────────────────────

async def passive_income_loop():
    while True:
        await asyncio.sleep(60)
        async with __import__("aiosqlite").connect("game.db") as db:
            db.row_factory = __import__("aiosqlite").Row
            async with db.execute("SELECT user_id FROM users") as cur:
                users = await cur.fetchall()
            for row in users:
                uid = row["user_id"]
                upg = await get_upgrades(uid)
                lab_lvl = upg.get("lab", 0)
                club_lvl = upg.get("club", 0)
                if lab_lvl > 0:
                    # Лаб производит синтетику: 1/2/4/6 ед в минуту
                    production = [1, 2, 4, 6][lab_lvl - 1] if lab_lvl <= 4 else 6
                    inv = await get_inventory(uid)
                    await update_inventory(uid, synth=inv["synth"] + production)
                if club_lvl > 0:
                    # Клуб даёт чистый кэш: 100/300/700/1500 в минуту
                    income = [100, 300, 700, 1500][club_lvl - 1] if club_lvl <= 4 else 1500
                    user = await get_user(uid)
                    await update_user(uid, clean_cash=user["clean_cash"] + income)

# ──────────────────────────────────────────
# ХЭНДЛЕРЫ
# ──────────────────────────────────────────

@dp.message(CommandStart())
async def cmd_start(msg: Message):
    user = await get_user(msg.from_user.id, msg.from_user.username or msg.from_user.first_name)
    text = (
        f"🎮 <b>Добро пожаловать в Подпольную Империю!</b>\n\n"
        f"Ты начинаешь с $5,000 грязного кэша.\n"
        f"Торгуй на Чёрном рынке, занимайся контрабандой,\n"
        f"отмывай деньги и строй свою империю!\n\n"
        f"🏠 Главное меню:"
    )
    await msg.answer(text, reply_markup=main_menu_kb(), parse_mode="HTML")

@dp.callback_query(F.data == "menu")
async def cb_menu(cb: CallbackQuery):
    await cb.message.edit_text("🏠 <b>Главное меню</b>", reply_markup=main_menu_kb(), parse_mode="HTML")

@dp.callback_query(F.data == "profile")
async def cb_profile(cb: CallbackQuery):
    uid = cb.from_user.id
    user = await get_user(uid, cb.from_user.username or "")
    inv = await get_inventory(uid)
    upg = await get_upgrades(uid)

    inv_text = "\n".join(
        f"  {GOODS[k]['name']}: {inv.get(k,0)} ед."
        for k in GOODS if inv.get(k, 0) > 0
    ) or "  (пусто)"

    upg_text = "\n".join(
        f"  {UPGRADES_INFO[k]['name']}: ур.{upg.get(k,0)}"
        for k in UPGRADES_INFO if upg.get(k, 0) > 0
    ) or "  (нет улучшений)"

    xp_needed = user["level"] * 1000
    text = (
        f"👤 <b>Профиль</b>\n\n"
        f"🎖 Уровень: {user['level']} | XP: {user['xp']}/{xp_needed}\n"
        f"⚡️ Авторитет: {user['authority']}\n\n"
        f"💵 Грязный кэш: <b>${user['dirty_cash']:,}</b>\n"
        f"🏦 Чистый кэш: <b>${user['clean_cash']:,}</b>\n\n"
        f"📦 <b>Инвентарь:</b>\n{inv_text}\n\n"
        f"🚀 <b>Улучшения:</b>\n{upg_text}"
    )
    await cb.message.edit_text(text, reply_markup=back_kb(), parse_mode="HTML")

@dp.callback_query(F.data == "market")
async def cb_market(cb: CallbackQuery):
    prices = get_market_prices()
    lines = [f"{info['name']}: <b>${prices[k]:,}</b>" for k, info in GOODS.items()]
    text = "🛒 <b>Чёрный рынок</b>\nЦены обновляются каждые 5 минут\n\n" + "\n".join(lines)
    await cb.message.edit_text(text, reply_markup=market_kb(), parse_mode="HTML")

@dp.callback_query(F.data.startswith("buy_") & ~F.data.startswith("buy_upg_"))
async def cb_buy(cb: CallbackQuery):
    key = cb.data[4:]
    if key not in GOODS:
        return await cb.answer("Ошибка")
    uid = cb.from_user.id
    user = await get_user(uid)
    price = get_market_prices()[key]
    qty = max(1, user["dirty_cash"] // price)
    if qty == 0 or user["dirty_cash"] < price:
        return await cb.answer("❌ Недостаточно средств!", show_alert=True)
    cost = price * qty
    inv = await get_inventory(uid)
    await update_user(uid, dirty_cash=user["dirty_cash"] - cost)
    await update_inventory(uid, **{key: inv[key] + qty})
    await cb.answer(f"✅ Куплено {qty} ед. {GOODS[key]['name']} за ${cost:,}")

@dp.callback_query(F.data.startswith("sell_"))
async def cb_sell(cb: CallbackQuery):
    key = cb.data[5:]
    if key not in GOODS:
        return await cb.answer("Ошибка")
    uid = cb.from_user.id
    inv = await get_inventory(uid)
    qty = inv.get(key, 0)
    if qty == 0:
        return await cb.answer("❌ Нет товара для продажи!", show_alert=True)
    price = get_market_prices()[key]
    total = price * qty
    user = await get_user(uid)
    await update_user(uid, dirty_cash=user["dirty_cash"] + total)
    await update_inventory(uid, **{key: 0})
    leveled, lvl = await add_xp(uid, qty * 5)
    msg = f"✅ Продано {qty} ед. за ${total:,}"
    if leveled:
        msg += f"\n🎉 Уровень повышен до {lvl}!"
    await cb.answer(msg, show_alert=True)

@dp.callback_query(F.data == "delivery")
async def cb_delivery(cb: CallbackQuery):
    uid = cb.from_user.id
    inv = await get_inventory(uid)
    has_goods = any(inv.get(k, 0) > 0 for k in GOODS)
    text = (
        "🚗 <b>Контрабанда</b>\n"
        "Выбери точку доставки. При провале теряешь весь товар!\n\n"
        "💡 Купи Охрану в Улучшениях, чтобы снизить риск до 5%"
    )
    await cb.message.edit_text(text, reply_markup=delivery_kb(has_goods), parse_mode="HTML")

@dp.callback_query(F.data.startswith("deliver_"))
async def cb_deliver(cb: CallbackQuery):
    idx = int(cb.data.split("_")[1])
    dp_info = DELIVERY_POINTS[idx]
    uid = cb.from_user.id
    user = await get_user(uid)
    inv = await get_inventory(uid)
    upg = await get_upgrades(uid)

    has_goods = any(inv.get(k, 0) > 0 for k in GOODS)
    if not has_goods:
        return await cb.answer("❌ Нет товаров для доставки!", show_alert=True)

    risk = 0.05 if upg.get("guard", 0) > 0 else dp_info["risk"]
    caught = random.random() < risk

    if caught:
        # Теряем весь товар
        await update_inventory(uid, synth=0, organics=0, crystals=0, psycho=0, meds=0)
        await cb.answer("🚔 Попался! Копы изъяли весь товар. Лучше повезёт в следующий раз!", show_alert=True)
    else:
        reward = dp_info["reward"]
        await update_user(uid, dirty_cash=user["dirty_cash"] + reward)
        leveled, lvl = await add_xp(uid, dp_info["xp"])
        msg = f"✅ Доставка успешна! +${reward:,} грязных денег"
        if leveled:
            msg += f"\n🎉 Уровень повышен до {lvl}!"
        await cb.answer(msg, show_alert=True)
    await cb_delivery(cb)

@dp.callback_query(F.data == "laundry")
async def cb_laundry(cb: CallbackQuery):
    uid = cb.from_user.id
    user = await get_user(uid)
    upg = await get_upgrades(uid)
    laundry_lvl = upg.get("laundry_lvl", 0)
    commission = [0.30, 0.20, 0.10][min(laundry_lvl, 2)]
    text = (
        f"🧼 <b>Прачечная</b>\n\n"
        f"Обмен грязного кэша на чистый.\n"
        f"Текущая комиссия: <b>{int(commission*100)}%</b>\n"
        f"Улучши Прачечную, чтобы снизить комиссию.\n\n"
        f"💵 Грязный кэш: ${user['dirty_cash']:,}"
    )
    await cb.message.edit_text(text, reply_markup=laundry_kb(user, upg), parse_mode="HTML")

@dp.callback_query(F.data == "do_laundry")
async def cb_do_laundry(cb: CallbackQuery):
    uid = cb.from_user.id
    user = await get_user(uid)
    upg = await get_upgrades(uid)
    dirty = user["dirty_cash"]
    if dirty <= 0:
        return await cb.answer("❌ Нет грязных денег!", show_alert=True)
    laundry_lvl = upg.get("laundry_lvl", 0)
    commission = [0.30, 0.20, 0.10][min(laundry_lvl, 2)]
    clean_get = int(dirty * (1 - commission))
    await update_user(uid, dirty_cash=0, clean_cash=user["clean_cash"] + clean_get)
    await cb.answer(f"✅ Отмыто! Получено ${clean_get:,} чистых денег", show_alert=True)
    await cb_laundry(cb)

@dp.callback_query(F.data == "upgrades")
async def cb_upgrades(cb: CallbackQuery):
    uid = cb.from_user.id
    upg = await get_upgrades(uid)
    text = (
        "🚀 <b>Улучшения бизнеса</b>\n\n"
        "🔬 Лаборатория — производит Синтетику каждую мин.\n"
        "🎰 Ночной клуб — чистый кэш каждую мин.\n"
        "🛡 Охрана — снижает риск при доставке до 5%\n"
        "🧼 Улучш. Прачечной — снижает комиссию\n\n"
        "💡 Лаб и Клуб покупаются за <b>чистый</b> кэш.\n"
        "🛡 Охрана — за <b>грязный</b>."
    )
    await cb.message.edit_text(text, reply_markup=upgrades_kb(upg), parse_mode="HTML")

@dp.callback_query(F.data.startswith("buy_upg_"))
async def cb_buy_upgrade(cb: CallbackQuery):
    key = cb.data[8:]
    if key not in UPGRADES_INFO:
        return await cb.answer("Ошибка")
    uid = cb.from_user.id
    user = await get_user(uid)
    upg = await get_upgrades(uid)
    info = UPGRADES_INFO[key]
    lvl = upg.get(key, 0)

    if lvl >= len(info["costs"]):
        return await cb.answer("✅ Уже максимальный уровень!", show_alert=True)

    cost = info["costs"][lvl]
    if info["currency"] == "clean":
        balance = user["clean_cash"]
        if balance < cost:
            return await cb.answer(f"❌ Нужно ${cost:,} чистых денег! У тебя: ${balance:,}", show_alert=True)
        await update_user(uid, clean_cash=balance - cost)
    else:
        balance = user["dirty_cash"]
        if balance < cost:
            return await cb.answer(f"❌ Нужно ${cost:,} грязных денег! У тебя: ${balance:,}", show_alert=True)
        await update_user(uid, dirty_cash=balance - cost)

    await update_upgrades(uid, **{key: lvl + 1})
    await cb.answer(f"✅ {info['name']} улучшена до ур.{lvl+1}!", show_alert=True)
    await cb_upgrades(cb)

@dp.callback_query(F.data == "leaderboard")
async def cb_leaderboard(cb: CallbackQuery):
    top = await get_leaderboard()
    lines = []
    medals = ["🥇", "🥈", "🥉"] + ["🔹"] * 7
    for i, p in enumerate(top):
        name = p["username"] or "Аноним"
        total = p["total"]
        lines.append(f"{medals[i]} {name} — Ур.{p['level']} — ${total:,}")
    text = "🏆 <b>Топ-10 Империй</b>\n\n" + ("\n".join(lines) if lines else "Пока никого нет")
    await cb.message.edit_text(text, reply_markup=back_kb(), parse_mode="HTML")

@dp.callback_query(F.data == "noop")
async def cb_noop(cb: CallbackQuery):
    await cb.answer()

# ──────────────────────────────────────────
# ЗАПУСК
# ──────────────────────────────────────────

async def main():
    await init_db()
    asyncio.create_task(passive_income_loop())
    print("✅ Бот запущен!")
    await dp.start_polling(bot, skip_updates=True)

if __name__ == "__main__":
    asyncio.run(main())

