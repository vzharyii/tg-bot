"""
Callback handlers module
Handles all callback query handlers
"""

import logging
import asyncio
from aiogram import types, Bot
from aiogram.dispatcher import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from bot.config import ADMIN_ID, PHOTO_FILE_ID, API_TOKEN
from bot.models.states import AdminStates, UserStates
from bot.models.cache import banned_cache, last_bot_msg, pending_cache, access_cache_set, access_cache_remove
from bot.database.connection import check_db_ready, db_execute_with_retry, db_fetch_with_retry
from bot.database.queries import get_access_nickname
from bot.middleware.security import ban_user_system
from bot.utils.ui import send_ui
from bot.utils.helpers import delete_after_delay

logger = logging.getLogger(__name__)


def register_callback_handlers(dp):
    """Register all callback query handlers"""
    
    # --- REJECTION FLOW ---
    
    @dp.callback_query_handler(lambda c: c.data.startswith("pre_no:"), state="*")
    async def process_reject_start(call: types.CallbackQuery, state: FSMContext):
        """Start rejection process"""
        _, nick, uid = call.data.split(":")
        admin_msg_text = call.message.caption or call.message.text or ""
        is_caption = bool(call.message.caption)
        await state.update_data(
            target_nick=nick,
            target_uid=int(uid),
            mid=call.message.message_id,
            admin_msg_text=admin_msg_text,
            admin_msg_is_caption=is_caption
        )
        await AdminStates.waiting_for_rejection_reason.set()
        await call.message.answer(f"⌨️ Введите причину отказа для `{nick}`:", parse_mode="Markdown")
        await call.answer()

    @dp.message_handler(state=AdminStates.waiting_for_rejection_reason)
    async def process_reject_reason(message: types.Message, state: FSMContext):
        """Process rejection reason"""
        data = await state.get_data()
        target_uid = data['target_uid']
        target_nick = data['target_nick']
        reason = message.text.strip()
        
        # Remove application from DB
        delete_success = await db_execute_with_retry(
            "DELETE FROM access_list WHERE tg_user_id=%s AND nickname=%s",
            (target_uid, target_nick),
            action_desc="Ошибка удаления заявки"
        )
        if not delete_success:
            logger.error("Не удалось удалить заявку из БД после повторов.")
        access_cache_remove(target_uid)
        
        # Send rejection notification to user
        try:
            reject_text = (
                f"❌ <b>Отказ в доступе</b>\n\n"
                f"🎮 <b>Ник:</b> <code>{target_nick}</code>\n"
                f"📝 <b>Причина:</b> {reason}\n\n"
                f"💡 Вы можете подать заявку повторно, устранив указанные замечания."
            )
            markup_user = InlineKeyboardMarkup(row_width=2)
            markup_user.row(
                InlineKeyboardButton("📝 Подать заявку", callback_data="menu_apply"),
                InlineKeyboardButton("🏠 Главное меню", callback_data="menu_start")
            )
            
            # Delete old user message if exists
            if target_uid in last_bot_msg and last_bot_msg[target_uid]:
                try:
                    await message.bot.delete_message(target_uid, last_bot_msg[target_uid])
                except:
                    pass
            
            # Send new message with photo
            msg = await message.bot.send_photo(
                target_uid, 
                PHOTO_FILE_ID, 
                caption=reject_text, 
                reply_markup=markup_user, 
                parse_mode="HTML"
            )
            last_bot_msg[target_uid] = msg.message_id
        except Exception as e:
            logger.error(f"Не смог отправить отказ юзеру {target_uid}: {e}")
        
        # Update admin message
        try:
            admin_msg_id = data['mid']
            status_line = f"\n\n❌ <b>ОТКАЗАНО:</b> {target_nick}\n📝 {reason}"
            admin_msg_text = data.get('admin_msg_text', "")
            is_caption = data.get('admin_msg_is_caption', False)
            
            if is_caption:
                await message.bot.edit_message_caption(
                    chat_id=ADMIN_ID,
                    message_id=admin_msg_id,
                    caption=admin_msg_text + status_line,
                    parse_mode="HTML",
                    reply_markup=None
                )
            else:
                await message.bot.edit_message_text(
                    chat_id=ADMIN_ID,
                    message_id=admin_msg_id,
                    text=admin_msg_text + status_line,
                    parse_mode="HTML",
                    reply_markup=None
                )
        except Exception as e:
            logger.error(f"Не смог обновить сообщение админа: {e}")
        
        await message.reply("✅ Отказ отправлен")
        await state.finish()

    # --- BAN FLOW ---
    
    @dp.callback_query_handler(text_startswith="pre_ban:", state="*")
    async def cb_pre_ban(call: types.CallbackQuery):
        """Confirm ban action"""
        _, nick, uid = call.data.split(":")
        
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(
            InlineKeyboardButton("⚠️ ДА, В БАН", callback_data=f"confirm_ban:{uid}"),
            InlineKeyboardButton("🔙 Нет, назад", callback_data=f"cancel_ban:{nick}:{uid}")
        )
        await call.message.edit_reply_markup(reply_markup=markup)
        await call.answer()

    @dp.callback_query_handler(text_startswith="cancel_ban:", state="*")
    async def cb_cancel_ban(call: types.CallbackQuery):
        """Cancel ban, restore original buttons"""
        _, nick, uid = call.data.split(":")
        
        markup = InlineKeyboardMarkup(row_width=3)
        markup.add(
            InlineKeyboardButton("✅ Принять", callback_data=f"yes:{nick}:{uid}"),
            InlineKeyboardButton("❌ Отказать", callback_data=f"pre_no:{nick}:{uid}"),
            InlineKeyboardButton("🚫 БАН", callback_data=f"pre_ban:{nick}:{uid}")
        )
        await call.message.edit_reply_markup(reply_markup=markup)
        await call.answer()

    @dp.callback_query_handler(text_startswith="confirm_ban:", state="*")
    async def cb_confirm_ban(call: types.CallbackQuery, state: FSMContext):
        """Confirm ban and request reason"""
        if call.from_user.id != ADMIN_ID:
            return
            
        uid = int(call.data.split(":")[1])
        
        # Save ban info and request reason
        is_caption = bool(call.message.caption)
        await state.update_data(ban_uid=uid, ban_mid=call.message.message_id, ban_is_caption=is_caption)
        await AdminStates.waiting_for_ban_reason.set()
        
        markup = InlineKeyboardMarkup().add(InlineKeyboardButton("Отмена", callback_data="cancel_admin_action"))
        prompt_text = f"🚫 <b>Бан пользователя {uid}</b>\n\n📝 Введите причину бана:"
        if call.message.caption:
            await call.message.edit_caption(caption=prompt_text, reply_markup=markup, parse_mode="HTML")
        else:
            await call.message.edit_text(prompt_text, reply_markup=markup, parse_mode="HTML")
        await call.answer()

    @dp.callback_query_handler(text="cancel_admin_action", state=AdminStates.waiting_for_ban_reason)
    async def cb_cancel_ban_reason(call: types.CallbackQuery, state: FSMContext):
        """Cancel ban action"""
        await state.finish()
        text = "🚫 Бан отменен."
        if call.message.caption:
            await call.message.edit_caption(caption=text, reply_markup=None)
        else:
            await call.message.edit_text(text, reply_markup=None)
        await call.answer()

    @dp.message_handler(state=AdminStates.waiting_for_ban_reason)
    async def process_ban_reason_text(message: types.Message, state: FSMContext):
        """Process ban reason and execute ban"""
        reason = message.text
        data = await state.get_data()
        
        # Support both button ban (ban_uid) and command ban (manual_ban_uid)
        uid = data.get('ban_uid') or data.get('manual_ban_uid')
        mid = data.get('ban_mid')  # May be None for command ban
        
        # Ban user!
        await ban_user_system(uid, f"User {uid}", None, reason)
        
        # Update message with buttons (if any - for button ban)
        if mid:
            is_caption = data.get('ban_is_caption', False)
            text = f"🚫 <b>ПОЛЬЗОВАТЕЛЬ ЗАБАНЕН</b> (ID: {uid})\n📝 Причина: {reason}"
        if mid:
            is_caption = data.get('ban_is_caption', False)
            text = f"🚫 <b>ПОЛЬЗОВАТЕЛЬ ЗАБАНЕН</b> (ID: {uid})\n📝 Причина: {reason}"
            try:
                if is_caption:
                    await message.bot.edit_message_caption(chat_id=ADMIN_ID, message_id=mid, caption=text, parse_mode="HTML")
                else:
                    await message.bot.edit_message_text(text, chat_id=ADMIN_ID, message_id=mid, parse_mode="HTML")
            except:
                pass
        
        await message.reply(f"✅ Забанен: {uid}")
        await state.finish()

    # --- SCRIPT SUGGESTION FLOW ---
    # Note: Script selection is handled in user.py (cb_menu_suggest, cb_suggest_select_script)
    # This handler processes the actual suggestion text after script is selected
    
    @dp.message_handler(state=AdminStates.waiting_for_suggestion)
    async def process_suggestion_text(message: types.Message, state: FSMContext):
        """Process suggestion submission"""
        data = await state.get_data()
        mid = data.get('suggest_mid')
        script_name = data.get('suggest_script', 'mine')  # Default to 'mine' for backward compatibility
        
        # Get nickname
        nick = await get_access_nickname(message.from_user.id)
        if not nick:
            await message.reply("⚠️ У вас нет активного доступа к скриптам.")
            await state.finish()
            return
        
        text = message.text
        user_id = message.from_user.id
        
        # Script display names
        script_display = {
            'mine': 'Шахты',
            'oskolki': 'Счетчик осколков'
        }
        
        # Save to DB with script_name
        success = await db_execute_with_retry(
            "INSERT INTO suggestions (tg_user_id, nickname, script_name, suggestion_text) VALUES (%s, %s, %s, %s)",
            (user_id, nick, script_name, text),
            action_desc="Ошибка сохранения предложения"
        )
        
        if success:
            # Notify admin with script name
            user_link = f"@{message.from_user.username}" if message.from_user.username else f"<a href='tg://user?id={user_id}'>{message.from_user.full_name}</a>"
            admin_alert = (
                f"💡 <b>НОВОЕ ПРЕДЛОЖЕНИЕ!</b>\n\n"
                f"📜 <b>Скрипт:</b> {script_display.get(script_name, script_name)}\n"
                f"👤 <b>От:</b> {user_link} (Ник: <code>{nick}</code>)\n"
                f"📝 <b>Текст:</b>\n{text}"
            )
            try:
                await message.bot.send_message(ADMIN_ID, admin_alert, parse_mode="HTML")
            except:
                pass
            
            # 1. Delete hint message
            if mid:
                try:
                    await message.bot.delete_message(message.chat.id, mid)
                except:
                    pass
                
            # 2. Show confirmation with action buttons
            from bot.utils.ui import send_ui, get_menu_markup
            
            caption = (
                "✅ <b>Предложение успешно отправлено!</b>\n\n"
                f"📜 <b>Скрипт:</b> {script_display.get(script_name, script_name)}\n"
                "👨‍💻 <b>Статус:</b> Передано разработчику\n\n"
                "Что делаем дальше?"
            )
            
            markup = InlineKeyboardMarkup(row_width=1)
            markup.add(InlineKeyboardButton("💡 Отправить ещё предложение", callback_data="menu_suggest"))
            markup.add(InlineKeyboardButton("🏠 Главное меню", callback_data="menu_start"))
            
            await send_ui(message, caption, markup)
        else:
            await message.reply("❌ Ошибка при сохранении. Попробуйте позже.")
        
        await state.finish()

    # --- SUGGESTIONS VIEWING ---
    
    @dp.callback_query_handler(text="back_to_suggestions", state="*")
    async def cb_back_suggestions(call: types.CallbackQuery):
        """Return to suggestions list"""
        if call.from_user.id != ADMIN_ID:
            return
        await dp.show_suggestions_list(call.message, edit=True)
        await call.answer()

    @dp.callback_query_handler(text_startswith="view_suggest:", state="*")
    async def cb_view_suggestion(call: types.CallbackQuery):
        """View detailed suggestion"""
        if call.from_user.id != ADMIN_ID:
            return
            
        sid = int(call.data.split(":")[1])
        
        row = await db_fetch_with_retry(
            "SELECT nickname, tg_user_id, suggestion_text, created_at FROM suggestions WHERE id = %s",
            (sid,),
            fetch="one",
            action_desc="Ошибка чтения предложения"
        )
        
        if not row:
            return await call.answer("❌ Предложение не найдено", show_alert=True)
        
        nick, uid, stext, dt = row
        text = (
            f"💡 <b>Детали предложения #{sid}</b>\n\n"
            f"👤 <b>От:</b> <code>{nick}</code> (ID: <code>{uid}</code>)\n"
            f"📅 <b>Дата:</b> {dt}\n\n"
            f"📝 <b>Текст:</b>\n{stext}"
        )
        
        markup = InlineKeyboardMarkup().add(
            InlineKeyboardButton("🗑 Удалить", callback_data=f"del_suggest:{sid}"),
            InlineKeyboardButton("🔙 Назад", callback_data="back_to_suggestions")
        )
        
        await call.message.edit_text(text, reply_markup=markup, parse_mode="HTML")

    @dp.callback_query_handler(text_startswith="del_suggest:", state="*")
    async def cb_del_suggestion(call: types.CallbackQuery):
        """Delete a suggestion"""
        if call.from_user.id != ADMIN_ID:
            return
            
        sid = int(call.data.split(":")[1])
        
        await db_execute_with_retry(
            "DELETE FROM suggestions WHERE id = %s",
            (sid,),
            action_desc="Ошибка удаления предложения"
        )
        
        await call.answer("✅ Удалено")
        await cb_back_suggestions(call)

    # --- PENDING LIST NAVIGATION ---
    
    @dp.callback_query_handler(text="pending_list", state="*")
    async def cb_pending_list(call: types.CallbackQuery):
        """Show pending list"""
        if call.from_user.id != ADMIN_ID:
            return
            
        text, markup = await dp.build_pending_list(call.from_user.id)
        try:
            await call.message.edit_text(text, parse_mode="HTML", reply_markup=markup)
        except Exception:
            await call.message.answer(text, parse_mode="HTML", reply_markup=markup)
        await call.answer()

    @dp.callback_query_handler(text_startswith="pending_pick:", state="*")
    async def cb_pending_pick(call: types.CallbackQuery):
        """Pick a pending application to view"""
        if call.from_user.id != ADMIN_ID:
            return
            
        try:
            idx = int(call.data.split(":")[1])
        except ValueError:
            return await call.answer("Неверный номер", show_alert=True)
        
        rows = pending_cache.get(call.from_user.id)
        if not rows or idx < 1 or idx > len(rows):
            await call.answer("Список устарел. Обновляю.", show_alert=True)
            return await cb_pending_list(call)
        
        nick, uid = rows[idx - 1]
        if not uid:
            return await call.answer("У заявки нет ID пользователя", show_alert=True)
            
        text = (
            f"📝 <b>Заявка #{idx}</b>\n\n"
            f"🎮 <b>Ник:</b> <code>{nick}</code>\n"
            f"👤 <b>ID:</b> <code>{uid}</code>\n\n"
            f"Выберите действие:"
        )
        
        markup = InlineKeyboardMarkup(row_width=3)
        markup.add(
            InlineKeyboardButton("✅ Принять", callback_data=f"yes:{nick}:{uid}"),
            InlineKeyboardButton("❌ Отказать", callback_data=f"pre_no:{nick}:{uid}"),
            InlineKeyboardButton("🚫 БАН", callback_data=f"pre_ban:{nick}:{uid}")
        )
        markup.add(InlineKeyboardButton("📋 К списку", callback_data="pending_list"))
        
        try:
            await call.message.edit_text(text, parse_mode="HTML", reply_markup=markup)
        except Exception:
            await call.message.answer(text, parse_mode="HTML", reply_markup=markup)
        await call.answer()

    # --- GENERAL CALLBACKS ---
    
    @dp.callback_query_handler(lambda c: True, state="*")
    async def process_all_callbacks(call: types.CallbackQuery, state: FSMContext):
        """Handle all remaining callback queries"""
        d = call.data
        
        # Approval
        if d.startswith("yes:"):
            from bot.handlers.user import cb_menu_start
            
            _, nick, uid = d.split(":")
            uid = int(uid)
            
            # Respond immediately to avoid "Query is too old"
            try:
                await call.answer("⏳ Обрабатываю...")
            except:
                pass
            
            if not check_db_ready():
                try:
                    await call.message.reply("❌ Ошибка: БД недоступна")
                except:
                    pass
                return
            
            # Update in DB with retries
            success = False
            try:
                upd = await db_execute_with_retry(
                    "UPDATE access_list SET approved=1 WHERE tg_user_id=%s AND nickname=%s",
                    (uid, nick),
                    attempts=3,
                    action_desc="Ошибка обновления статуса заявки"
                )
                if upd:
                    result = await db_fetch_with_retry(
                        "SELECT approved FROM access_list WHERE tg_user_id=%s AND nickname=%s",
                        (uid, nick),
                        fetch="one",
                        attempts=3,
                        action_desc="Ошибка проверки статуса заявки"
                    )
                    if result and result[0] == 1:
                        success = True
            except Exception as e:
                logger.error(f"Ошибка обновления заявки: {e}")
            
            if not success:
                try:
                    await call.message.reply(f"❌ Ошибка БД: не удалось сохранить изменения для {nick}. Проверьте вручную.")
                except:
                    pass
                return
            
            access_cache_set(uid, nick)
            
            # Update admin message
            try:
                current_caption = call.message.caption
                current_text = call.message.text
                
                status_line = f"\n\n✅ <b>ОДОБРЕНО:</b> {nick}"
                
                if current_caption:
                    await call.message.edit_caption(caption=current_caption + status_line, parse_mode="HTML", reply_markup=None)
                elif current_text:
                    await call.message.edit_text(text=current_text + status_line, parse_mode="HTML", reply_markup=None)
                else:
                    await call.message.edit_reply_markup(reply_markup=None)
                    
            except Exception as e:
                logger.error(f"Не смог отредактировать сообщение админа: {e}")
            
            # Notify user
            try:
                success_text = (
                    f"✅ <b>ДОСТУП ВЫДАН!</b>\n\n"
                    f"👤 <b>Ник:</b> <code>{nick}</code>\n\n"
                    f"🚀 Приятной игры! Теперь вам доступны все функции."
                )
                markup_user = InlineKeyboardMarkup().add(InlineKeyboardButton("🏠 Главное меню", callback_data="menu_start"))
                
                if uid in last_bot_msg and last_bot_msg[uid]:
                    try:
                        await call.bot.delete_message(uid, last_bot_msg[uid])
                    except:
                        pass
                
                msg = await call.bot.send_photo(uid, PHOTO_FILE_ID, caption=success_text, reply_markup=markup_user, parse_mode="HTML")
                last_bot_msg[uid] = msg.message_id
            except Exception as e:
                logger.error(f"Не смог уведомить юзера {uid} об одобрении: {e}")
            
            await call.answer("✅ Заявка одобрена!")

        # User self-delete nick
        elif d.startswith("del_my:"):
            nick = d.split(":")[1]
            
            markup = InlineKeyboardMarkup(row_width=2)
            markup.add(
                InlineKeyboardButton("🗑 Да, удалить", callback_data=f"conf_del:{nick}"),
                InlineKeyboardButton("🔙 Нет, назад", callback_data="menu_profile")
            )
            
            await send_ui(call, 
                f"⚠️ <b>Вы уверены, что хотите удалить ник <code>{nick}</code>?</b>\n\n"
                "Вы потеряете доступ к боту и придется подавать заявку заново.", 
                markup
            )
            await call.answer()

        # Confirm delete
        elif d.startswith("conf_del:"):
            from bot.handlers.user import cb_menu_start
            
            nick = d.split(":")[1]
            uid = call.from_user.id
            
            # Answer callback first
            try:
                await call.answer("Ник удален")
            except:
                pass
            
            # Delete from DB
            success = await db_execute_with_retry(
                "DELETE FROM access_list WHERE nickname=%s AND tg_user_id=%s",
                (nick, uid),
                action_desc="Ошибка удаления ника"
            )
            if not success:
                logger.error("Не удалось удалить ник из БД после повторов.")
            access_cache_remove(uid)
            
            # Return to main menu
            await cb_menu_start(call, state)

        # Unban
        elif d.startswith("unban:"):
            if call.from_user.id != ADMIN_ID:
                return
                
            uid = int(d.split(":")[1])
            if uid in banned_cache:
                banned_cache.remove(uid)
                
            await db_execute_with_retry(
                "DELETE FROM banned_users WHERE tg_user_id=%s",
                (uid,),
                action_desc="Ошибка удаления бана"
            )
            await call.message.edit_text(f"✅ Разбанен: {uid}")
            
            try:
                await call.bot.send_message(
                    uid,
                    "✅ <b>Вы разблокированы!</b>\n\nТеперь вы снова можете пользоваться ботом.",
                    parse_mode="HTML"
                )
            except:
                pass

        # Manual ban (legacy)
        elif d.startswith("ban_manual:"):
            if call.from_user.id != ADMIN_ID:
                return
                
            uid = int(d.split(":")[1])
            await ban_user_system(uid, "Manual", "Manual", "Ручной бан")
            await call.message.edit_text(f"🚫 Забанен: {uid}")
