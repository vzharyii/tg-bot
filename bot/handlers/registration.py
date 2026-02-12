"""
Registration handlers module
Handles user registration flow with FSM
"""

import logging
import re
from aiogram import types
from aiogram.dispatcher import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from bot.config import ADMIN_ID, REQUEST_PHOTO_FILE_ID, PHOTO_FILE_ID
from bot.models.states import UserStates
from bot.models.cache import last_bot_msg
from bot.database.connection import check_db_ready, db_execute_with_retry, db_fetch_with_retry
from bot.utils.ui import send_ui

logger = logging.getLogger(__name__)


def register_registration_handlers(dp):
    """Register all registration and appeal handlers"""
    
    # --- BAN APPEAL HANDLERS ---
    
    @dp.callback_query_handler(lambda c: c.data == "appeal_ban", state="*")
    async def process_appeal_click(call: types.CallbackQuery):
        """Start ban appeal process"""
        await UserStates.waiting_for_appeal.set()
        appeal_text = (
            "📝 <b>Обжалование бана</b>\n\n"
            "Напишите подробное объяснение, почему вы считаете бан ошибочным:"
        )
        markup = InlineKeyboardMarkup().add(InlineKeyboardButton("❌ Отмена", callback_data="cancel_appeal"))
        await send_ui(call, appeal_text, markup)
        await call.answer()

    @dp.callback_query_handler(text="cancel_appeal", state="*")
    async def process_cancel_appeal(call: types.CallbackQuery, state: FSMContext):
        """Cancel ban appeal"""
        await state.finish()
        ban_text = (
            f"🚫 <b>ВЫ ЗАБЛОКИРОВАНЫ</b>\n\n"
            f"Если считаете это ошибкой, нажмите кнопку ниже:"
        )
        markup_user = InlineKeyboardMarkup().add(InlineKeyboardButton("⚖️ Обжаловать бан", callback_data="appeal_ban"))
        await send_ui(call, ban_text, markup_user)
        await call.answer()

    @dp.message_handler(state=UserStates.waiting_for_appeal)
    async def process_appeal_text(message: types.Message, state: FSMContext):
        """Handle ban appeal text submission"""
        from aiogram import Bot
        from bot.config import API_TOKEN
        
        # Get ban reason from DB
        ban_reason = "Неизвестна"
        row = await db_fetch_with_retry(
            "SELECT reason FROM banned_users WHERE tg_user_id = %s",
            (message.from_user.id,),
            fetch="one",
            action_desc="Ошибка чтения причины бана для обжалования"
        )
        if row and row[0]:
            ban_reason = row[0]

        user_link = f"@{message.from_user.username}" if message.from_user.username else f"<a href='tg://user?id={message.from_user.id}'>{message.from_user.full_name}</a>"
        appeal_admin_text = (
            f"📩 <b>ОБЖАЛОВАНИЕ БАНА</b>\n\n"
            f"👤 <b>От:</b> {user_link} (ID: <code>{message.from_user.id}</code>)\n"
            f"🚫 <b>Причина бана:</b> {ban_reason}\n\n"
            f"<b>Текст обжалования:</b>\n{message.text}"
        )
        markup = InlineKeyboardMarkup().add(InlineKeyboardButton("🔓 Разбанить", callback_data=f"unban:{message.from_user.id}"))
        
        bot = message.bot
        await bot.send_message(ADMIN_ID, text=appeal_admin_text, reply_markup=markup, parse_mode="HTML")
        
        success_text = (
            "✅ <b>Обжалование отправлено!</b>\n\n"
            "Ожидайте решения администратора."
        )
        await send_ui(message, success_text)
        await state.finish()

    # --- REGISTRATION HANDLERS ---
    
    @dp.callback_query_handler(text="menu_apply", state="*")
    async def cb_menu_apply(call: types.CallbackQuery, state: FSMContext):
        """Start registration process"""
        user_id = call.from_user.id
        if not check_db_ready():
            return await call.answer("БД недоступна", show_alert=True)
        
        try:
            # Check status in access_list
            row = await db_fetch_with_retry(
                "SELECT nickname, approved FROM access_list WHERE tg_user_id = %s",
                (user_id,),
                fetch="one",
                action_desc="Ошибка проверки заявки"
            )
            
            if row:
                nickname, approved = row
                
                # Robust check if user is approved
                is_approved = False
                if approved == 1 or approved == '1':
                    is_approved = True
                elif isinstance(approved, str) and (approved.startswith('{') or approved.startswith('[')):
                    import json
                    try:
                        acc_dict = json.loads(approved)
                        if isinstance(acc_dict, dict) and any(acc_dict.values()):
                            is_approved = True
                    except:
                        pass
                
                if is_approved:
                    return await call.answer("✅ У вас уже есть доступ! Проверьте профиль.", show_alert=True)
                
                # If pending
                else:
                    pending_text = (
                        f"📩 <b>Ваша заявка уже отправлена!</b>\n\n"
                        f"🎮 <b>Ник:</b> <code>{nickname}</code>\n"
                        f"⏳ <b>Статус:</b> На рассмотрении\n\n"
                        f"Ожидайте решения администратора.\n"
                        f"Вы получите уведомление о результате."
                    )
                    markup = InlineKeyboardMarkup().add(InlineKeyboardButton("🏠 В главное меню", callback_data="menu_start"))
                    await send_ui(call, pending_text, markup)
                    return await call.answer()
                    
        except Exception as e:
            logger.error(f"Ошибка проверки заявки: {e}")
            return await call.answer("Ошибка БД", show_alert=True)

        # No application exists - start registration
        await UserStates.waiting_for_nick.set()
        markup = InlineKeyboardMarkup().add(InlineKeyboardButton("🔙 Отмена", callback_data="menu_start"))
        await send_ui(call, "📝 <b>Шаг 1/3</b>\nВведите ваш игровой <b>Nick_Name</b>:\n(Формат: Name_Surname)", markup)
        await call.answer()

    @dp.message_handler(state=UserStates.waiting_for_nick)
    async def process_reg_nick(message: types.Message, state: FSMContext):
        """Handle nickname input during registration"""
        from aiogram import Bot
        from bot.config import API_TOKEN
        
        nick = message.text.strip()
        # Delete user message to keep chat clean
        try:
            await message.delete()
        except:
            pass

        if not re.match(r"^[A-Z][a-zA-Z]*_[A-Z][a-zA-Z]*$", nick):
            # Format error
            err_text = (
                f"⚠️ <b>Ошибка формата!</b>\n"
                f"Вы ввели: <code>{nick}</code>\n\n"
                f"📝 <b>Шаг 1/3</b>\n"
                f"Введите ваш игровой <b>Nick_Name</b>:\n"
                f"(Формат: Name_Surname)"
            )
            markup = InlineKeyboardMarkup().add(InlineKeyboardButton("🔙 Отмена", callback_data="menu_start"))
            
            # Try to edit old message to avoid flashing
            user_id = message.from_user.id
            if user_id in last_bot_msg:
                try:
                    await message.bot.edit_message_caption(
                        chat_id=message.chat.id,
                        message_id=last_bot_msg[user_id],
                        caption=err_text,
                        reply_markup=markup,
                        parse_mode="HTML"
                    )
                    return
                except Exception as e:
                    logger.warning(f"Не смог отредачить ошибку: {e}")
                    try:
                        await message.bot.delete_message(message.chat.id, last_bot_msg[user_id])
                    except:
                        pass
            
            # Fallback: send new message
            await send_ui(message, err_text, markup)
            return
            
        await state.update_data(reg_nick=nick)
        await UserStates.waiting_for_info.set()
        markup = InlineKeyboardMarkup().add(InlineKeyboardButton("🔙 Отмена", callback_data="menu_start"))
        await send_ui(message, f"✅ Ник: <code>{nick}</code>\n\n📝 <b>Шаг 2/3</b>\nУкажите вашу <b>Семью</b> и кратко опишите кто вы:", markup)

    @dp.message_handler(state=UserStates.waiting_for_info)
    async def process_reg_info(message: types.Message, state: FSMContext):
        """Handle info input during registration"""
        from aiogram import Bot
        from bot.config import API_TOKEN
        
        info = message.text.strip()
        try:
            await message.delete()
        except:
            pass
        
        data = await state.get_data()
        nick = data.get("reg_nick")
        user_id = message.from_user.id
        
        if len(info) < 3:
            markup = InlineKeyboardMarkup().add(InlineKeyboardButton("🔙 Отмена", callback_data="menu_start"))
            await send_ui(message, "⚠️ Описание слишком короткое. Повторите:", markup)
            return
        
        # Save info to state and move to script selection
        await state.update_data(reg_info=info)
        await UserStates.waiting_for_script_selection.set()
        
        # Initialize selected scripts (empty by default)
        await state.update_data(selected_scripts={'mine': False, 'oskolki': False})
        
        # Show script selection menu
        from bot.handlers.script_selection import show_script_selection_menu
        await show_script_selection_menu(message, state)
