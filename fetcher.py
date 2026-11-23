import asyncio
import calendar
import html
import logging
import re
import socket
from urllib.parse import quote_plus

import feedparser

from sources import CATALOG

log = logging.getLogger(__name__)
socket.setdefaulttimeout(20)  # feedparser сам таймаут не задаёт


def _clean(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def _parse(url: str):
    feed = feedparser.parse(url)
    if not feed.entries:
        log.warning("Лента пуста или недоступна: %s (%s)", url, getattr(feed, "bozo_exception", "нет ошибки"))
    return feed


async def fetch_source(key: str) -> list[dict]:
    name, url = CATALOG[key]
    feed = await asyncio.to_thread(_parse, url)
    items = []
    for e in feed.entries:
        published = getattr(e, "published_parsed", None)
        items.append({
            "title": _clean(e.get("title", "")),
            "link": e.get("link", ""),
            "summary": _clean(e.get("summary", "")),
            "ts": calendar.timegm(published) if published else 0,
            "source": name,
        })
    return items


async def search_google_news(query: str) -> list[dict]:
    """Поиск свежих новостей (за последние 2 дня) по теме через RSS Google Новостей."""
    url = (
        "https://news.google.com/rss/search?q="
        + quote_plus(f"{query} when:2d")
        + "&hl=ru&gl=RU&ceid=RU:ru"
    )
    feed = await asyncio.to_thread(_parse, url)
    items = []
    for e in feed.entries:
        title = _clean(e.get("title", ""))
        source = _clean(e.get("source", {}).get("title", ""))
        suffix = f" - {source}"
        if source and title.endswith(suffix):  # заголовки вида «Заголовок - Издание»
            title = title[: -len(suffix)]
        published = getattr(e, "published_parsed", None)
        items.append({
            "title": title,
            "link": e.get("link", ""),
            "summary": "",
            "ts": calendar.timegm(published) if published else 0,
            "source": source or "Google Новости",
        })
    return items
