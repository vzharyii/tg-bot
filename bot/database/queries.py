"""
Database queries module
Contains all database query functions
"""

from .connection import db_execute_with_retry, db_fetch_with_retry
from bot.models.cache import access_cache, access_cache_set, access_cache_remove, access_cache_remove_by_nick
import time
import json


async def get_user_script_access(user_id):
    """
    Get user's script access permissions
    
    Args:
        user_id: Telegram user ID
        
    Returns:
        dict: Dictionary like {'mine': True, 'oskolki': False} or None if no access
    """
    # Check cache first
    cached = access_cache.get(user_id)
    if cached:
        nickname, expires_at, access_dict = cached
        if expires_at > time.time() and isinstance(access_dict, dict):
            return access_dict
        # If expired or access_dict is None (old cache format), remove it
        if expires_at <= time.time():
            access_cache.pop(user_id, None)

    row = await db_fetch_with_retry(
        "SELECT approved, nickname FROM access_list WHERE tg_user_id = %s",
        (user_id,),
        fetch="one",
        action_desc="Ошибка проверки доступа к скриптам"
    )
    
    if not row or row[0] is None:
        return None
    
    approved_json, nickname = row
    
    # Parse JSON or handle legacy 0/1
    access_dict = None
    try:
        # If it's modern JSON (e.g. '{"mine": true}')
        if isinstance(approved_json, str) and (approved_json.startswith('{') or approved_json.startswith('[')):
            access_dict = json.loads(approved_json)
        elif isinstance(approved_json, dict):
            access_dict = approved_json
        # If it's legacy or simplified status
        else:
             val = str(approved_json)
             if val == '1':
                 access_dict = {'mine': True, 'oskolki': True}
             else:
                 # 0, NULL, or any other value means no approved access
                 return None
    except Exception as e:
        logger.error(f"Error parsing access JSON for {user_id}: {e}")
        return None
        
    # Extra check: if it parsed as empty dict, treat as no access
    if not access_dict or not any(access_dict.values()):
        return None
        
    # Populate cache
    if access_dict:
        access_cache_set(user_id, nickname, access_dict)
        
    return access_dict


async def has_script_access(user_id, script_name):
    """
    Check if user has access to a specific script
    
    Args:
        user_id: Telegram user ID
        script_name: Script identifier ('mine', 'oskolki', etc.)
        
    Returns:
        bool: True if user has access to the script
    """
    access = await get_user_script_access(user_id)
    if not access:
        return False
    return access.get(script_name, False)


async def get_access_nickname(user_id):
    """
    Get user's approved nickname from cache or database
    
    Args:
        user_id: Telegram user ID
        
    Returns:
        str: Nickname if user has ANY approved access, None otherwise
    """
    # Check cache first
    cached = access_cache.get(user_id)
    if cached:
        nickname, expires_at, _ = cached # Unpack 3 values
        if expires_at > time.time():
            return nickname
        access_cache.pop(user_id, None)
    
    # Query database - check if user has any approved scripts
    row = await db_fetch_with_retry(
        "SELECT nickname, approved FROM access_list WHERE tg_user_id = %s",
        (user_id,),
        fetch="one",
        action_desc="Ошибка проверки доступа"
    )
    
    if not row:
        return None
    
    nickname, approved = row
    
    # Check if user has any approved scripts
    if approved is None:
        return None
    
    try:
        # Parse JSON to check if any script is approved
        if isinstance(approved, str):
            access_dict = json.loads(approved)
        elif isinstance(approved, dict):
            access_dict = approved
        else:
            # Old format compatibility
            access_dict = {'mine': True, 'oskolki': True}
        
        # If any script is approved, cache and return nickname
        if any(access_dict.values()):
            access_cache_set(user_id, nickname, access_dict)
            return nickname
    except:
        pass
    
    return None
