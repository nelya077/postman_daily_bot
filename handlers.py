import html
from datetime import date

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

import db
from digest import format_digest, search_news, selected_sources, send_digest, user_topics
from sources import CATALOG
from topics import PRESETS

router = Router()

HELP = (
    "📬 <b>Почтальон</b> собирает новости по вашим фильтрам.\n\n"
    "/menu — главное меню настроек\n"
    "/topics слово1, слово2 — тематика (ключевые слова; «-» чтобы сбросить)\n"
    "/sources — выбрать источники\n"
    "/limit 5 — сколько новостей в дайджесте (1–20)\n"
    "/every 24 — как часто присылать, в часах (1–168)\n"
    "/settings — текущие настройки\n"
    "/digest — получить подборку сейчас\n"
    "/search тема — найти свежие новости по теме в интернете"
)

WELCOME = (
    "👋 Приветствую, {name}!\n\n"
    "Я Почтальон: собираю новости по вашим темам и источникам "
    "и присылаю короткий дайджест, когда вам удобно.\n\n"
    "Настройка займёт минуту 👇"
)

MENU_TEXT = "📬 <b>Главное меню</b>\n\nЧто настроим?"

EVERY_OPTIONS = [
    (1, "Каждый час"),
    (3, "Каждые 3 часа"),
    (6, "Каждые 6 часов"),
    (12, "Каждые 12 часов"),
    (24, "Раз в день"),
    (168, "Раз в неделю"),
]
LIMIT_OPTIONS = [3, 5, 10, 15, 20]


class TopicInput(StatesGroup):
    waiting = State()


# ---------- вспомогательное ----------

def btn(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data)


def grid(buttons: list, per_row: int) -> list[list]:
    return [buttons[i:i + per_row] for i in range(0, len(buttons), per_row)]


def back_row() -> list:
    return [btn("◀️ В меню", "menu")]


async def edit(cb: CallbackQuery, text: str, kb: InlineKeyboardMarkup):
    try:
        await cb.message.edit_text(text, reply_markup=kb)
    except TelegramBadRequest:
        pass  # текст не изменился
    await cb.answer()


def every_text(hours: int) -> str:
    names = {h: label.lower() for h, label in EVERY_OPTIONS}
    return names.get(hours, f"раз в {hours} ч")


# ---------- экраны ----------

def menu_kb() -> InlineKeyboardMarkup:
    buttons = [
        btn("📰 Тема подборки", "m:topics"),
        btn("📡 Источники", "m:sources"),
        btn("⏰ Когда присылать", "m:when"),
        btn("📊 Объём новостей", "m:limit"),
    ]
    return InlineKeyboardMarkup(inline_keyboard=grid(buttons, 2))


def sources_kb(selected: list[str]) -> InlineKeyboardMarkup:
    buttons = [
        btn(f"{'✅' if key in selected else '▫️'} {name}", f"src:{key}")
        for key, (name, _) in CATALOG.items()
    ]
    return InlineKeyboardMarkup(inline_keyboard=grid(buttons, 2) + [back_row()])


def sources_screen(u: dict):
    text = "📡 <b>Источники</b>\n\nОтметьте, откуда брать новости:"
    return text, sources_kb(selected_sources(u))


def topics_screen(u: dict):
    current = user_topics(u)
    lower = {t.lower() for t in current}
    shown = html.escape(", ".join(current)) or "все темы"
    text = f"📰 <b>Тема подборки</b>\n\nСейчас: {shown}\n\nВыберите темы кнопками или добавьте свою:"
    buttons = [btn(f"{'✅ ' if name.lower() in lower else ''}{name}", f"tp:{name}") for name in PRESETS]
    rows = grid(buttons, 2) + [
        [btn("✏️ Своя тема", "tp:custom")],
        [btn("♻️ Сбросить (все темы)", "tp:reset")],
        back_row(),
    ]
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


def when_screen(u: dict):
    cur = u["every_hours"]
    text = (
        f"⏰ <b>Когда присылать новости</b>\n\nСейчас: {every_text(cur)}\n\n"
        "Как часто присылать подборку?"
    )
    buttons = [btn(f"{'✅ ' if h == cur else ''}{label}", f"wh:{h}") for h, label in EVERY_OPTIONS]
    return text, InlineKeyboardMarkup(inline_keyboard=grid(buttons, 2) + [back_row()])


def limit_screen(u: dict):
    cur = u["limit_n"]
    text = f"📊 <b>Объём новостей</b>\n\nСейчас: {cur} в подборке\n\nСколько новостей присылать за раз?"
    buttons = [btn(f"{'✅ ' if n == cur else ''}{n}", f"lm:{n}") for n in LIMIT_OPTIONS]
    return text, InlineKeyboardMarkup(inline_keyboard=grid(buttons, 5) + [back_row()])


SCREENS = {
    "topics": topics_screen,
    "sources": sources_screen,
    "when": when_screen,
    "limit": limit_screen,
}


# ---------- старт, меню, справка ----------

@router.message(CommandStart())
async def start(m: Message, state: FSMContext):
    await state.clear()
    is_new = not await db.user_exists(m.chat.id)
    await db.get_user(m.chat.id)
    if is_new:
        name = html.escape((m.from_user.first_name if m.from_user else "") or "друг")
        await m.answer(WELCOME.format(name=name), reply_markup=menu_kb())
    else:
        await m.answer(MENU_TEXT, reply_markup=menu_kb())


@router.message(Command("menu"))
async def menu(m: Message, state: FSMContext):
    await state.clear()
    await db.get_user(m.chat.id)
    await m.answer(MENU_TEXT, reply_markup=menu_kb())


@router.message(Command("help"))
async def help_(m: Message):
    await m.answer(HELP)


@router.callback_query(F.data == "menu")
async def menu_cb(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await edit(cb, MENU_TEXT, menu_kb())


@router.callback_query(F.data.startswith("m:"))
async def open_screen(cb: CallbackQuery):
    screen = SCREENS.get(cb.data[2:])
    if not screen:
        await cb.answer()
        return
    u = await db.get_user(cb.message.chat.id)
    text, kb = screen(u)
    await edit(cb, text, kb)


# ---------- тема ----------

@router.callback_query(F.data == "tp:custom")
async def topic_custom(cb: CallbackQuery, state: FSMContext):
    await state.set_state(TopicInput.waiting)
    await edit(
        cb,
        "✏️ <b>Своя тема</b>\n\nНапишите одно или несколько слов через запятую, "
        "например: <i>python, нейросети</i>. Они добавятся к вашим темам.",
        InlineKeyboardMarkup(inline_keyboard=[back_row()]),
    )


@router.message(TopicInput.waiting, F.text, ~F.text.startswith("/"))
async def topic_custom_input(m: Message, state: FSMContext):
    u = await db.get_user(m.chat.id)
    current = user_topics(u)
    lower = {t.lower() for t in current}
    for word in [w.strip()[:40] for w in m.text.split(",") if w.strip()][:10]:
        if word.lower() not in lower:
            current.append(word)
            lower.add(word.lower())
    await db.update_user(m.chat.id, topics=", ".join(current))
    await state.clear()
    u["topics"] = ", ".join(current)
    text, kb = topics_screen(u)
    await m.answer(text, reply_markup=kb)


@router.callback_query(F.data == "tp:reset")
async def topic_reset(cb: CallbackQuery):
    await db.update_user(cb.message.chat.id, topics="")
    u = await db.get_user(cb.message.chat.id)
    text, kb = topics_screen(u)
    await edit(cb, text, kb)


@router.callback_query(F.data.startswith("tp:"))
async def topic_toggle(cb: CallbackQuery):
    label = cb.data[3:]
    if label not in PRESETS:
        await cb.answer()
        return
    u = await db.get_user(cb.message.chat.id)
    current = user_topics(u)
    if label.lower() in {t.lower() for t in current}:
        current = [t for t in current if t.lower() != label.lower()]
    else:
        current.append(label)
    await db.update_user(cb.message.chat.id, topics=", ".join(current))
    u["topics"] = ", ".join(current)
    text, kb = topics_screen(u)
    await edit(cb, text, kb)


# ---------- источники ----------

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
    try:
        await cb.message.edit_reply_markup(reply_markup=sources_kb(ordered))
    except TelegramBadRequest:
        pass
    await cb.answer()


# ---------- частота и объём ----------

@router.callback_query(F.data.startswith("wh:"))
async def set_when(cb: CallbackQuery):
    hours = int(cb.data[3:])
    if hours not in {h for h, _ in EVERY_OPTIONS}:
        await cb.answer()
        return
    await db.update_user(cb.message.chat.id, every_hours=hours)
    u = await db.get_user(cb.message.chat.id)
    text, kb = when_screen(u)
    await edit(cb, text, kb)


@router.callback_query(F.data.startswith("lm:"))
async def set_limit(cb: CallbackQuery):
    n = int(cb.data[3:])
    if n not in LIMIT_OPTIONS:
        await cb.answer()
        return
    await db.update_user(cb.message.chat.id, limit_n=n)
    u = await db.get_user(cb.message.chat.id)
    text, kb = limit_screen(u)
    await edit(cb, text, kb)


# ---------- текстовые команды ----------

@router.message(Command("settings"))
async def settings(m: Message):
    u = await db.get_user(m.chat.id)
    topics = html.escape(", ".join(user_topics(u))) or "все темы"
    names = ", ".join(CATALOG[k][0] for k in selected_sources(u))
    await m.answer(
        f"<b>Настройки</b>\nТематика: {topics}\nИсточники: {names}\n"
        f"Новостей в дайджесте: {u['limit_n']}\nЧастота: {every_text(u['every_hours'])}"
    )


@router.message(Command("topics"))
async def topics_cmd(m: Message, command: CommandObject):
    if not command.args:
        await m.answer("Укажите слова через запятую, например: /topics ai, python, экономика\nСбросить: /topics -")
        return
    raw = command.args.strip()
    value = "" if raw == "-" else ", ".join(t.strip() for t in raw.split(",") if t.strip())
    await db.update_user(m.chat.id, topics=value)
    await m.answer(f"Тематика: {html.escape(value) or 'все темы'}")


@router.message(Command("sources"))
async def sources_cmd(m: Message):
    u = await db.get_user(m.chat.id)
    text, kb = sources_screen(u)
    await m.answer(text, reply_markup=kb)


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
async def limit_cmd(m: Message, command: CommandObject):
    await _set_int(m, command, "limit_n", 1, 20, "Новостей в дайджесте: {n}")


@router.message(Command("every"))
async def every_cmd(m: Message, command: CommandObject):
    await _set_int(m, command, "every_hours", 1, 168, "Присылаю раз в {n} ч")


@router.message(Command("digest"))
async def digest_now(m: Message):
    u = await db.get_user(m.chat.id)
    await m.answer("Собираю подборку…")
    await send_digest(m.bot, m.chat.id, u, manual=True)


SEARCH_PER_DAY = 20
_search_log: dict[int, tuple[str, int]] = {}  # chat_id -> (дата, сколько поисков сегодня)


@router.message(Command("search"))
async def search_cmd(m: Message, command: CommandObject):
    u = await db.get_user(m.chat.id)
    topics = [t.strip() for t in (command.args or "").split(",") if t.strip()] or user_topics(u)
    if not topics:
        await m.answer("Укажите тему: /search python, нейросети. Или выберите темы в /menu.")
        return

    today = date.today().isoformat()
    day, count = _search_log.get(m.chat.id, (today, 0))
    if day != today:
        count = 0
    if count >= SEARCH_PER_DAY:
        await m.answer(f"Лимит поисков на сегодня исчерпан ({SEARCH_PER_DAY}). Попробуйте завтра.")
        return
    _search_log[m.chat.id] = (today, count + 1)

    await m.answer("Ищу свежие новости…")
    items = await search_news(topics, u["limit_n"])
    if not items:
        await m.answer("Ничего не нашёл. Попробуйте другую тему или повторите позже.")
        return
    await m.answer(format_digest(items), disable_web_page_preview=True)
