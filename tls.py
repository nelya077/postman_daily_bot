"""Общий SSL-контекст: корневые сертификаты certifi + корневой сертификат НУЦ Минцифры.
Нужен, потому что стандартный Python на macOS часто не знает корневых сертификатов,
а российские сайты и GigaChat используют сертификат Минцифры."""
import logging
import os
import ssl

import certifi

log = logging.getLogger(__name__)

_ctx: ssl.SSLContext | None = None


def context() -> ssl.SSLContext:
    global _ctx
    if _ctx is None:
        ctx = ssl.create_default_context(cafile=certifi.where())
        ca = os.getenv("GIGACHAT_CA_BUNDLE", "").strip()
        if ca:
            path = os.path.expanduser(ca)
            if not os.path.isabs(path):  # относительный путь считаем от папки проекта
                path = os.path.join(os.path.dirname(os.path.abspath(__file__)), path)
            try:
                ctx.load_verify_locations(cafile=path)
            except (OSError, ssl.SSLError):
                log.error("Не удалось прочитать сертификат %s. Проверьте GIGACHAT_CA_BUNDLE в .env", path)
        _ctx = ctx
    return _ctx
