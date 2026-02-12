"""
Cache management module
In-memory caches for performance optimization
"""

import time
from bot.config import ACCESS_CACHE_TTL, ACCESS_CACHE_MAX

# --- CACHE STORES ---
spam_control = {}  # user_id -> timestamp
banned_cache = set()  # Set of banned user IDs
last_bot_msg = {}  # user_id -> message_id for deletion
pending_cache = {}  # admin_id -> list of (nick, uid)
access_cache = {}  # user_id -> (nickname, expires_at)


def access_cache_cleanup():
    """Remove expired entries from access cache"""
    now = time.time()
    for uid, val in list(access_cache.items()):
        # Handle tuple values: (nick, expires_at, [scripts])
        if len(val) >= 2:
            expires_at = val[1]
            if expires_at <= now:
                access_cache.pop(uid, None)


def access_cache_set(user_id, nickname, access_dict=None):
    """
    Add or update user in access cache
    
    Args:
        user_id: Telegram user ID
        nickname: User's approved nickname
        access_dict: Dictionary of approved scripts (optional)
    """
    access_cache_cleanup()
    if len(access_cache) >= ACCESS_CACHE_MAX:
        access_cache.pop(next(iter(access_cache)), None)
    
    # Store timestamp, nickname and access dict
    # Structure: (nickname, expires_at, access_dict)
    # Default access_dict to empty if not provided, though typically should be provided
    access_cache[user_id] = (nickname, time.time() + ACCESS_CACHE_TTL, access_dict)


def access_cache_remove(user_id):
    """
    Remove user from access cache by user ID
    
    Args:
        user_id: Telegram user ID
    """
    access_cache.pop(user_id, None)


def access_cache_remove_by_nick(nickname):
    """
    Remove user from access cache by nickname
    
    Args:
        nickname: User's nickname
    """
    for uid, val in list(access_cache.items()):
        # Handle both 2-tuple (legacy) and 3-tuple (new) structures
        if len(val) >= 1:
            cached_nick = val[0]
            if cached_nick == nickname:
                access_cache.pop(uid, None)
