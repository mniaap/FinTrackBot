"""FinTrackBot — Main entry point.

Local usage:
    1. Copy .env.example to .env and fill in your tokens.
    2. pip install -r requirements.txt
    3. python bot.py

Render deployment:
    Push to GitHub → Render auto-detects Procfile → sets env vars in dashboard.
"""
import asyncio
import logging
import signal
import sys

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

from config import TELEGRAM_BOT_TOKEN
from database import init_db
from handlers import router

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

# Render sends SIGTERM; aiogram handles it via stop_polling(), but we
# also wire it explicitly so the process exits cleanly within the
# 30-second grace period.
_shutdown_event: asyncio.Event | None = None


def main() -> None:
    global _shutdown_event

    if not TELEGRAM_BOT_TOKEN:
        logger.error(
            "TELEGRAM_BOT_TOKEN is not set. "
            "On Render: add it in Environment Variables. "
            "Locally: copy .env.example to .env and fill it in."
        )
        sys.exit(1)

    # Initialise database tables
    init_db()
    logger.info("Database initialised.")

    # Create bot & dispatcher
    bot = Bot(
        token=TELEGRAM_BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()
    dp.include_router(router)

    # ---- Lifecycle callbacks ----
    async def on_startup() -> None:
        await bot.set_my_commands([
            ("start", "Welcome message & tutorial"),
            ("help", "Show all commands & examples"),
            ("owed", "Who owes you money"),
            ("owes", "Who you owe money to"),
            ("summary", "Spending summary (today / month)"),
            ("chart", "Spending pie chart"),
            ("budgets", "View all budgets"),
            ("export", "Export transactions as CSV"),
        ])
        logger.info("Bot started successfully! Listening for updates...")

    async def on_shutdown() -> None:
        logger.info("Shutting down gracefully...")
        await bot.session.close()
        logger.info("Bot stopped.")

    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    # ---- Signal handling for Render ----
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    _shutdown_event = asyncio.Event()

    def _handle_sigterm(signum, frame):
        logger.info("Received SIGTERM — initiating shutdown")
        asyncio.ensure_future(_request_shutdown())

    async def _request_shutdown():
        await dp.stop_polling()
        if _shutdown_event:
            _shutdown_event.set()

    try:
        loop.add_signal_handler(signal.SIGTERM, _handle_sigterm)
    except NotImplementedError:
        # Windows doesn't support add_signal_handler
        signal.signal(signal.SIGTERM, _handle_sigterm)

    # Run long-polling
    try:
        dp.run_polling(bot)
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        logger.info("Exiting.")


if __name__ == "__main__":
    main()