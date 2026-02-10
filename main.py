"""
Main entry point for Podzemka Bot
"""

import os
import asyncio
from aiohttp import web
from bot.app import create_app


def main():
    """Start the bot"""
    # Windows event loop fix
    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    # Create application
    app, bot, dp = create_app()
    
    # Get port from environment
    port = int(os.environ.get("PORT", 8080))
    
    # Run web application
    web.run_app(app, port=port)


if __name__ == '__main__':
    main()
