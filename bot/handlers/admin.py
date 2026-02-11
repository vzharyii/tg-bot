"""
Admin handlers module
Handles all admin commands
"""

import logging
from aiogram import types, Bot
from aiogram.dispatcher import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from bot.config import ADMIN_ID, API_TOKEN
from bot.models.states import AdminStates
from bot.models.cache import banned_cache, pending_cache
from bot.database.connection import check_db_ready, db_execute_with_retry, db_fetch_with_retry
from bot.database.queries import get_access_nickname
from bot.middleware.security import ban_user_system
from bot.models.cache import access_cache_remove_by_nick

logger = logging.getLogger(__name__)


def register_admin_handlers(dp):
    """Register all admin command handlers"""
    
    @dp.message_handler(commands=['list'])
    async def cmd_list(message: types.Message):
        """Show list of approved users"""
        if message.from_user.id != ADMIN_ID:
            return
        
        if not check_db_ready():
            return
            
        try:
            # Query for users with valid JSON in approved column
            rows = await db_fetch_with_retry(
                "SELECT nickname, tg_user_id, approved FROM access_list WHERE approved IS NOT NULL AND approved != '0' AND approved != '1'",
                fetch="all",
                action_desc="Ошибка получения списка одобренных"
            )
            if rows is None:
                rows = []
            
            text = "📂 <b>Список пользователей:</b>\n\n"
            if not rows:
                text += "Пусто."
            else:
                for r in rows:
                    nick = r[0]
                    uid = r[1] if r[1] else "N/A"
                    approved_json = r[2]
                    
                    # Parse access
                    import json
                    try:
                        access = json.loads(approved_json) if isinstance(approved_json, str) else approved_json
                        access_str = ""
                        if isinstance(access, dict):
                            parts = []
                            if access.get('mine'): parts.append("⛏")
                            if access.get('oskolki'): parts.append("💎")
                            access_str = " ".join(parts)
                    except:
                        access_str = "❓"
                    
                    # Get user info safely
                    user_link = f"ID: <tg-spoiler>{uid}</tg-spoiler>"
                    try:
                        if uid != "N/A":
                            chat = await message.bot.get_chat(uid)
                            if chat.username:
                                user_link = f"@{chat.username} (ID: <tg-spoiler>{uid}</tg-spoiler>)"
                            else:
                                user_link = f"<a href='tg://user?id={uid}'>{chat.full_name}</a> (ID: <tg-spoiler>{uid}</tg-spoiler>)"
                    except Exception:
                        # If bot doesn't know the user (cleared cache/restart), show just ID
                        pass
                    
                    text += f"• <code>{nick}</code> {access_str} — {user_link}\n"
            
            await message.reply(text, parse_mode="HTML")

        except Exception as e:
            await message.reply(f"Ошибка: {e}")

    @dp.message_handler(commands=['revoke_mine'])
    async def cmd_revoke_mine(message: types.Message):
        """Revoke access to Mine script"""
        if message.from_user.id != ADMIN_ID:
            return
            
        args = message.get_args()
        if not args:
            return await message.reply("⚠️ Использование: `/revoke_mine Nick_Name`", parse_mode="Markdown")
        
        nickname = args.strip()
        
        try:
            # Get current access
            row = await db_fetch_with_retry(
                "SELECT approved, tg_user_id FROM access_list WHERE nickname = %s",
                (nickname,),
                fetch="one",
                action_desc="Ошибка получения прав"
            )
            
            if not row:
                return await message.reply("⚠️ Пользователь не найден")
                
            current_access = row[0]
            user_id = row[1]
            import json
            
            if isinstance(current_access, str):
                try:
                    current_access = json.loads(current_access)
                except:
                    current_access = {}
            elif not isinstance(current_access, dict):
                current_access = {}
                
            # Update access
            current_access['mine'] = False
            new_access_json = json.dumps(current_access)
            
            # Save to DB
            success = await db_execute_with_retry(
                "UPDATE access_list SET approved = %s WHERE nickname = %s",
                (new_access_json, nickname),
                action_desc="Ошибка обновления прав"
            )
            
            if success:
                # Update cache
                from bot.models.cache import access_cache_set
                access_cache_set(user_id, nickname)
                await message.reply(f"✅ Доступ к '⛏ Скрипт Шахты' отозван у пользователя <code>{nickname}</code>", parse_mode="HTML")
            else:
                await message.reply("❌ Ошибка базы данных")
                
        except Exception as e:
            await message.reply(f"Ошибка: {e}")

    @dp.message_handler(commands=['revoke_oskolki'])
    async def cmd_revoke_oskolki(message: types.Message):
        """Revoke access to Oskolki script"""
        if message.from_user.id != ADMIN_ID:
            return
            
        args = message.get_args()
        if not args:
            return await message.reply("⚠️ Использование: `/revoke_oskolki Nick_Name`", parse_mode="Markdown")
        
        nickname = args.strip()
        
        try:
            # Get current access
            row = await db_fetch_with_retry(
                "SELECT approved, tg_user_id FROM access_list WHERE nickname = %s",
                (nickname,),
                fetch="one",
                action_desc="Ошибка получения прав"
            )
            
            if not row:
                return await message.reply("⚠️ Пользователь не найден")
                
            current_access = row[0]
            user_id = row[1]
            import json
            
            if isinstance(current_access, str):
                try:
                    current_access = json.loads(current_access)
                except:
                    current_access = {}
            elif not isinstance(current_access, dict):
                current_access = {}
                
            # Update access
            current_access['oskolki'] = False
            new_access_json = json.dumps(current_access)
            
            # Save to DB
            success = await db_execute_with_retry(
                "UPDATE access_list SET approved = %s WHERE nickname = %s",
                (new_access_json, nickname),
                action_desc="Ошибка обновления прав"
            )
            
            if success:
                # Update cache
                from bot.models.cache import access_cache_set
                access_cache_set(user_id, nickname)
                await message.reply(f"✅ Доступ к '🔮 Счетчик осколков' отозван у пользователя <code>{nickname}</code>", parse_mode="HTML")
            else:
                await message.reply("❌ Ошибка базы данных")
                
        except Exception as e:
            await message.reply(f"Ошибка: {e}")

    async def build_pending_list(admin_id):
        """Build pending applications list"""
        rows = await db_fetch_with_retry(
            "SELECT nickname, tg_user_id FROM access_list WHERE approved=0 OR approved IS NULL",
            fetch="all",
            action_desc="Ошибка получения списка заявок"
        )
        if rows is None:
            rows = []
            
        text = "⏳ <b>Заявки на рассмотрении:</b>\n\n"
        if not rows:
            text += "Нет заявок."
        else:
            pending_cache[admin_id] = rows
            for idx, r in enumerate(rows, start=1):
                nick = r[0]
                uid = r[1] if r[1] else "N/A"
                
                username = None
                if uid != "N/A":
                    try:
                        user = await dp.bot.get_chat(uid)
                        if user.username:
                            username = f"@{user.username}"
                    except:
                        pass
                
                user_info = f"ID: {uid}"
                if username:
                    user_info = f"{username} (ID: {uid})"
                
                text += f"{idx}. <code>{nick}</code> — {user_info}\n"
        
        markup = InlineKeyboardMarkup(row_width=5)
        if rows:
            buttons = []
            for idx in range(1, len(rows) + 1):
                buttons.append(InlineKeyboardButton(str(idx), callback_data=f"pending_pick:{idx}"))
            markup.add(*buttons)
        return text, markup

    @dp.message_handler(commands=['pending'])
    async def cmd_pending(message: types.Message):
        """Show pending applications"""
        if message.from_user.id != ADMIN_ID:
            return
        
        if not check_db_ready():
            return
            
        try:
            text, markup = await build_pending_list(message.from_user.id)
            await message.reply(text, parse_mode="HTML", reply_markup=markup)

        except Exception as e:
            await message.reply(f"Ошибка: {e}")

    @dp.message_handler(commands=['banned'])
    async def cmd_banned(message: types.Message):
        """Show list of banned users"""
        if message.from_user.id != ADMIN_ID:
            return
        
        if not check_db_ready():
            return
            
        try:
            rows = await db_fetch_with_retry(
                "SELECT tg_user_id, reason FROM banned_users",
                fetch="all",
                action_desc="Ошибка получения списка банов"
            )
            if rows is None:
                rows = []
            
            text = "🚫 <b>Список забаненных:</b>\n\n"
            if not rows:
                text += "Нет забаненных."
            else:
                for r in rows:
                    uid = r[0]
                    reason = r[1] if r[1] else "Не указана"
                    
                    # Get username and fullname
                    username = None
                    fullname = f"User {uid}"
                    try:
                        user = await message.bot.get_chat(uid)
                        fullname = user.full_name or f"User {uid}"
                        if user.username:
                            username = f"@{user.username}"
                    except:
                        pass
                    
                    user_info = f"{username} (ID: {uid})" if username else f"{fullname} (ID: {uid})"
                    
                    text += f"• {user_info}\n  📝 Причина: {reason}\n"
            
            await message.reply(text, parse_mode="HTML")

        except Exception as e:
            await message.reply(f"Ошибка: {e}")

    @dp.message_handler(commands=['add'])
    async def cmd_manual_add(message: types.Message):
        """Manually add a nick to access list"""
        if message.from_user.id != ADMIN_ID:
            return
            
        args = message.get_args()
        if not args:
            return await message.reply("⚠️ Введите ник: `/add Nick_Name`", parse_mode="Markdown")
        
        if not check_db_ready():
            return await message.reply("БД офф.")
            
        try:
            success = await db_execute_with_retry(
                "INSERT INTO access_list (nickname, approved) VALUES (%s, 1)",
                (args,),
                action_desc="Ошибка ручного добавления"
            )
            if not success:
                return await message.reply("❌ Не удалось добавить в БД. Попробуйте позже.")
            await message.reply(f"✅ Добавил: {args}")
        except Exception as e:
            await message.reply(f"Ошибка: {e}")

    @dp.message_handler(commands=['del'])
    async def cmd_manual_del(message: types.Message):
        """Manually delete a nick from access list"""
        if message.from_user.id != ADMIN_ID:
            return
            
        args = message.get_args()
        if not args:
            return await message.reply("⚠️ Введите ник: `/del Nick_Name`", parse_mode="Markdown")

        if not check_db_ready():
            return await message.reply("БД офф.")
            
        try:
            success = await db_execute_with_retry(
                "DELETE FROM access_list WHERE nickname=%s",
                (args,),
                action_desc="Ошибка удаления ника"
            )
            if not success:
                return await message.reply("❌ Не удалось удалить из БД. Попробуйте позже.")
            access_cache_remove_by_nick(args)
            await message.reply(f"🗑 Удалил: {args}")
        except Exception as e:
            await message.reply(f"Ошибка: {e}")

    @dp.message_handler(commands=['ban'])
    async def cmd_ban(message: types.Message, state: FSMContext):
        """Ban a user"""
        if message.from_user.id != ADMIN_ID:
            return
            
        args = message.get_args()
        if not args:
            return await message.reply("⚠️ Использование: `/ban USER_ID`", parse_mode="Markdown")
        
        try:
            uid = int(args)
            if uid in banned_cache:
                return await message.reply("⚠️ Пользователь уже забанен")
            
            # Save ID and request reason
            await state.update_data(manual_ban_uid=uid)
            await AdminStates.waiting_for_ban_reason.set()
            
            markup = InlineKeyboardMarkup().add(InlineKeyboardButton("❌ Отмена", callback_data="cancel_admin_action"))
            await message.reply(f"🚫 <b>Бан пользователя {uid}</b>\n\n📝 Введите причину бана:", reply_markup=markup, parse_mode="HTML")
        except ValueError:
            await message.reply("⚠️ ID должен быть числом")

    @dp.message_handler(commands=['unban'])
    async def cmd_unban(message: types.Message):
        """Unban a user"""
        if message.from_user.id != ADMIN_ID:
            return
            
        args = message.get_args()
        if not args:
            return await message.reply("⚠️ Использование: `/unban USER_ID`", parse_mode="Markdown")
        
        try:
            uid = int(args)
            
            if uid not in banned_cache:
                return await message.reply("⚠️ Пользователь не в бане")
            
            banned_cache.remove(uid)
            
            await db_execute_with_retry(
                "DELETE FROM banned_users WHERE tg_user_id=%s",
                (uid,),
                action_desc="Ошибка удаления бана"
            )
            
            # Notify unbanned user
            try:
                await message.bot.send_message(uid, "✅ <b>Вы разблокированы!</b>\n\nТеперь вы снова можете пользоваться ботом.", parse_mode="HTML")
            except:
                pass
            
            await message.reply(f"✅ Разбанен: {uid}")
        except ValueError:
            await message.reply("⚠️ ID должен быть числом")
        except Exception as e:
            await message.reply(f"❌ Ошибка: {e}")

    async def show_suggestions_list(message: types.Message, edit=False):
        """Show suggestions list"""
        rows = await db_fetch_with_retry(
            "SELECT id, nickname, suggestion_text FROM suggestions ORDER BY created_at DESC",
            fetch="all",
            action_desc="Ошибка получения предложений"
        )
        
        if not rows:
            text = "📭 Предложений пока нет."
            if edit:
                await message.edit_text(text)
            else:
                await message.reply(text)
            return
        
        text = "💡 <b>Предложения по скриптам:</b>\n\n"
        markup = InlineKeyboardMarkup(row_width=5)
        
        btns = []
        for i, row in enumerate(rows, 1):
            sid, nick, stext = row
            short_text = (stext[:30] + '...') if len(stext) > 30 else stext
            text += f"{i}. <b>{nick}</b>: {short_text}\n"
            btns.append(InlineKeyboardButton(str(i), callback_data=f"view_suggest:{sid}"))
        
        for i in range(0, len(btns), 5):
            markup.row(*btns[i:i+5])
            
        if edit:
            await message.edit_text(text, reply_markup=markup, parse_mode="HTML")
        else:
            await message.reply(text, reply_markup=markup, parse_mode="HTML")

    @dp.message_handler(commands=['suggestions'])
    async def cmd_suggestions(message: types.Message):
        """Show user suggestions"""
        if message.from_user.id != ADMIN_ID:
            return
        await show_suggestions_list(message, edit=False)

    # File ID getters
    @dp.message_handler(commands=['getphoto'], state="*")
    async def cmd_get_photo_id(message: types.Message, state: FSMContext):
        """Get file_id of a photo"""
        if message.from_user.id != ADMIN_ID:
            return
        
        await AdminStates.waiting_for_photo.set()
        markup = InlineKeyboardMarkup().add(InlineKeyboardButton("❌ Отмена", callback_data="cancel_admin_action"))
        await message.reply(
            "📸 <b>Получение file_id картинки</b>\n\n"
            "Отправь мне картинку, и я пришлю её file_id.",
            reply_markup=markup,
            parse_mode="HTML"
        )

    @dp.message_handler(content_types=['photo'], state=AdminStates.waiting_for_photo)
    async def process_photo_for_id(message: types.Message, state: FSMContext):
        """Process photo and return file_id"""
        file_id = message.photo[-1].file_id  # Highest quality
        
        await message.reply(f"<code>{file_id}</code>", parse_mode="HTML")
        await state.finish()

    @dp.message_handler(commands=['getfile'], state="*")
    async def cmd_get_file_id(message: types.Message, state: FSMContext):
        """Get file_id of a document"""
        if message.from_user.id != ADMIN_ID:
            return
        
        await AdminStates.waiting_for_file.set()
        markup = InlineKeyboardMarkup().add(InlineKeyboardButton("❌ Отмена", callback_data="cancel_admin_action"))
        await message.reply(
            "📄 <b>Получение file_id файла</b>\n\n"
            "Отправь мне документ (файл), и я пришлю его file_id.",
            reply_markup=markup,
            parse_mode="HTML"
        )

    @dp.message_handler(content_types=['document'], state=AdminStates.waiting_for_file)
    async def process_file_for_id(message: types.Message, state: FSMContext):
        """Process document and return file_id"""
        file_id = message.document.file_id
        
        await message.reply(f"<code>{file_id}</code>", parse_mode="HTML")
        await state.finish()

    # Export show_suggestions_list for use in callbacks
    dp.show_suggestions_list = show_suggestions_list
    dp.build_pending_list = build_pending_list
    @dp.message_handler(commands=['broadcast'])
    async def cmd_broadcast(message: types.Message):
        """Start broadcast process"""
        if message.from_user.id != ADMIN_ID:
            return
            
        await AdminStates.waiting_for_broadcast_target.set()
        markup = InlineKeyboardMarkup()
        markup.row(
            InlineKeyboardButton("📢 Всем", callback_data="bc_target_all"),
            InlineKeyboardButton("👤 Выбрать пользователей", callback_data="bc_target_select")
        )
        markup.add(InlineKeyboardButton("❌ Отмена", callback_data="broadcast_cancel"))
        await message.reply("📢 <b>Рассылка</b>\n\nКому вы хотите отправить сообщение?", reply_markup=markup, parse_mode="HTML")

    @dp.callback_query_handler(text="broadcast_cancel", state="*")
    async def cb_broadcast_cancel(call: types.CallbackQuery, state: FSMContext):
        """Cancel broadcast"""
        current_state = await state.get_state()
        if not current_state:
            return
        await state.finish()
        
        try:
            await call.message.delete()
        except:
            await call.message.edit_reply_markup(reply_markup=None)
            
        await call.message.answer("❌ Рассылка отменена.")
        await call.answer()

    @dp.callback_query_handler(text="bc_target_all", state=AdminStates.waiting_for_broadcast_target)
    async def cb_bc_target_all(call: types.CallbackQuery, state: FSMContext):
        """Select ALL users target"""
        await AdminStates.waiting_for_broadcast_msg.set()
        await state.update_data(broadcast_target="all")
        await call.message.edit_text("📢 <b>Рассылка (Всем)</b>\n\nОтправьте сообщение, которое нужно разослать (текст или фото с подписью).", parse_mode="HTML")

    @dp.callback_query_handler(text="bc_target_select", state=AdminStates.waiting_for_broadcast_target)
    async def cb_bc_target_select(call: types.CallbackQuery, state: FSMContext):
        """Start user selection"""
        if not check_db_ready():
            await call.answer("БД недоступна", show_alert=True)
            return

        users = await db_fetch_with_retry(
            "SELECT tg_user_id, nickname FROM access_list WHERE approved IS NOT NULL AND approved != '0'", 
            fetch="all"
        )
        
        if not users:
            await call.answer("Нет доступных пользователей", show_alert=True)
            return
            
        # Store users map for quick access {id: nick}
        users_map = {u[0]: u[1] for u in users}
        
        await AdminStates.waiting_for_broadcast_users.set()
        await state.update_data(
            broadcast_target="select", 
            all_users_map=users_map, # Save map to avoid re-fetching
            selected_ids=[] # Start empty
        )
        
        await render_broadcast_users_keyboard(call, users_map, [])

    async def render_broadcast_users_keyboard(call: types.CallbackQuery, users_map, selected_ids):
        """Helper to render user selection keyboard"""
        markup = InlineKeyboardMarkup(row_width=2)
        
        # Add user checkboxes
        buttons = []
        for uid, nick in users_map.items():
            is_selected = uid in selected_ids
            mark = "✅" if is_selected else "⬜"
            buttons.append(InlineKeyboardButton(f"{mark} {nick}", callback_data=f"bc_u_{uid}"))
            
        markup.add(*buttons)
        
        # Control buttons
        markup.row(
            InlineKeyboardButton("✅ Готово", callback_data="bc_users_done"),
            InlineKeyboardButton("❌ Отмена", callback_data="broadcast_cancel")
        )
        
        text = f"👤 <b>Выбор получателей</b>\nВыбрано: {len(selected_ids)}"
        
        # Try edit, if fail (same content) - ignore
        try:
            await call.message.edit_text(text, reply_markup=markup, parse_mode="HTML")
        except:
            pass

    @dp.callback_query_handler(text_startswith="bc_u_", state=AdminStates.waiting_for_broadcast_users)
    async def cb_broadcast_user_toggle(call: types.CallbackQuery, state: FSMContext):
        """Toggle user selection"""
        uid = int(call.data.split("_")[2])
        data = await state.get_data()
        selected_ids = data.get("selected_ids", [])
        users_map = data.get("all_users_map", {})
        
        if uid in selected_ids:
            selected_ids.remove(uid)
        else:
            selected_ids.append(uid)
            
        await state.update_data(selected_ids=selected_ids)
        await render_broadcast_users_keyboard(call, users_map, selected_ids)
        await call.answer()

    @dp.callback_query_handler(text="bc_users_done", state=AdminStates.waiting_for_broadcast_users)
    async def cb_bc_users_done(call: types.CallbackQuery, state: FSMContext):
        """Finish user selection"""
        data = await state.get_data()
        selected_ids = data.get("selected_ids", [])
        users_map = data.get("all_users_map", {})
        
        if not selected_ids:
            await call.answer("⚠ Выберите хотя бы одного пользователя!", show_alert=True)
            return
            
        # Get names safely checking both int and str keys (FSM/JSON quirk)
        def get_name(uid):
            return users_map.get(uid) or users_map.get(str(uid)) or str(uid)
            
        names_str = ", ".join([get_name(uid) for uid in selected_ids])
        
        await AdminStates.waiting_for_broadcast_msg.set()
        await call.message.edit_text(
            f"📢 <b>Рассылка (Выбрано: {names_str})</b>\n\nОтправьте сообщение (текст или фото).", 
            parse_mode="HTML"
        )

    @dp.message_handler(content_types=[types.ContentType.TEXT, types.ContentType.PHOTO, types.ContentType.DOCUMENT], state=AdminStates.waiting_for_broadcast_msg)
    async def process_broadcast_msg(message: types.Message, state: FSMContext):
        """Process broadcast message content"""
        # Save message data to state
        broadcast_text = message.caption if (message.photo or message.document) else message.text
        
        broadcast_photo = None
        broadcast_document = None
        
        if message.photo:
            broadcast_photo = message.photo[-1].file_id
        elif message.document:
            broadcast_document = message.document.file_id
        
        data = await state.get_data()
        target_type = data.get("broadcast_target", "all")
        selected_ids = data.get("selected_ids", [])
        users_map = data.get("all_users_map", {})
        
        if target_type == "all":
            target_str = "Всем"
        else:
            def get_name(uid):
                return users_map.get(uid) or users_map.get(str(uid)) or str(uid)
            names = [get_name(uid) for uid in selected_ids]
            target_str = ", ".join(names)
        
        await state.update_data(
            broadcast_text=broadcast_text,
            broadcast_photo=broadcast_photo,
            broadcast_document=broadcast_document
        )
        
        # Confirmation keyboard
        markup = InlineKeyboardMarkup()
        markup.add(
            InlineKeyboardButton(f"✅ Отправить", callback_data="broadcast_send"),
            InlineKeyboardButton("❌ Отмена", callback_data="broadcast_cancel")
        )
        
        preview_header = f"📢 <b>Предпросмотр (Получатели: {target_str}):</b>\n\n"
        
        # Show preview
        if broadcast_photo:
            await message.answer_photo(
                broadcast_photo,
                caption=f"{preview_header}{broadcast_text if broadcast_text else ''}",
                parse_mode="HTML",
                reply_markup=markup
            )
        elif broadcast_document:
            await message.answer_document(
                broadcast_document,
                caption=f"{preview_header}{broadcast_text if broadcast_text else ''}",
                parse_mode="HTML",
                reply_markup=markup
            )
        else:
            await message.answer(
                f"{preview_header}{broadcast_text}",
                parse_mode="HTML",
                reply_markup=markup
            )

    @dp.callback_query_handler(text="broadcast_send", state=AdminStates.waiting_for_broadcast_msg)
    async def cb_broadcast_send(call: types.CallbackQuery, state: FSMContext):
        """Execute broadcast"""
        data = await state.get_data()
        text = data.get('broadcast_text')
        photo = data.get('broadcast_photo')
        document = data.get('broadcast_document')
        target_type = data.get("broadcast_target", "all")
        
        await state.finish()
        await call.message.edit_reply_markup(reply_markup=None)
        status_msg = await call.message.reply("⏳ Начинаю рассылку...")
        
        recipients = []
        
        try:
            if target_type == "all":
                 # Fetch all users
                rows = await db_fetch_with_retry(
                    "SELECT tg_user_id FROM access_list",
                    fetch="all",
                    action_desc="Broadcast user fetch"
                )
                if rows:
                    recipients = [r[0] for r in rows]
            else:
                # Use selected ids
                recipients = data.get("selected_ids", [])
        except Exception as e:
            await status_msg.edit_text(f"❌ Ошибка БД: {e}")
            return

        if not recipients:
            await status_msg.edit_text("❌ Нет получателей для рассылки.")
            return
            
        count_ok = 0
        count_fail = 0
        
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("🏠 Главное меню", callback_data="menu_start"))
        
        import asyncio
        for uid in recipients:
            try:
                if photo:
                    await call.bot.send_photo(uid, photo, caption=text, parse_mode="HTML", reply_markup=markup)
                elif document:
                    await call.bot.send_document(uid, document, caption=text, parse_mode="HTML", reply_markup=markup)
                else:
                    await call.bot.send_message(uid, text, parse_mode="HTML", reply_markup=markup)
                count_ok += 1
            except Exception:
                count_fail += 1
            
            await asyncio.sleep(0.05) # Flood limit prevention
            
        await status_msg.edit_text(
            f"✅ <b>Рассылка завершена!</b>\n"
            f"🎯 Цель: {target_type}\n"
            f"📤 Успешно: {count_ok}\n"
            f"❌ Ошибок: {count_fail}",
            parse_mode="HTML"
        )
