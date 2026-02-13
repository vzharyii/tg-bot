# Additional access request handlers
# Allows users to request access to scripts they don't have yet

import json
import logging
from aiogram import types
from aiogram.dispatcher import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from bot.config import ADMIN_ID, REQUEST_PHOTO_FILE_ID
from bot.models.states import UserStates
from bot.database.connection import db_execute_with_retry, db_fetch_with_retry
from bot.utils.ui import send_ui
from bot.utils.access_control import get_user_script_access

logger = logging.getLogger(__name__)


def register_additional_access_handlers(dp):
    """Register handlers for requesting additional script access"""
    
    @dp.callback_query_handler(text="request_additional_access", state="*")
    async def cb_request_additional_access(call: types.CallbackQuery, state: FSMContext):
        """Show menu to select which script to request access to"""
        user_id = call.from_user.id
        
        # Get current access
        current_access = await get_user_script_access(user_id)
        if not current_access:
            await call.answer("⚠️ Ошибка получения доступа", show_alert=True)
            return
        
        # Get user nickname
        row = await db_fetch_with_retry(
            "SELECT nickname FROM access_list WHERE tg_user_id = %s",
            (user_id,),
            fetch="one",
            action_desc="Ошибка получения ника"
        )
        
        if not row:
            await call.answer("⚠️ Профиль не найден", show_alert=True)
            return
        
        nickname = row[0]
        
        # Find scripts without access
        available_to_request = []
        if not current_access.get('mine'):
            available_to_request.append(('mine', '⛏ Скрипт Шахты'))
        if not current_access.get('oskolki'):
            available_to_request.append(('oskolki', '🔮 Счетчик осколков'))
        
        if not available_to_request:
            await call.answer("✅ У вас уже есть доступ ко всем скриптам!", show_alert=True)
            return
        
        # Store in state
        await state.update_data(
            additional_access_nickname=nickname,
            additional_access_current=current_access,
            additional_access_selected={}
        )
        await UserStates.waiting_for_script_selection.set()
        
        # Show selection menu
        await show_additional_access_menu(call, state, available_to_request)
    
    async def show_additional_access_menu(event, state, available_scripts):
        """Show script selection menu for additional access"""
        data = await state.get_data()
        selected = data.get('additional_access_selected', {})
        
        caption = (
            "➕ <b>Запрос дополнительного доступа</b>\n\n"
            "Выберите скрипты, к которым хотите получить доступ:\n\n"
        )
        
        for script_id, script_name in available_scripts:
            prefix = '✅ ' if selected.get(script_id) else ''
            caption += f"{prefix}<b>{script_name}</b>\n"
        
        caption += "\n<i>Нажмите на кнопки ниже для выбора</i>"
        
        markup = InlineKeyboardMarkup(row_width=1) # Wider buttons for full names
        
        # Add toggle buttons
        buttons = []
        for script_id, script_name in available_scripts:
            prefix = '✅ ' if selected.get(script_id) else ''
            buttons.append(InlineKeyboardButton(
                f"{prefix}{script_name}",
                callback_data=f"add_toggle_{script_id}"
            ))
        
        if buttons:
            for btn in buttons:
                markup.add(btn)
        
        # Show submit button only if at least one script is selected
        if any(selected.values()):
            markup.add(InlineKeyboardButton("Отправить запрос", callback_data="add_submit"))
        
        markup.add(InlineKeyboardButton("🔙 Отмена", callback_data="menu_profile"))
        
        await send_ui(event, caption, markup)
    
    @dp.callback_query_handler(lambda c: c.data.startswith("add_toggle_"), state=UserStates.waiting_for_script_selection)
    async def cb_add_toggle_script(call: types.CallbackQuery, state: FSMContext):
        """Toggle script selection for additional access"""
        script = call.data.replace("add_toggle_", "")
        
        data = await state.get_data()
        selected = data.get('additional_access_selected', {})
        current_access = data.get('additional_access_current', {})
        
        # Toggle the script
        selected[script] = not selected.get(script, False)
        await state.update_data(additional_access_selected=selected)
        
        # Get available scripts
        available_to_request = []
        if not current_access.get('mine'):
            available_to_request.append(('mine', '⛏ Скрипт Шахты'))
        if not current_access.get('oskolki'):
            available_to_request.append(('oskolki', '🔮 Счетчик осколков'))
        
        # Refresh the menu
        await show_additional_access_menu(call, state, available_to_request)
        await call.answer()
    
    @dp.callback_query_handler(text="add_submit", state=UserStates.waiting_for_script_selection)
    async def cb_add_submit(call: types.CallbackQuery, state: FSMContext):
        """Submit additional access request"""
        data = await state.get_data()
        nickname = data.get('additional_access_nickname')
        current_access = data.get('additional_access_current', {})
        selected = data.get('additional_access_selected', {})
        user_id = call.from_user.id
        
        if not any(selected.values()):
            await call.answer("⚠️ Выберите хотя бы один скрипт!", show_alert=True)
            return
        
        # Build requested scripts list
        requested_list = []
        if selected.get('mine'):
            requested_list.append("⛏ Скрипт Шахты")
        if selected.get('oskolki'):
            requested_list.append("🔮 Счетчик осколков")
        requested_text = ", ".join(requested_list)
        
        # Build current access list
        current_list = []
        if current_access.get('mine'):
            current_list.append("⛏ Скрипт Шахты")
        if current_access.get('oskolki'):
            current_list.append("🔮 Счетчик осколков")
        current_text = ", ".join(current_list) if current_list else "нет"
        
        # Prepare requested access JSON
        requested_access = {}
        if selected.get('mine'):
            requested_access['mine'] = True
        if selected.get('oskolki'):
            requested_access['oskolki'] = True
        
        requested_json = json.dumps(requested_access)
        
        # Update DB with requested_access
        await db_execute_with_retry(
            "UPDATE access_list SET requested_access = %s WHERE tg_user_id = %s",
            (requested_json, call.from_user.id),
            action_desc="Сохранение запроса на доп. доступ"
        )

        # Notify admin
        try:
            # Generate short code for approval buttons
            short_code_list = []
            if requested_access.get('mine'): short_code_list.append('m1')
            else: short_code_list.append('m0')
            
            if requested_access.get('oskolki'): short_code_list.append('o1')
            else: short_code_list.append('o0')
            
            short_code = "".join(short_code_list)
            
            user_link = f"@{call.from_user.username}" if call.from_user.username else f"<a href='tg://user?id={user_id}'>{call.from_user.full_name}</a>"

            caption = (
                f"➕ <b>Запрос дополнительного доступа</b>\n\n"
                f"👤 <b>От:</b> {user_link}\n"
                f"🎮 <b>Ник:</b> <code>{nickname}</code>\n"
                f"📜 <b>Запрашивает:</b> {requested_text}\n\n"
                f"<i>Заявка сохранена в базе и доступна через /pending</i>"
            )
            
            markup = InlineKeyboardMarkup(row_width=2)
            markup.add(
                InlineKeyboardButton("✅ Одобрить все", callback_data=f"approve_additional_all:{call.from_user.id}:{short_code}"),
                InlineKeyboardButton("⚙️ Выбрать", callback_data=f"approve_additional_select:{call.from_user.id}:{short_code}")
            )
            
            # Assuming PHOTO_FILE_ID is defined elsewhere or REQUEST_PHOTO_FILE_ID should be used
            # Using REQUEST_PHOTO_FILE_ID as it's already imported
            if REQUEST_PHOTO_FILE_ID and REQUEST_PHOTO_FILE_ID != "ВСТАВЬ_СЮДА_FILE_ID_ФОТКИ_ЗАЯВОК":
                await call.bot.send_photo(ADMIN_ID, REQUEST_PHOTO_FILE_ID, caption=caption, reply_markup=markup, parse_mode="HTML")
            else:
                await call.bot.send_message(ADMIN_ID, text=caption, reply_markup=markup, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Не удалось отправить уведомление админу: {e}")
        
        # Notify user
        # Assuming get_menu_markup is defined elsewhere or a default markup is needed
        # Using the original markup_home for consistency if get_menu_markup is not available
        markup_home = InlineKeyboardMarkup()
        markup_home.add(InlineKeyboardButton("👤 Профиль", callback_data="menu_profile"))
        markup_home.add(InlineKeyboardButton("🏠 В главное меню", callback_data="menu_start"))
        
        await send_ui(call, f"✅ <b>Запрос отправлен!</b>\n\n📜 Запрошенные скрипты:\n{requested_text}\n\nОжидайте решения администратора.", markup_home)
        await state.finish()
        await call.answer()
