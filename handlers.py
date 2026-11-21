from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

import db
from digest import parse_topics, selected_sources, send_digest
from sources import CATALOG

router = Router()

HELP = (
    "📬 <b>Почтальон</b> собирает новости по вашим фильтрам.\n\n"
    "/topics слово1, слово2 — тематика (ключевые слова; «-» чтобы сбросить)\n"
    "/sources — выбрать источники\n"
    "/limit 5 — сколько новостей в дайджесте (1–20)\n"
    "/every 24 — как часто присылать, в часах (1–168)\n"
    "/settings — текущие настройки\n"
    "/digest — получить подборку сейчас"
)


def sources_kb(selected: list[str]):
    b = InlineKeyboardBuilder()
    for key, (name, _) in CATALOG.items():
        mark = "✅" if key in selected else "▫️"
        b.button(text=f"{mark} {name}", callback_data=f"src:{key}")
    b.adjust(2)
    return b.as_markup()


@router.message(CommandStart())
async def start(m: Message):
    await db.get_user(m.chat.id)
    await m.answer(HELP)


@router.message(Command("settings"))
async def settings(m: Message):
    u = await db.get_user(m.chat.id)
    topics = ", ".join(parse_topics(u)) or "все темы"
    names = ", ".join(CATALOG[k][0] for k in selected_sources(u))
    await m.answer(
        f"<b>Настройки</b>\nТематика: {topics}\nИсточники: {names}\n"
        f"Новостей в дайджесте: {u['limit_n']}\nЧастота: раз в {u['every_hours']} ч"
    )


@router.message(Command("topics"))
async def topics(m: Message, command: CommandObject):
    if not command.args:
        await m.answer("Укажите слова через запятую, например: /topics ai, python, экономика\nСбросить: /topics -")
        return
    raw = command.args.strip()
    value = "" if raw == "-" else ", ".join(t.strip() for t in raw.split(",") if t.strip())
    await db.update_user(m.chat.id, topics=value)
    await m.answer(f"Тематика: {value or 'все темы'}")


@router.message(Command("sources"))
async def sources(m: Message):
    u = await db.get_user(m.chat.id)
    await m.answer("Выберите источники:", reply_markup=sources_kb(selected_sources(u)))


@router.callback_query(F.data.startswith("src:"))
async def toggle_source(cb: CallbackQuery):
    key = cb.data.split(":", 1)[1]
    if key not in CATALOG:
        await cb.answer()
        return
    u = await db.get_user(cb.message.chat.id)
    chosen = set(selected_sources(u))
    if key in chosen:
        if len(chosen) == 1:
            await cb.answer("Нужен хотя бы один источник", show_alert=True)
            return
        chosen.remove(key)
    else:
        chosen.add(key)
    ordered = [k for k in CATALOG if k in chosen]
    await db.update_user(cb.message.chat.id, sources=",".join(ordered))
    await cb.message.edit_reply_markup(reply_markup=sources_kb(ordered))
    await cb.answer()


async def _set_int(m: Message, command: CommandObject, field: str, lo: int, hi: int, ok: str):
    try:
        n = int((command.args or "").strip())
        assert lo <= n <= hi
    except (ValueError, AssertionError):
        await m.answer(f"Нужно число от {lo} до {hi}.")
        return
    await db.update_user(m.chat.id, **{field: n})
    await m.answer(ok.format(n=n))


@router.message(Command("limit"))
async def limit(m: Message, command: CommandObject):
    await _set_int(m, command, "limit_n", 1, 20, "Новостей в дайджесте: {n}")


@router.message(Command("every"))
async def every(m: Message, command: CommandObject):
    await _set_int(m, command, "every_hours", 1, 168, "Присылаю раз в {n} ч")


@router.message(Command("digest"))
async def digest_now(m: Message):
    u = await db.get_user(m.chat.id)
    await m.answer("Собираю подборку…")
    await send_digest(m.bot, m.chat.id, u, manual=True)
