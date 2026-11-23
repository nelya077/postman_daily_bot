import asyncio
import calendar
import html
import logging
import re
from urllib.parse import quote_plus

import aiohttp
import feedparser

import tls
from sources import CATALOG

log = logging.getLogger(__name__)

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; PostmanDailyBot/1.0)"}


def _clean(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


async def _download(url: str) -> bytes | None:
    """Скачивает ленту через aiohttp с проверенным SSL-контекстом (urllib в feedparser на macOS падает на сертификатах)."""
    timeout = aiohttp.ClientTimeout(total=20)
    try:
        async with aiohttp.ClientSession(timeout=timeout, headers=HEADERS) as session:
            async with session.get(url, ssl=tls.context()) as resp:
                if resp.status != 200:
                    log.warning("Лента недоступна: %s (HTTP %s)", url, resp.status)
                    return None
                return await resp.read()
    except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as e:
        if "CERTIFICATE_VERIFY_FAILED" in str(e):
            log.warning(
                "Лента недоступна: %s (ошибка сертификата). Для российских сайтов нужен сертификат Минцифры: "
                "укажите GIGACHAT_CA_BUNDLE в .env", url,
            )
        else:
            log.warning("Лента недоступна: %s (%s)", url, e)
        return None


async def _load_feed(url: str):
    content = await _download(url)
    if content is None:
        return None
    feed = await asyncio.to_thread(feedparser.parse, content)
    if not feed.entries:
        log.warning("Лента пуста: %s (%s)", url, getattr(feed, "bozo_exception", "нет ошибки"))
    return feed


async def fetch_source(key: str) -> list[dict]:
    name, url = CATALOG[key]
    feed = await _load_feed(url)
    if feed is None:
        return []
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
    feed = await _load_feed(url)
    if feed is None:
        return []
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
