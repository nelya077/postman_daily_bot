import asyncio
import logging
import os

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv

import db
from digest import tick
from handlers import router


async def main():
    load_dotenv()
    logging.basicConfig(level=logging.INFO)
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise SystemExit("Не задан BOT_TOKEN в файле .env")

    await db.init_db()
    bot = Bot(token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(router)

    await bot.set_my_commands([
        BotCommand(command="menu", description="Главное меню"),
        BotCommand(command="digest", description="Получить подборку сейчас"),
        BotCommand(command="search", description="Найти новости в интернете"),
        BotCommand(command="settings", description="Текущие настройки"),
        BotCommand(command="help", description="Список команд"),
    ])

    scheduler = AsyncIOScheduler()
    scheduler.add_job(tick, "interval", minutes=5, args=[bot])
    scheduler.start()

    try:
        await dp.start_polling(bot)
    finally:
        scheduler.shutdown(wait=False)
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass  # остановка через Ctrl+C / красный квадрат в PyCharm
