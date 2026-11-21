import time

import aiosqlite

DB_PATH = "pochtalon.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    chat_id INTEGER PRIMARY KEY,
    topics TEXT NOT NULL DEFAULT '',
    sources TEXT NOT NULL DEFAULT '',
    limit_n INTEGER NOT NULL DEFAULT 5,
    every_hours INTEGER NOT NULL DEFAULT 24,
    last_sent REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS sent_news (
    chat_id INTEGER NOT NULL,
    link TEXT NOT NULL,
    PRIMARY KEY (chat_id, link)
);
"""

ALLOWED = {"topics", "sources", "limit_n", "every_hours", "last_sent"}


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(SCHEMA)
        await db.commit()


async def user_exists(chat_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT 1 FROM users WHERE chat_id = ?", (chat_id,))
        return await cur.fetchone() is not None


async def get_user(chat_id: int) -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        # last_sent = сейчас: первый авто-дайджест придёт через every_hours, а не сразу
        await db.execute(
            "INSERT OR IGNORE INTO users (chat_id, last_sent) VALUES (?, ?)",
            (chat_id, time.time()),
        )
        await db.commit()
        cur = await db.execute("SELECT * FROM users WHERE chat_id = ?", (chat_id,))
        return dict(await cur.fetchone())


async def update_user(chat_id: int, **fields):
    fields = {k: v for k, v in fields.items() if k in ALLOWED}
    if not fields:
        return
    sets = ", ".join(f"{k} = ?" for k in fields)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(f"UPDATE users SET {sets} WHERE chat_id = ?", (*fields.values(), chat_id))
        await db.commit()


async def all_users() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM users")
        return [dict(r) for r in await cur.fetchall()]


async def get_sent(chat_id: int, links: list[str]) -> set[str]:
    if not links:
        return set()
    marks = ",".join("?" * len(links))
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            f"SELECT link FROM sent_news WHERE chat_id = ? AND link IN ({marks})",
            (chat_id, *links),
        )
        return {r[0] for r in await cur.fetchall()}


async def mark_sent(chat_id: int, links: list[str]):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executemany(
            "INSERT OR IGNORE INTO sent_news (chat_id, link) VALUES (?, ?)",
            [(chat_id, l) for l in links],
        )
        await db.commit()
