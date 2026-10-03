import os

import aiosqlite

# Auf Railway: DB_PATH=/data/clanbot.db (Pfad des Volumes)
DB_PATH = os.getenv("DB_PATH", "clanbot.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    guild_id INTEGER, key TEXT, value TEXT,
    PRIMARY KEY (guild_id, key)
);
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER, name TEXT COLLATE NOCASE,
    stock INTEGER, description TEXT,
    UNIQUE (guild_id, name)
);
CREATE TABLE IF NOT EXISTS loans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER, user_id INTEGER, item_id INTEGER,
    amount INTEGER, days INTEGER, status TEXT,
    requested_at TEXT, due_at TEXT, returned_at TEXT,
    note TEXT, message_id INTEGER, reminded INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS temp_voice (
    channel_id INTEGER PRIMARY KEY, guild_id INTEGER, owner_id INTEGER
);
"""


async def init():
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.executescript(SCHEMA)
        await conn.commit()


async def execute(query, params=()):
    async with aiosqlite.connect(DB_PATH) as conn:
        cur = await conn.execute(query, params)
        await conn.commit()
        return cur.lastrowid


async def fetchall(query, params=()):
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        cur = await conn.execute(query, params)
        return await cur.fetchall()


async def fetchone(query, params=()):
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        cur = await conn.execute(query, params)
        return await cur.fetchone()


async def get_setting(guild_id, key):
    row = await fetchone("SELECT value FROM settings WHERE guild_id=? AND key=?", (guild_id, key))
    return row["value"] if row else None


async def set_setting(guild_id, key, value):
    await execute(
        "INSERT INTO settings (guild_id, key, value) VALUES (?, ?, ?) "
        "ON CONFLICT(guild_id, key) DO UPDATE SET value=excluded.value",
        (guild_id, key, str(value)),
    )
