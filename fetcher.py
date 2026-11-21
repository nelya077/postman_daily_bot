import asyncio
import calendar
import html
import re

import feedparser

from sources import CATALOG


def _clean(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def _parse(url: str):
    return feedparser.parse(url)


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
