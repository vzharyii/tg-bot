"""
Security middleware module
Ban checks and user security
"""

import logging
import time
from aiogram import types
from aiogram.dispatcher import FSMContext

from bot.config import ADMIN_ID, PHOTO_FILE_ID
from bot.models.states import UserStates
from bot.models.cache import banned_cache, last_bot_msg
from bot.database.connection import check_db_ready, db_execute_with_retry

logger = logging.getLogger(__name__)


async def check_user_status(message: types.Message, state: FSMContext = None):
    """
    Check if user is allowed to use the bot
    
    Args:
        message: Telegram message
        state: FSM context
        
    Returns:
        bool: True if user can proceed, False if banned
    """
    user_id = message.from_user.id
    
    # Check if user is banned
    if user_id in banned_cache:
        current_state = await state.get_state() if state else None
        # Allow appeal submission even when banned
        if current_state == UserStates.waiting_for_appeal.state:
            return True
        return False
    
    # Spam control removed as per request
    return True


async def ban_user_system(user_id, fullname, username, reason):
    """
    Ban a user from the bot
    
    Args:
        user_id: Telegram user ID
        fullname: User's full name
        username: User's username (or None)
        reason: Ban reason
    """
    from aiogram import Bot
    from bot.config import API_TOKEN
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    
    if user_id in banned_cache:
        return  # Already banned
    
    banned_cache.add(user_id)
    
    # Save to database
    if check_db_ready():
        success = await db_execute_with_retry(
            "INSERT IGNORE INTO banned_users (tg_user_id, reason) VALUES (%s, %s)",
            (user_id, reason),
            action_desc="Ошибка записи бана"
        )
        if not success:
            logger.error("Не удалось записать бан в БД после повторов.")
        
        # Remove any pending access request
        await db_execute_with_retry(
            "DELETE FROM access_list WHERE tg_user_id=%s",
            (user_id,),
            action_desc="Ошибка удаления заявки при бане"
        )
        
        # Clear access cache
        from bot.models.cache import access_cache_remove
        access_cache_remove(user_id)
    
    # Create bot instance for sending messages
    bot = Bot(token=API_TOKEN)
    
    # Notify admin
    user_link = f"@{username}" if username else f"<a href='tg://user?id={user_id}'>{fullname}</a>"
    admin_text = (
        f"🚫 <b>ПОЛЬЗОВАТЕЛЬ ЗАБАНЕН</b>\n\n"
        f"👤 <b>Кто:</b> {user_link} (ID: <code>{user_id}</code>)\n"
        f"📝 <b>Причина:</b> {reason}"
    )
    markup_admin = InlineKeyboardMarkup().add(InlineKeyboardButton("🔓 Разбанить", callback_data=f"unban:{user_id}"))
    try:
        await bot.send_message(ADMIN_ID, text=admin_text, reply_markup=markup_admin, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Ошибка отправки бана админу: {e}")
    
    # Notify user
    ban_text = (
        f"🚫 <b>ВЫ ЗАБЛОКИРОВАНЫ</b>\n\n"
        f"Если считаете это ошибкой, нажмите кнопку ниже:"
    )
    markup_user = InlineKeyboardMarkup().add(InlineKeyboardButton("⚖️ Обжаловать бан", callback_data="appeal_ban"))
    try:
        await bot.send_photo(user_id, PHOTO_FILE_ID, caption=ban_text, reply_markup=markup_user, parse_mode="HTML")
        last_bot_msg[user_id] = None  # Reset cache for new context
    except Exception as e:
        logger.warning(f"Не смог отправить уведомление о бане: {e}")
    
    await bot.session.close()
