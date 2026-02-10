"""
Application factory module
Creates and configures the bot app
"""

import logging
import asyncio
from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.contrib.fsm_storage.memory import MemoryStorage

from bot.config import API_TOKEN, IS_WINDOWS
from bot.database.connection import init_db, close_db, set_app, db_fetch_with_retry

if IS_WINDOWS:
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
from bot.handlers.user import register_user_handlers
from bot.handlers.admin import register_admin_handlers
from bot.handlers.registration import register_registration_handlers
from bot.handlers.callbacks import register_callback_handlers
from bot.handlers.script_selection import register_script_selection_handlers
from bot.handlers.admin_approval import register_admin_approval_handlers
from bot.handlers.additional_access import register_additional_access_handlers

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Critical validation
if not API_TOKEN:
    logger.critical("❌ ОШИБКА: Проверь переменные окружения!")


def create_app():
    """
    Create and configure the bot application
    
    Returns:
        tuple: (web.Application, Bot, Dispatcher)
    """
    # Create components
    storage = MemoryStorage()
    bot = Bot(token=API_TOKEN)
    dp = Dispatcher(bot, storage=storage)
    app = web.Application()
    
    # Pass app reference to database module
    set_app(app)
    
    # Register all handlers
    logger.info("Регистрация обработчиков...")
    register_user_handlers(dp)
    register_admin_handlers(dp)
    register_registration_handlers(dp)
    register_script_selection_handlers(dp)
    register_admin_approval_handlers(dp)
    register_additional_access_handlers(dp)
    register_callback_handlers(dp)
    logger.info("✅ Обработчики зарегистрированы")
    
    # Setup routes
    app.router.add_get('/check', handle_check)
    app.router.add_get('/', lambda r: web.Response(text="OK"))
    
    # Setup startup and cleanup hooks
    app.on_startup.append(on_startup)
    app.on_cleanup.append(close_db)
    
    # Store bot and dispatcher in app for global access
    app['bot'] = bot
    app['dp'] = dp
    
    return app, bot, dp


async def handle_check(request):
    """Health check endpoint that returns access list"""
    app = request.app
    if 'db_pool' not in app:
        return web.json_response({"error": "DB Error"}, status=500)
        
    try:
        # Get requested script (default to 'mine' for backward compatibility)
        script_type = request.query.get('script', 'mine')
        
        # Get all approved users
        res = await db_fetch_with_retry(
            "SELECT nickname, approved FROM access_list WHERE approved IS NOT NULL AND approved != '0'",
            fetch="all",
            action_desc="Ошибка проверки БД"
        )
        
        if not res:
            return web.json_response([])
            
        allowed_users = []
        import json
        
        for nickname, approved in res:
            try:
                # 1. Check old format (int 1)
                if approved == 1 or approved == '1':
                    allowed_users.append(nickname)
                    continue
                    
                # 2. Check JSON format
                if isinstance(approved, str):
                    access = json.loads(approved)
                elif isinstance(approved, dict):
                    access = approved
                else:
                    continue
                    
                # Check specific script access
                if isinstance(access, dict) and access.get(script_type):
                    allowed_users.append(nickname)
                    
            except Exception:
                continue
                
        return web.json_response(allowed_users)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def on_startup(app):
    """Initialize database and start polling"""
    await init_db(app)
    dp = app['dp']
    asyncio.create_task(dp.start_polling())
