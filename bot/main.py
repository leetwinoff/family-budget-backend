"""
Entry point for the Telegram bot.
Run with:  python -m bot.main
"""
import logging
import os
import sys

from dotenv import load_dotenv
from telegram.ext import Application, CommandHandler, ChatMemberHandler

# Allow running from the backend/ directory without installing the package
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv()

from bot.handlers import cmd_start, on_bot_added  # noqa: E402

logging.basicConfig(
    format='%(asctime)s | %(levelname)s | %(name)s | %(message)s',
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def main() -> None:
    token = os.environ.get('TELEGRAM_BOT_TOKEN')
    if not token:
        logger.error('TELEGRAM_BOT_TOKEN is not set. Exiting.')
        sys.exit(1)

    frontend_url = os.environ.get('FRONTEND_URL', '')
    if not frontend_url:
        logger.warning('FRONTEND_URL is not set — WebApp button will not work.')

    app = Application.builder().token(token).build()

    # Commands
    app.add_handler(CommandHandler('start', cmd_start))
    app.add_handler(CommandHandler('budget', cmd_start))

    # Bot added to / removed from a chat
    app.add_handler(ChatMemberHandler(on_bot_added, ChatMemberHandler.MY_CHAT_MEMBER))

    logger.info('Bot is running...')
    app.run_polling(allowed_updates=['message', 'my_chat_member'])


if __name__ == '__main__':
    main()
