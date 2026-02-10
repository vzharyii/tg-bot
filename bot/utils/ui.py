"""
UI utilities module
Functions for sending and managing UI elements
"""

import logging
from aiogram import types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto

from bot.config import PHOTO_FILE_ID, ADMIN_ID
from bot.models.cache import last_bot_msg
from bot.database.queries import get_access_nickname

logger = logging.getLogger(__name__)


async def send_ui(event, caption, markup=None, photo=None):
    """
    Universal UI sender function
    - If CallbackQuery: edits current message (photo + text)
    - If Message: deletes old bot message (if exists), sends new photo
    
    Args:
        event: CallbackQuery or Message
        caption: Message caption/text
        markup: Inline keyboard markup
        photo: Photo file_id (defaults to PHOTO_FILE_ID)
    """
    # Use default photo if not specified
    if photo is None:
        photo = PHOTO_FILE_ID
    
    user_id = event.from_user.id
    
    # 1. If it's a Callback -> Edit message
    if isinstance(event, types.CallbackQuery):
        try:
            media = InputMediaPhoto(photo, caption=caption, parse_mode="HTML")
            await event.message.edit_media(media, reply_markup=markup)
        except Exception as e:
            # If content unchanged or message too old -> send new
            msg = await event.bot.send_photo(
                event.message.chat.id, 
                photo, 
                caption=caption, 
                reply_markup=markup, 
                parse_mode="HTML"
            )
            last_bot_msg[user_id] = msg.message_id
        return

    # 2. If it's a Message -> Clean up and send new
    if isinstance(event, types.Message):
        # Try to delete previous bot message
        if user_id in last_bot_msg:
            try:
                await event.bot.delete_message(event.chat.id, last_bot_msg[user_id])
            except:
                pass  # May be already deleted or too old
        
        # Send new message
        try:
            msg = await event.bot.send_photo(
                event.chat.id, 
                photo, 
                caption=caption, 
                reply_markup=markup, 
                parse_mode="HTML"
            )
            last_bot_msg[user_id] = msg.message_id
        except Exception as e:
            logger.error(f"UI Error: {e}")



async def get_menu_markup(user_id):
    """
    Get main menu markup based on user access
    
    Args:
        user_id: Telegram user ID
        
    Returns:
        InlineKeyboardMarkup: Menu keyboard
    """
    has_access = bool(await get_access_nickname(user_id))

    markup = InlineKeyboardMarkup(row_width=2)
    if has_access:
        # If has access: Profile, Scripts
        markup.row(
            InlineKeyboardButton("👤 Профиль", callback_data="menu_profile"),
            InlineKeyboardButton("📜 Скрипты", callback_data="menu_scripts")
        )
        markup.add(InlineKeyboardButton("💡 Предложить изменения", callback_data="menu_suggest"))
    else:
        # If no access: Profile, Submit application
        markup.row(
            InlineKeyboardButton("👤 Профиль", callback_data="menu_profile"),
            InlineKeyboardButton("📝 Подать заявку", callback_data="menu_apply")
        )
    markup.add(InlineKeyboardButton("📚 Помощь", callback_data="menu_help"))
    return markup


def get_help_text(user_id):
    """
    Get help text based on user role
    
    Args:
        user_id: Telegram user ID
        
    Returns:
        str: Help text
    """
    is_admin = (user_id == ADMIN_ID)
    
    text = (
        "📚 <b>Справочник</b>\n\n"
        "🤖 <b>Как пользоваться ботом?</b>\n"
        "Весь функционал доступен через <b>кнопки меню</b>:\n\n"
        "📝 <b>Подать заявку</b> — Нажмите, чтобы зарегистрировать свой ник для доступа к скрипту.\n"
        "👤 <b>Профиль</b> — Проверить свой текущий статус.\n\n"
        "<i>💡 Если меню пропало или бот завис, введите команду /start</i>"
    )

    if is_admin:
        text += (
            "\n\n👑 <b>Команды Админа:</b>\n"
            "• <code>/list</code> — Список одобренных пользователей\n"
            "• <code>/pending</code> — Заявки на рассмотрении\n"
            "• <code>/banned</code> — Список забаненных\n"
            "• <code>/suggestions</code> — Предложения пользователей\n"
            "• <code>/ban ID</code> — Бан (потребуется причина)\n"
            "• <code>/unban ID</code> — Разбан\n"
            "• <code>/add Nick</code> — Добавить ник вручную\n"
            "• <code>/del Nick</code> — Удалить ник полностью\n"
            "• <code>/revoke_mine Nick</code> — Отозвать доступ к Шахте\n"
            "• <code>/revoke_oskolki Nick</code> — Отозвать доступ к Осколкам\n"
            "• <code>/broadcast</code> — Рассылка сообщения всем\n"
            "• <code>/getphoto</code> — Получить file_id картинки\n"
            "• <code>/getfile</code> — Получить file_id файла"
        )
    return text
