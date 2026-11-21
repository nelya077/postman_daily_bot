import asyncio
import html
import logging
import time

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError

import db
from fetcher import fetch_source
from sources import CATALOG

log = logging.getLogger(__name__)


def selected_sources(user: dict) -> list[str]:
    keys = [k for k in user["sources"].split(",") if k in CATALOG]
    return keys or list(CATALOG)  # пусто = все источники


def parse_topics(user: dict) -> list[str]:
    return [t.strip().lower() for t in user["topics"].split(",") if t.strip()]


async def build_digest(chat_id: int, user: dict) -> list[dict]:
    keys = selected_sources(user)
    results = await asyncio.gather(*(fetch_source(k) for k in keys), return_exceptions=True)
    items = []
    for key, res in zip(keys, results):
        if isinstance(res, Exception):
            log.warning("Источник %s недоступен: %s", key, res)
            continue
        items.extend(res)

    topics = parse_topics(user)
    if topics:
        items = [i for i in items if any(t in f"{i['title']} {i['summary']}".lower() for t in topics)]

    sent = await db.get_sent(chat_id, [i["link"] for i in items if i["link"]])
    items = [i for i in items if i["link"] and i["link"] not in sent]

    seen, unique = set(), []
    for i in sorted(items, key=lambda x: x["ts"], reverse=True):
        key = i["title"].lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(i)
    return unique[: user["limit_n"]]


def format_digest(items: list[dict]) -> str:
    lines = ["📬 <b>Почтальон: подборка новостей</b>", ""]
    for i in items:
        link = html.escape(i["link"], quote=True)
        lines.append(f'• <a href="{link}">{html.escape(i["title"])}</a> <i>({html.escape(i["source"])})</i>')
        if i["summary"]:
            short = i["summary"][:140] + ("…" if len(i["summary"]) > 140 else "")
            lines.append(html.escape(short))
        lines.append("")
    return "\n".join(lines).strip()


async def send_digest(bot: Bot, chat_id: int, user: dict, manual: bool = False) -> bool:
    items = await build_digest(chat_id, user)
    if not items:
        if manual:
            await bot.send_message(chat_id, "Новых новостей по вашим фильтрам пока нет.")
        return False
    try:
        await bot.send_message(chat_id, format_digest(items), disable_web_page_preview=True)
    except TelegramForbiddenError:
        log.info("Пользователь %s заблокировал бота", chat_id)
        return False
    await db.mark_sent(chat_id, [i["link"] for i in items])
    return True


async def tick(bot: Bot):
    """Периодическая проверка: кому пора отправить дайджест."""
    now = time.time()
    for user in await db.all_users():
        if now - user["last_sent"] < user["every_hours"] * 3600:
            continue
        try:
            await send_digest(bot, user["chat_id"], user)
        except Exception:
            log.exception("Ошибка рассылки для %s", user["chat_id"])
        await db.update_user(user["chat_id"], last_sent=now)
