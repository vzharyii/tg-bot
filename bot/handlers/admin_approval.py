# Admin approval handlers for per-script access control
# Handles approval flow where admin can select which scripts to approve

import json
import logging
from aiogram import types
from aiogram.dispatcher import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from bot.config import ADMIN_ID, PHOTO_FILE_ID
from bot.models.cache import last_bot_msg, access_cache_set, access_cache_remove
from bot.database.connection import db_execute_with_retry, db_fetch_with_retry
from bot.utils.ui import send_ui

logger = logging.getLogger(__name__)


def register_admin_approval_handlers(dp):
    """Register admin approval handlers for script selection"""
    
    @dp.callback_query_handler(lambda c: c.data.startswith("approve_all:"), state="*")
    async def cb_approve_all(call: types.CallbackQuery):
        """Approve all requested scripts"""
        parts = call.data.split(":", 2)
        user_id = int(parts[1])
        
        # Get requested scripts from callback data
        try:
            requested_scripts = json.loads(parts[2]) if len(parts) > 2 else {'mine': True, 'oskolki': True}
        except:
            requested_scripts = {'mine': True, 'oskolki': True}
        
        # Get user info from database
        row = await db_fetch_with_retry(
            "SELECT nickname FROM access_list WHERE tg_user_id = %s",
            (user_id,),
            fetch="one",
            action_desc="Ошибка получения ника пользователя"
        )
        
        if not row:
            await call.answer("⚠️ Заявка не найдена", show_alert=True)
            return
        
        nickname = row[0]
        
        # Approve all requested scripts
        approved_json = json.dumps(requested_scripts)
        success = await db_execute_with_retry(
            "UPDATE access_list SET approved = %s WHERE tg_user_id = %s",
            (approved_json, user_id),
            action_desc="Ошибка одобрения заявки"
        )
        
        if not success:
            await call.answer("❌ Ошибка БД", show_alert=True)
            return
        
        # Update cache
        access_cache_set(user_id, nickname)
        
        # Build approved scripts list
        approved_list = []
        if requested_scripts.get('mine'):
            approved_list.append("⛏ Скрипт Шахты")
        if requested_scripts.get('oskolki'):
            approved_list.append("🔮 Счетчик осколков")
        approved_text = ", ".join(approved_list)
        
        # Notify user
        try:
            approval_text = (
                f"✅ <b>Доступ одобрен!</b>\n\n"
                f"🎮 <b>Ник:</b> <code>{nickname}</code>\n"
                f"📜 <b>Доступные скрипты:</b>\n{approved_text}\n\n"
                f"Теперь вы можете скачивать и использовать скрипты!"
            )
            markup_user = InlineKeyboardMarkup()
            markup_user.add(InlineKeyboardButton("📜 Скрипты", callback_data="menu_scripts"))
            markup_user.add(InlineKeyboardButton("🏠 Главное меню", callback_data="menu_start"))
            
            # Delete old message if exists
            if user_id in last_bot_msg and last_bot_msg[user_id]:
                try:
                    await call.bot.delete_message(user_id, last_bot_msg[user_id])
                except:
                    pass
            
            # Send approval notification
            msg = await call.bot.send_photo(
                user_id,
                PHOTO_FILE_ID,
                caption=approval_text,
                reply_markup=markup_user,
                parse_mode="HTML"
            )
            last_bot_msg[user_id] = msg.message_id
        except Exception as e:
            logger.error(f"Не смог отправить одобрение юзеру {user_id}: {e}")
        
        # Update admin message - remove buttons and add status
        try:
            status_line = f"\n\n✅ <b>ОДОБРЕНО:</b> {nickname}\n📜 Скрипты: {approved_text}"
            new_caption = (call.message.caption or call.message.text or "") + status_line
            
            if call.message.caption:
                await call.message.edit_caption(
                    caption=new_caption, 
                    parse_mode="HTML",
                    reply_markup=None  # Remove buttons
                )
            else:
                await call.message.edit_text(
                    text=new_caption, 
                    parse_mode="HTML",
                    reply_markup=None  # Remove buttons
                )
        except Exception as e:
            logger.error(f"Failed to update admin message: {e}")
        
        await call.answer(f"✅ Одобрено: {approved_text}")
    
    @dp.callback_query_handler(lambda c: c.data.startswith("approve_select:"), state="*")
    async def cb_approve_select(call: types.CallbackQuery, state: FSMContext):
        """Show script selection interface for admin"""
        parts = call.data.split(":", 2)
        user_id = int(parts[1])
        
        # Get requested scripts
        try:
            requested_scripts = json.loads(parts[2]) if len(parts) > 2 else {'mine': True, 'oskolki': True}
        except:
            requested_scripts = {'mine': True, 'oskolki': True}
        
        # Get user info
        row = await db_fetch_with_retry(
            "SELECT nickname FROM access_list WHERE tg_user_id = %s",
            (user_id,),
            fetch="one",
            action_desc="Ошибка получения ника"
        )
        
        if not row:
            await call.answer("⚠️ Заявка не найдена", show_alert=True)
            return
        
        nickname = row[0]
        
        # Store in state (including original caption for later update)
        await state.update_data(
            approval_user_id=user_id,
            approval_nickname=nickname,
            approval_requested=requested_scripts,
            approval_selected={'mine': False, 'oskolki': False},
            approval_admin_msg_id=call.message.message_id,
            approval_original_caption=call.message.caption or call.message.text
        )
        
        # Show selection menu
        await show_admin_script_selection(call, state)
    
    async def show_admin_script_selection(event, state):
        """Show admin script selection menu"""
        data = await state.get_data()
        requested = data.get('approval_requested', {})
        selected = data.get('approval_selected', {})
        nickname = data.get('approval_nickname', 'Unknown')
        
        caption = (
            f"⚙️ <b>Выбор скриптов для одобрения</b>\n\n"
            f"👤 <b>Пользователь:</b> <code>{nickname}</code>\n"
            f"📜 <b>Запросил:</b> "
        )
        
        requested_list = []
        if requested.get('mine'):
            requested_list.append("⛏ Скрипт Шахты")
        if requested.get('oskolki'):
            requested_list.append("🔮 Счетчик осколков")
        caption += ", ".join(requested_list) if requested_list else "нет"
        
        caption += "\n\n<b>Выберите что одобрить:</b>\n"
        
        if requested.get('mine'):
            caption += f"{'✅ ' if selected.get('mine') else ''}<b>⛏ Скрипт Шахты</b>\n"
        if requested.get('oskolki'):
            caption += f"{'✅ ' if selected.get('oskolki') else ''}<b>🔮 Счетчик осколков</b>\n"
        
        markup = InlineKeyboardMarkup(row_width=1)
        
        # Add toggle buttons only for requested scripts
        buttons = []
        if requested.get('mine'):
            buttons.append(InlineKeyboardButton(
                f"{'✅ ' if selected.get('mine') else ''}⛏ Скрипт Шахты",
                callback_data="admin_toggle_mine"
            ))
        if requested.get('oskolki'):
            buttons.append(InlineKeyboardButton(
                f"{'✅ ' if selected.get('oskolki') else ''}🔮 Счетчик осколков",
                callback_data="admin_toggle_oskolki"
            ))
        
        if buttons:
            for btn in buttons:
                markup.add(btn)
        
        # Show approve button only if at least one script is selected
        if any(selected.values()):
            markup.add(InlineKeyboardButton("✅ Одобрить выбранные", callback_data="admin_approve_confirm"))
        
        markup.add(InlineKeyboardButton("🔙 Отмена", callback_data="admin_approve_cancel"))
        
        try:
            await event.message.answer(caption, reply_markup=markup, parse_mode="HTML")
        except:
            await event.bot.send_message(ADMIN_ID, caption, reply_markup=markup, parse_mode="HTML")
        
        await event.answer()
    
    @dp.callback_query_handler(lambda c: c.data.startswith("admin_toggle_"), state="*")
    async def cb_admin_toggle_script(call: types.CallbackQuery, state: FSMContext):
        """Toggle script selection for admin approval"""
        script = call.data.replace("admin_toggle_", "")
        
        data = await state.get_data()
        selected = data.get('approval_selected', {})
        
        # Toggle the script
        selected[script] = not selected.get(script, False)
        await state.update_data(approval_selected=selected)
        
        # Update the message
        data = await state.get_data()
        requested = data.get('approval_requested', {})
        nickname = data.get('approval_nickname', 'Unknown')
        
        caption = (
            f"⚙️ <b>Выбор скриптов для одобрения</b>\n\n"
            f"👤 <b>Пользователь:</b> <code>{nickname}</code>\n"
            f"📜 <b>Запросил:</b> "
        )
        
        requested_list = []
        if requested.get('mine'):
            requested_list.append("⛏ Скрипт Шахты")
        if requested.get('oskolki'):
            requested_list.append("🔮 Счетчик осколков")
        caption += ", ".join(requested_list) if requested_list else "нет"
        
        caption += "\n\n<b>Выберите что одобрить:</b>\n"
        
        if requested.get('mine'):
            caption += f"{'✅ ' if selected.get('mine') else ''}<b>⛏ Скрипт Шахты</b>\n"
        if requested.get('oskolki'):
            caption += f"{'✅ ' if selected.get('oskolki') else ''}<b>🔮 Счетчик осколков</b>\n"
        
        markup = InlineKeyboardMarkup(row_width=1)
        
        buttons = []
        if requested.get('mine'):
            buttons.append(InlineKeyboardButton(
                f"{'✅ ' if selected.get('mine') else ''}⛏ Скрипт Шахты",
                callback_data="admin_toggle_mine"
            ))
        if requested.get('oskolki'):
            buttons.append(InlineKeyboardButton(
                f"{'✅ ' if selected.get('oskolki') else ''}🔮 Счетчик осколков",
                callback_data="admin_toggle_oskolki"
            ))
        
        if buttons:
            for btn in buttons:
                markup.add(btn)
        
        if any(selected.values()):
            markup.add(InlineKeyboardButton("✅ Одобрить выбранные", callback_data="admin_approve_confirm"))
        
        markup.add(InlineKeyboardButton("🔙 Отмена", callback_data="admin_approve_cancel"))
        
        try:
            await call.message.edit_text(caption, reply_markup=markup, parse_mode="HTML")
        except:
            pass
        
        await call.answer()
    
    @dp.callback_query_handler(text="admin_approve_confirm", state="*")
    async def cb_admin_approve_confirm(call: types.CallbackQuery, state: FSMContext):
        """Confirm and save admin's script selection"""
        data = await state.get_data()
        user_id = data.get('approval_user_id')
        nickname = data.get('approval_nickname')
        selected = data.get('approval_selected', {})
        admin_msg_id = data.get('approval_admin_msg_id')
        
        if not any(selected.values()):
            await call.answer("⚠️ Выберите хотя бы один скрипт!", show_alert=True)
            return
        
        # Save to database
        approved_json = json.dumps(selected)
        success = await db_execute_with_retry(
            "UPDATE access_list SET approved = %s WHERE tg_user_id = %s",
            (approved_json, user_id),
            action_desc="Ошибка одобрения заявки"
        )
        
        if not success:
            await call.answer("❌ Ошибка БД", show_alert=True)
            return
        
        # Update cache
        access_cache_set(user_id, nickname)
        
        # Build approved scripts list
        approved_list = []
        if selected.get('mine'):
            approved_list.append("⛏ Скрипт Шахты")
        if selected.get('oskolki'):
            approved_list.append("🔮 Счетчик осколков")
        approved_text = ", ".join(approved_list)
        
        # Notify user
        try:
            approval_text = (
                f"✅ <b>Доступ одобрен!</b>\n\n"
                f"🎮 <b>Ник:</b> <code>{nickname}</code>\n"
                f"📜 <b>Доступные скрипты:</b>\n{approved_text}\n\n"
                f"Теперь вы можете скачивать и использовать скрипты!"
            )
            markup_user = InlineKeyboardMarkup()
            markup_user.add(InlineKeyboardButton("📜 Скрипты", callback_data="menu_scripts"))
            markup_user.add(InlineKeyboardButton("🏠 Главное меню", callback_data="menu_start"))
            
            if user_id in last_bot_msg and last_bot_msg[user_id]:
                try:
                    await call.bot.delete_message(user_id, last_bot_msg[user_id])
                except:
                    pass
            
            msg = await call.bot.send_photo(
                user_id,
                PHOTO_FILE_ID,
                caption=approval_text,
                reply_markup=markup_user,
                parse_mode="HTML"
            )
            last_bot_msg[user_id] = msg.message_id
        except Exception as e:
            logger.error(f"Не смог отправить одобрение юзеру {user_id}: {e}")
        
        # Update original admin message - remove buttons and add status
        try:
            original_caption = data.get('approval_original_caption', '')
            status_line = f"\n\n✅ <b>ОДОБРЕНО:</b> {nickname}\n📜 Скрипты: {approved_text}"
            new_caption = original_caption + status_line
            
            # Edit message and remove reply markup (buttons)
            try:
                await call.bot.edit_message_caption(
                    chat_id=ADMIN_ID,
                    message_id=admin_msg_id,
                    caption=new_caption,
                    parse_mode="HTML",
                    reply_markup=None  # Remove buttons
                )
            except:
                # If it's a text message instead of photo
                try:
                    await call.bot.edit_message_text(
                        chat_id=ADMIN_ID,
                        message_id=admin_msg_id,
                        text=new_caption,
                        parse_mode="HTML",
                        reply_markup=None  # Remove buttons
                    )
                except Exception as e:
                    logger.error(f"Failed to update admin message: {e}")
        except Exception as e:
            logger.error(f"Failed to update admin message outer: {e}")
        
        # Delete selection message
        try:
            await call.message.delete()
        except:
            pass
        
        await call.answer(f"✅ Одобрено: {approved_text}")
        await state.finish()
    
    @dp.callback_query_handler(text="admin_approve_cancel", state="*")
    async def cb_admin_approve_cancel(call: types.CallbackQuery, state: FSMContext):
        """Cancel admin script selection"""
        try:
            await call.message.delete()
        except:
            pass
        
        await call.answer("❌ Отменено")
        await state.finish()
    
    # --- ADDITIONAL ACCESS APPROVAL HANDLERS ---
    
    @dp.callback_query_handler(lambda c: c.data.startswith("approve_additional_all:"), state="*")
    async def cb_approve_additional_all(call: types.CallbackQuery):
        """Approve all requested additional scripts"""
        parts = call.data.split(":", 2)
        user_id = int(parts[1])
        
        # Get requested scripts
        try:
            requested_scripts = json.loads(parts[2]) if len(parts) > 2 else {}
        except:
            requested_scripts = {}
        
        # Get current user access
        from bot.database.queries import get_user_script_access
        current_access = await get_user_script_access(user_id)
        
        if not current_access:
            await call.answer("⚠️ Пользователь не найден", show_alert=True)
            return
        
        # Get user info
        row = await db_fetch_with_retry(
            "SELECT nickname FROM access_list WHERE tg_user_id = %s",
            (user_id,),
            fetch="one",
            action_desc="Ошибка получения ника"
        )
        
        if not row:
            await call.answer("⚠️ Пользователь не найден", show_alert=True)
            return
        
        nickname = row[0]
        
        # Merge current access with requested
        new_access = current_access.copy()
        for script, value in requested_scripts.items():
            if value:
                new_access[script] = True
        
        # Save to database
        approved_json = json.dumps(new_access)
        success = await db_execute_with_retry(
            "UPDATE access_list SET approved = %s WHERE tg_user_id = %s",
            (approved_json, user_id),
            action_desc="Ошибка одобрения дополнительного доступа"
        )
        
        if not success:
            await call.answer("❌ Ошибка БД", show_alert=True)
            return
        
        # Update cache
        access_cache_set(user_id, nickname)
        
        # Build newly granted scripts list
        newly_granted = []
        if requested_scripts.get('mine'):
            newly_granted.append("⛏ Скрпит Шахты")
        if requested_scripts.get('oskolki'):
            newly_granted.append("🔮 Счетчик Осколков")
        granted_text = ", ".join(newly_granted)
        
        # Notify user
        try:
            approval_text = (
                f"✅ <b>Дополнительный доступ одобрен!</b>\n\n"
                f"🎮 <b>Ник:</b> <code>{nickname}</code>\n"
                f"➕ <b>Новые скрипты:</b>\n{granted_text}\n\n"
                f"Теперь вы можете скачивать и использовать эти скрипты!"
            )
            markup_user = InlineKeyboardMarkup()
            markup_user.add(InlineKeyboardButton("📜 Скрипты", callback_data="menu_scripts"))
            markup_user.add(InlineKeyboardButton("👤 Профиль", callback_data="menu_profile"))
            
            if user_id in last_bot_msg and last_bot_msg[user_id]:
                try:
                    await call.bot.delete_message(user_id, last_bot_msg[user_id])
                except:
                    pass
            
            msg = await call.bot.send_photo(
                user_id,
                PHOTO_FILE_ID,
                caption=approval_text,
                reply_markup=markup_user,
                parse_mode="HTML"
            )
            last_bot_msg[user_id] = msg.message_id
        except Exception as e:
            logger.error(f"Не смог отправить одобрение юзеру {user_id}: {e}")
        
        # Update admin message
        try:
            status_line = f"\n\n✅ <b>ОДОБРЕНО:</b> {nickname}\n➕ Добавлены: {granted_text}"
            new_caption = (call.message.caption or call.message.text or "") + status_line
            
            if call.message.caption:
                await call.message.edit_caption(caption=new_caption, parse_mode="HTML")
            else:
                await call.message.edit_text(text=new_caption, parse_mode="HTML")
        except:
            pass
        
        await call.answer(f"✅ Одобрено: {granted_text}")
    
    @dp.callback_query_handler(lambda c: c.data.startswith("reject_additional:"), state="*")
    async def cb_reject_additional(call: types.CallbackQuery):
        """Reject additional access request"""
        user_id = int(call.data.split(":")[1])
        
        # Get user info
        row = await db_fetch_with_retry(
            "SELECT nickname FROM access_list WHERE tg_user_id = %s",
            (user_id,),
            fetch="one",
            action_desc="Ошибка получения ника"
        )
        
        if not row:
            await call.answer("⚠️ Пользователь не найден", show_alert=True)
            return
        
        nickname = row[0]
        
        # Notify user
        try:
            reject_text = (
                f"❌ <b>Запрос отклонен</b>\n\n"
                f"🎮 <b>Ник:</b> <code>{nickname}</code>\n\n"
                f"Ваш запрос на дополнительный доступ был отклонен администратором."
            )
            markup_user = InlineKeyboardMarkup()
            markup_user.add(InlineKeyboardButton("👤 Профиль", callback_data="menu_profile"))
            markup_user.add(InlineKeyboardButton("🏠 Главное меню", callback_data="menu_start"))
            
            if user_id in last_bot_msg and last_bot_msg[user_id]:
                try:
                    await call.bot.delete_message(user_id, last_bot_msg[user_id])
                except:
                    pass
            
            msg = await call.bot.send_photo(
                user_id,
                PHOTO_FILE_ID,
                caption=reject_text,
                reply_markup=markup_user,
                parse_mode="HTML"
            )
            last_bot_msg[user_id] = msg.message_id
        except Exception as e:
            logger.error(f"Не смог отправить отказ юзеру {user_id}: {e}")
        
        # Update admin message
        try:
            status_line = f"\n\n❌ <b>ОТКЛОНЕНО:</b> {nickname}"
            new_caption = (call.message.caption or call.message.text or "") + status_line
            
            if call.message.caption:
                await call.message.edit_caption(caption=new_caption, parse_mode="HTML")
            else:
                await call.message.edit_text(text=new_caption, parse_mode="HTML")
        except:
            pass
        
        await call.answer("❌ Отклонено")
