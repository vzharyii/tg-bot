# Script selection handlers for registration
# This file contains handlers for the script selection step during user registration

import json
import logging
from aiogram import types
from aiogram.dispatcher import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from bot.config import ADMIN_ID, REQUEST_PHOTO_FILE_ID
from bot.models.states import UserStates
from bot.database.connection import db_execute_with_retry
from bot.utils.ui import send_ui

logger = logging.getLogger(__name__)


async def show_script_selection_menu(event, state):
    """Show script selection menu with checkboxes"""
    data = await state.get_data()
    selected = data.get('selected_scripts', {'mine': False, 'oskolki': False})
    
    caption = (
        "📜 <b>Шаг 3/3: Выбор скриптов</b>\n\n"
        "Выберите к каким скриптам вы хотите получить доступ:\n\n"
        f"{'✅ ' if selected.get('mine') else ''}<b>⛏ Скрипт Шахты</b>\n"
        f"{'✅ ' if selected.get('oskolki') else ''}<b>🔮 Счетчик осколков</b>\n\n"
        "<i>Нажмите на кнопки ниже для выбора</i>"
    )
    
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(
        InlineKeyboardButton(
            f"{'✅ ' if selected.get('mine') else ''}⛏ Скрипт Шахты",
            callback_data="reg_toggle_mine"
        ),
        InlineKeyboardButton(
            f"{'✅ ' if selected.get('oskolki') else ''}🔮 Счетчик осколков",
            callback_data="reg_toggle_oskolki"
        )
    )
    
    # Show submit button only if at least one script is selected
    if any(selected.values()):
        markup.add(InlineKeyboardButton("Отправить заявку", callback_data="reg_submit"))
    
    markup.add(InlineKeyboardButton("🔙 Отмена", callback_data="menu_start"))
    
    await send_ui(event, caption, markup)


def register_script_selection_handlers(dp):
    """Register script selection handlers"""
    
    @dp.callback_query_handler(lambda c: c.data.startswith("reg_toggle_"), state=UserStates.waiting_for_script_selection)
    async def cb_toggle_script(call: types.CallbackQuery, state: FSMContext):
        """Toggle script selection"""
        script = call.data.replace("reg_toggle_", "")
        
        data = await state.get_data()
        selected = data.get('selected_scripts', {'mine': False, 'oskolki': False})
        
        # Toggle the script
        selected[script] = not selected.get(script, False)
        await state.update_data(selected_scripts=selected)
        
        # Refresh the menu
        await show_script_selection_menu(call, state)
        await call.answer()
    
    @dp.callback_query_handler(text="reg_submit", state=UserStates.waiting_for_script_selection)
    async def cb_reg_submit(call: types.CallbackQuery, state: FSMContext):
        """Submit registration with selected scripts"""
        data = await state.get_data()
        nick = data.get("reg_nick")
        info = data.get("reg_info")
        selected_scripts = data.get('selected_scripts', {})
        user_id = call.from_user.id
        
        # Check if at least one script is selected
        if not any(selected_scripts.values()):
            await call.answer("⚠️ Выберите хотя бы один скрипт!", show_alert=True)
            return
        
        # Save application to DB with NULL (pending approval)
        # The requested scripts will be shown to admin in the notification
        success = await db_execute_with_retry(
            "INSERT INTO access_list (nickname, tg_user_id, approved) VALUES (%s, %s, NULL) "
            "ON DUPLICATE KEY UPDATE nickname=%s, approved=NULL",
            (nick, user_id, nick),
            action_desc="Ошибка сохранения заявки"
        )
        if not success:
            logger.error("Не удалось сохранить заявку в БД после повторов.")

        # Build requested scripts list for display
        requested_scripts_list = []
        if selected_scripts.get('mine'):
            requested_scripts_list.append("⛏ Скрипт Шахты")
        if selected_scripts.get('oskolki'):
            requested_scripts_list.append("🔮 Счетчик осколков")
        requested_scripts_text = ", ".join(requested_scripts_list)

        # Send to admin with script selection buttons
        user_link = f"@{call.from_user.username}" if call.from_user.username else f"<a href='tg://user?id={user_id}'>{call.from_user.full_name}</a>"

        caption_admin = (
            f"📩 <b>НОВАЯ ЗАЯВКА</b>\n\n"
            f"👤 <b>От:</b> {user_link} (ID: <code>{user_id}</code>)\n"
            f"🎮 <b>Ник:</b> <code>{nick}</code>\n"
            f"📄 <b>Описание:</b>\n{info}\n\n"
            f"📜 <b>Запрашивает доступ к:</b>\n{requested_scripts_text}"
        )
        
        # Create admin approval keyboard
        # Encode requested scripts in callback for admin to use
        scripts_json = json.dumps(selected_scripts)
        
        markup_admin = InlineKeyboardMarkup(row_width=3)
        markup_admin.add(
            InlineKeyboardButton("✅ Одобрить все", callback_data=f"approve_all:{user_id}:{scripts_json}"),
            InlineKeyboardButton("⚙️ Выбрать", callback_data=f"approve_select:{user_id}:{scripts_json}"),
            InlineKeyboardButton("❌ Отказать", callback_data=f"pre_no:{nick}:{user_id}")
        )
        markup_admin.add(
            InlineKeyboardButton("🚫 БАН", callback_data=f"pre_ban:{nick}:{user_id}")
        )

        try:
            # Send with photo if file_id is set
            if REQUEST_PHOTO_FILE_ID and REQUEST_PHOTO_FILE_ID != "ВСТАВЬ_СЮДА_FILE_ID_ФОТКИ_ЗАЯВОК":
                await call.bot.send_photo(ADMIN_ID, REQUEST_PHOTO_FILE_ID, caption=caption_admin, reply_markup=markup_admin, parse_mode="HTML")
            else:
                # Fallback to text if no file_id
                await call.bot.send_message(ADMIN_ID, text=caption_admin, reply_markup=markup_admin, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Err admin send: {e}")
        
        markup_home = InlineKeyboardMarkup().add(InlineKeyboardButton("🏠 В главное меню", callback_data="menu_start"))
        await send_ui(call, f"✅ <b>Заявка отправлена!</b>\n\n📜 Запрошенные скрипты:\n{requested_scripts_text}", markup_home)
        await state.finish()
        await call.answer()
