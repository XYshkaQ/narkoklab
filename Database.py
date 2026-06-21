import aiosqlite
import asyncio
from datetime import datetime

DB_PATH = "game.db"

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                level INTEGER DEFAULT 1,
                xp INTEGER DEFAULT 0,
                dirty_cash INTEGER DEFAULT 5000,
                clean_cash INTEGER DEFAULT 0,
                authority INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                last_passive INTEGER DEFAULT 0
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS inventory (
                user_id INTEGER PRIMARY KEY,
                synth INTEGER DEFAULT 0,
                organics INTEGER DEFAULT 0,
                crystals INTEGER DEFAULT 0,
                psycho INTEGER DEFAULT 0,
                meds INTEGER DEFAULT 0
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS upgrades (
                user_id INTEGER PRIMARY KEY,
                lab INTEGER DEFAULT 0,
                club INTEGER DEFAULT 0,
                guard INTEGER DEFAULT 0,
                laundry_lvl INTEGER DEFAULT 0
            )
        """)
        await db.commit()

async def get_user(user_id: int, username: str = ""):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users WHERE user_id=?", (user_id,)) as cur:
            row = await cur.fetchone()
        if not row:
            await db.execute(
                "INSERT INTO users (user_id, username) VALUES (?,?)", (user_id, username)
            )
            await db.execute("INSERT INTO inventory (user_id) VALUES (?)", (user_id,))
            await db.execute("INSERT INTO upgrades (user_id) VALUES (?)", (user_id,))
            await db.commit()
            async with db.execute("SELECT * FROM users WHERE user_id=?", (user_id,)) as cur:
                row = await cur.fetchone()
        return dict(row)

async def get_inventory(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM inventory WHERE user_id=?", (user_id,)) as cur:
            row = await cur.fetchone()
        return dict(row) if row else {}

async def get_upgrades(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM upgrades WHERE user_id=?", (user_id,)) as cur:
            row = await cur.fetchone()
        return dict(row) if row else {}

async def update_user(user_id: int, **kwargs):
    if not kwargs:
        return
    fields = ", ".join(f"{k}=?" for k in kwargs)
    values = list(kwargs.values()) + [user_id]
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(f"UPDATE users SET {fields} WHERE user_id=?", values)
        await db.commit()

async def update_inventory(user_id: int, **kwargs):
    if not kwargs:
        return
    fields = ", ".join(f"{k}=?" for k in kwargs)
    values = list(kwargs.values()) + [user_id]
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(f"UPDATE inventory SET {fields} WHERE user_id=?", values)
        await db.commit()

async def update_upgrades(user_id: int, **kwargs):
    if not kwargs:
        return
    fields = ", ".join(f"{k}=?" for k in kwargs)
    values = list(kwargs.values()) + [user_id]
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(f"UPDATE upgrades SET {fields} WHERE user_id=?", values)
        await db.commit()

async def get_leaderboard():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT username, level, dirty_cash+clean_cash as total, authority "
            "FROM users ORDER BY total DESC LIMIT 10"
        ) as cur:
            rows = await cur.fetchall()
        return [dict(r) for r in rows]

async def add_xp(user_id: int, amount: int):
    user = await get_user(user_id)
    new_xp = user["xp"] + amount
    level = user["level"]
    xp_needed = level * 1000
    leveled_up = False
    while new_xp >= xp_needed:
        new_xp -= xp_needed
        level += 1
        xp_needed = level * 1000
        leveled_up = True
    await update_user(user_id, xp=new_xp, level=level, authority=user["authority"]+amount//10)
    return leveled_up, level

