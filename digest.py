import asyncio
import html
import logging
import os
import re
import time

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError

import db
import llm
from fetcher import fetch_source, search_google_news
from sources import CATALOG
from topics import expand

log = logging.getLogger(__name__)

POOL_SIZE = 60  # сколько свежих новостей отдаём модели на отбор


def selected_sources(user: dict) -> list[str]:
    keys = [k for k in user["sources"].split(",") if k in CATALOG]
    return keys or list(CATALOG)  # пусто = все источники


def user_topics(user: dict) -> list[str]:
    return [t.strip() for t in user["topics"].split(",") if t.strip()]


async def _collect(chat_id: int, user: dict) -> list[dict]:
    """Свежие, ещё не отправленные новости из выбранных источников, без дублей."""
    keys = selected_sources(user)
    results = await asyncio.gather(*(fetch_source(k) for k in keys), return_exceptions=True)
    items = []
    for key, res in zip(keys, results):
        if isinstance(res, Exception):
            log.warning("Источник %s недоступен: %s", key, res)
            continue
        items.extend(res)

    sent = await db.get_sent(chat_id, [i["link"] for i in items if i["link"]])
    items = [i for i in items if i["link"] and i["link"] not in sent]

    seen, unique = set(), []
    for i in sorted(items, key=lambda x: x["ts"], reverse=True):
        key = i["title"].lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(i)
    return unique


def _keyword_filter(items: list[dict], topics: list[str]) -> list[dict]:
    terms = expand(topics)
    if not terms:
        return items
    patterns = [re.compile(r"\b" + re.escape(t), re.IGNORECASE) for t in terms]
    return [i for i in items if any(p.search(f"{i['title']} {i['summary']}") for p in patterns)]


async def build_digest(chat_id: int, user: dict) -> list[dict]:
    topics = user_topics(user)
    limit = user["limit_n"]
    items = await _collect(chat_id, user)

    chosen = None
    if llm.enabled():
        chosen = await llm.pick_and_summarize(items[:POOL_SIZE], topics, limit)
    if chosen is None:  # LLM выключена или упала: обычный поиск по ключевым словам
        chosen = _keyword_filter(items, topics)[:limit]

    # Если лент не хватило, добираем новости по темам из поиска Google Новостей
    if os.getenv("WEB_SEARCH_IN_DIGEST", "1") == "1" and topics and len(chosen) < limit:
        extra = await search_news(topics, limit - len(chosen))
        known = {i["link"] for i in chosen}
        extra = [e for e in extra if e["link"] not in known]
        sent = await db.get_sent(chat_id, [e["link"] for e in extra])
        chosen += [e for e in extra if e["link"] not in sent]
    return chosen[:limit]


async def search_news(topics: list[str], limit: int) -> list[dict]:
    """Ищет свежие новости по темам в интернете (Google Новости); LLM выбирает лучшие и пересказывает."""
    results = await asyncio.gather(*(search_google_news(t) for t in topics[:3]), return_exceptions=True)
    items = []
    for topic, res in zip(topics[:3], results):
        if isinstance(res, Exception):
            log.warning("Поиск по теме %r не удался: %s", topic, res)
            continue
        items.extend(res)

    seen, pool = set(), []
    for i in sorted(items, key=lambda x: x["ts"], reverse=True):
        key = i["title"].lower()
        if not i["link"] or key in seen:
            continue
        seen.add(key)
        pool.append(i)
    pool = pool[:POOL_SIZE]

    chosen = None
    if llm.enabled():
        chosen = await llm.pick_and_summarize(pool, topics, limit)
    return chosen if chosen is not None else pool[:limit]


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
