"""
Database connection module
Manages database pool, connections, and retry logic
"""

import logging
import asyncio
import aiomysql
from bot.config import DB_CONFIG

logger = logging.getLogger(__name__)

# Global reference to the web app (set by app.py)
_app = None


def set_app(app):
    """Set the global app reference"""
    global _app
    _app = app


def check_db_ready():
    """Check if database pool is ready"""
    return _app is not None and 'db_pool' in _app


async def init_db(app):
    """
    Initialize database connection pool
    Loads banned users and approved access into cache
    """
    global _app
    _app = app
    
    logger.info(f"🔄 Подключение к TiDB...")
    try:
        pool = await aiomysql.create_pool(**DB_CONFIG)
        app['db_pool'] = pool
        
        # Import cache functions here to avoid circular import
        from bot.models.cache import banned_cache, access_cache_set
        
        # Load banned users into cache
        result = await db_fetch_with_retry(
            "SELECT tg_user_id FROM banned_users",
            fetch="all",
            action_desc="Загрузка забаненных"
        )
        if result:
            for row in result:
                banned_cache.add(row[0])

        # Load approved users into access cache
        approved = await db_fetch_with_retry(
            "SELECT tg_user_id, nickname FROM access_list WHERE approved = 1 AND tg_user_id IS NOT NULL",
            fetch="all",
            action_desc="Загрузка доступа"
        )
        if approved:
            for uid, nick in approved:
                access_cache_set(uid, nick)
                    
        logger.info(f"✅ УСПЕХ: БД подключена. В бане: {len(banned_cache)} чел.")
    except Exception as e:
        logger.error(f"❌ Ошибка БД: {str(e)}")


async def close_db(app):
    """Close database connection pool"""
    if 'db_pool' in app:
        app['db_pool'].close()
        await app['db_pool'].wait_closed()


async def db_execute_with_retry(query, params=None, attempts=3, delay=0.5, action_desc="операция БД"):
    """
    Execute a database query with retry logic
    
    Args:
        query: SQL query string
        params: Query parameters tuple
        attempts: Number of retry attempts
        delay: Delay between retries (seconds)
        action_desc: Description for logging
        
    Returns:
        bool: True if successful, False otherwise
    """
    if not check_db_ready():
        return False
        
    for attempt in range(1, attempts + 1):
        try:
            pool = _app['db_pool']
            async with pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(query, params or ())
            return True
        except Exception as e:
            logger.error(f"{action_desc}: попытка {attempt} неудачна: {e}")
            if attempt < attempts:
                await asyncio.sleep(delay * attempt)
    return False


async def db_fetch_with_retry(query, params=None, fetch="all", attempts=3, delay=0.5, action_desc="операция БД"):
    """
    Fetch data from database with retry logic
    
    Args:
        query: SQL query string
        params: Query parameters tuple
        fetch: "all" or "one" - fetch all rows or just one
        attempts: Number of retry attempts
        delay: Delay between retries (seconds)
        action_desc: Description for logging
        
    Returns:
        Query results or None if failed
    """
    if not check_db_ready():
        return None
        
    for attempt in range(1, attempts + 1):
        try:
            pool = _app['db_pool']
            async with pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(query, params or ())
                    if fetch == "one":
                        return await cur.fetchone()
                    return await cur.fetchall()
        except Exception as e:
            logger.error(f"{action_desc}: попытка {attempt} неудачна: {e}")
            if attempt < attempts:
                await asyncio.sleep(delay * attempt)
    return None
