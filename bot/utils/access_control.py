# Access control decorator and helpers
# Provides decorators and helper functions for checking script access

import logging
from functools import wraps
from aiogram import types

from bot.database.queries import has_script_access, get_user_script_access

logger = logging.getLogger(__name__)


def require_script_access(script_name):
    """
    Decorator to check if user has access to a specific script
    
    Args:
        script_name: Name of the script ('mine', 'oskolki', etc.)
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(call: types.CallbackQuery, *args, **kwargs):
            has_access = await has_script_access(call.from_user.id, script_name)
            if not has_access:
                await call.answer(f"🔒 У вас нет доступа к этому скрипту", show_alert=True)
                return
            return await func(call, *args, **kwargs)
        return wrapper
    return decorator


async def check_script_access_simple(user_id, script_name):
    """
    Simple helper to check script access
    
    Args:
        user_id: Telegram user ID
        script_name: Script identifier
        
    Returns:
        bool: True if user has access
    """
    return await has_script_access(user_id, script_name)


async def get_user_accessible_scripts(user_id):
    """
    Get list of scripts user has access to
    
    Args:
        user_id: Telegram user ID
        
    Returns:
        list: List of script names user has access to
    """
    access = await get_user_script_access(user_id)
    if not access:
        return []
    
    accessible = []
    if access.get('mine'):
        accessible.append('mine')
    if access.get('oskolki'):
        accessible.append('oskolki')
    
    return accessible


async def format_user_access_status(user_id):
    """
    Format user's access status as text
    
    Args:
        user_id: Telegram user ID
        
    Returns:
        str: Formatted access status text
    """
    access = await get_user_script_access(user_id)
    
    if not access:
        return "❌ Нет доступа к скриптам"
    
    status_lines = []
    
    if access.get('mine'):
        status_lines.append("Скрипт Шахты - ✅")
    else:
        status_lines.append("Скрипт Шахты - ❌")
    
    if access.get('oskolki'):
        status_lines.append("Счетчик осколков - ✅")
    else:
        status_lines.append("Счетчик осколков - ❌")
    
    return "\n".join(status_lines)
