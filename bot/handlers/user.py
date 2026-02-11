"""
User handlers module
Handles user-facing commands and menus
"""

import logging
import asyncio
from aiogram import types
from aiogram.dispatcher import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from bot.config import ADMIN_ID, PHOTO_FILE_ID, MINE_SCRIPT_BANNER_ID, MINE_SCRIPT_FILE_ID
from bot.models.cache import banned_cache, last_bot_msg
from bot.models.states import UserStates, AdminStates
from bot.database.connection import check_db_ready
from bot.database.queries import get_access_nickname
from bot.utils.ui import send_ui, get_menu_markup, get_help_text
from bot.middleware.security import check_user_status

logger = logging.getLogger(__name__)


def register_user_handlers(dp):
    """Register all user command handlers"""
    
    @dp.message_handler(commands=['help'], state="*")
    async def cmd_help(message: types.Message):
        """Show help information"""
        if message.from_user.id in banned_cache:
            return
        
        text = get_help_text(message.from_user.id)
        
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("🏠 Главное меню", callback_data="menu_start"))
        
        await send_ui(message, text, markup)

    @dp.message_handler(commands=['start'], state="*")
    async def cmd_start(message: types.Message, state: FSMContext):
        """Show main menu"""
        await state.finish()
        
        # If banned - show special screen
        if message.from_user.id in banned_cache:
            ban_screen_text = (
                f"🚫 <b>Ваш аккаунт заблокирован</b>\n\n"
                f"👋 Привет, {message.from_user.first_name}!\n\n"
                f"К сожалению, ваш доступ к боту заблокирован.\n"
                f"Если считаете это ошибкой, вы можете подать обжалование:"
            )
            markup = InlineKeyboardMarkup()
            markup.add(InlineKeyboardButton("⚖️ Обжаловать бан", callback_data="appeal_ban"))
            await send_ui(message, ban_screen_text, markup)
            return
        
        caption = (
            f"👋 <b>Привет, {message.from_user.first_name}!</b>\n\n"
            "🤖 <b>Magic Bot</b> — твой помощник для получения доступа к скриптам.\n\n"
            "💎 <b>Возможности бота:</b>\n"
            "🛡 <b>Система доступа:</b> Принимает заявку и после одобрения дает возможность скачивание скрипта с уже активным к нему доступом.\n"
            "📜 <b>Библиотека скриптов:</b>\n"
            "   ├ ⛏ <b>Скрипт Шахты</b> — подсчет ресурсов, таймеры и полезные утилиты.\n"
            "   └ 🔮 <b>Счетчик Осколков</b> — лог дропа со скинов/домов и напоминание о квесте на X4.\n\n"
            "<i>ℹ️ Файлы и инструкции станут доступны автоматически после одобрения заявки.</i>\n\n"
            "👇 <b>Главное меню:</b>"
            )

        markup = await get_menu_markup(message.from_user.id)
        await send_ui(message, caption, markup)

    @dp.message_handler(commands=['profile'], state="*")
    async def cmd_profile(message: types.Message, state: FSMContext):
        """Show user profile"""
        await show_profile_logic(message, state)

    @dp.message_handler(commands=['addmy'], state="*")
    async def cmd_addmy(message: types.Message, state: FSMContext):
        """Legacy command - redirect to UI"""
        await send_ui(message, "⚠️ Команда устарела. Используйте меню /start")

    # Menu callbacks
    @dp.callback_query_handler(text="menu_start", state="*")
    async def cb_menu_start(call: types.CallbackQuery, state: FSMContext):
        """Return to main menu"""
        await state.finish()
        
        # Delete script file if it was sent (in background, non-blocking)
        file_msg_id = last_bot_msg.get(f"{call.from_user.id}_file")
        if file_msg_id:
            async def delete_file():
                try:
                    await call.bot.delete_message(call.from_user.id, file_msg_id)
                    del last_bot_msg[f"{call.from_user.id}_file"]
                except:
                    pass
            asyncio.create_task(delete_file())
        
        caption = (
            f"👋 <b>Привет, {call.from_user.first_name}!</b>\n\n"
            "🤖 <b>Magic Bot</b> — твой помощник для получения доступа к скриптам.\n\n"
            "💎 <b>Возможности бота:</b>\n"
            "🛡 <b>Система доступа:</b> Принимает заявку и после одобрения дает возможность скачивание скрипта с уже активным к нему доступом.\n"
            "📜 <b>Библиотека скриптов:</b>\n"
            "   ├ ⛏ <b>Скрипт Шахты</b> — подсчет ресурсов, таймеры и полезные утилиты.\n"
            "   └ 🔮 <b>Счетчик Осколков</b> — лог дропа со скинов/домов и напоминание о квесте на X4.\n\n"
            "<i>ℹ️ Файлы и инструкции станут доступны автоматически после одобрения заявки.</i>\n\n"
            "👇 <b>Главное меню:</b>"
            )
        markup = await get_menu_markup(call.from_user.id)
        await send_ui(call, caption, markup)

    @dp.callback_query_handler(text="menu_help", state="*")
    async def cb_menu_help(call: types.CallbackQuery):
        """Show help"""
        text = get_help_text(call.from_user.id)
        
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("🏠 Главное меню", callback_data="menu_start"))
        
        await send_ui(call, text, markup)

    @dp.callback_query_handler(text="menu_profile", state="*")
    async def cb_menu_profile(call: types.CallbackQuery, state: FSMContext):
        """Show profile"""
        await show_profile_logic(call, state)

    @dp.callback_query_handler(text="menu_scripts", state="*")
    async def cb_menu_scripts(call: types.CallbackQuery, state: FSMContext):
        """Show scripts menu"""
        # Delete script file if it was sent
        file_msg_id = last_bot_msg.get(f"{call.from_user.id}_file")
        if file_msg_id:
            async def delete_file():
                try:
                    await call.bot.delete_message(call.from_user.id, file_msg_id)
                    del last_bot_msg[f"{call.from_user.id}_file"]
                except:
                    pass
            asyncio.create_task(delete_file())
        
        # Get user's accessible scripts
        from bot.utils.access_control import get_user_accessible_scripts
        accessible_scripts = await get_user_accessible_scripts(call.from_user.id)
        
        if not accessible_scripts:
            # User has no access to any scripts
            caption = (
                "📜 <b>Скрипты</b>\n\n"
                "❌ У вас пока нет доступа ни к одному скрипту.\n\n"
                "Вы можете запросить доступ через профиль."
            )
            markup = InlineKeyboardMarkup()
            markup.add(InlineKeyboardButton("👤 Профиль", callback_data="menu_profile"))
            markup.add(InlineKeyboardButton("🏠 Главное меню", callback_data="menu_start"))
            await send_ui(call, caption, markup)
            await call.answer()
            return
        
        caption = (
            "📜 <b>Доступные скрипты:</b>\n\n"
            "Выберите нужный скрипт из списка:"
        )
        markup = InlineKeyboardMarkup(row_width=2)
        
        # Add buttons only for accessible scripts
        buttons = []
        if 'mine' in accessible_scripts:
            buttons.append(InlineKeyboardButton("⛏ Скрипт Шахты", callback_data="script_mine"))
        if 'oskolki' in accessible_scripts:
            buttons.append(InlineKeyboardButton("🔮 Счетчик Осколков", callback_data="script_oskolki"))
        
        if buttons:
            markup.row(*buttons)
        
        markup.add(InlineKeyboardButton("🏠 Главное меню", callback_data="menu_start"))
        await send_ui(call, caption, markup)
        await call.answer()

    @dp.callback_query_handler(text="script_mine", state="*")
    async def cb_script_mine(call: types.CallbackQuery):
        """Script card for 'Mine'"""
        # Check access
        from bot.database.queries import has_script_access
        if not await has_script_access(call.from_user.id, 'mine'):
            await call.answer("❌ У вас нет доступа к этому скрипту!", show_alert=True)
            return
        
        caption = (
            "⛏ <b>Скрипт Шахты</b>\n\n"
            "💎 <b>Главные возможности:</b>\n"
            "• 📊 <b>Статистика ресурсов</b> — детальный учет добычи по дням (общая/удвоенные/МайнСкелет)\n"
            "• ⏰ <b>Умные таймеры</b> — отслеживание завалов, спавна ресурсов, автоармора\n"
            "• 🎯 <b>Автостарт</b> — скрипт включается автоматически при заходе на шахту\n"
            "• 📱 <b>HUD-панель</b> — ХП/Армор, розыск, тайм еры прямо на экране\n"
            "• ⌨️ <b>Команды</b> — /shh, /resic, /timer и другие для управления\n\n"
        )
        
        markup = InlineKeyboardMarkup()
        markup.row(
            InlineKeyboardButton("📥 Скачать", callback_data="download_mine"),
            InlineKeyboardButton("📖 Фулл описание", callback_data="script_mine_full")
        )
        markup.row(
            InlineKeyboardButton("🔙 Назад", callback_data="menu_scripts"),
            InlineKeyboardButton("🏠 Главное меню", callback_data="menu_start")
        )
        
        # Send with banner if available
        try:
            if MINE_SCRIPT_BANNER_ID and MINE_SCRIPT_BANNER_ID != "ВСТАВЬ_СЮДА_FILE_ID_БАННЕРА":
                await call.message.delete()
                msg = await call.bot.send_photo(call.from_user.id, MINE_SCRIPT_BANNER_ID, caption=caption, reply_markup=markup, parse_mode="HTML")
                last_bot_msg[call.from_user.id] = msg.message_id
            else:
                await send_ui(call, caption, markup)
        except Exception as e:
            logger.error(f"Ошибка отправки карточки скрипта: {e}")
            await send_ui(call, caption, markup)
        
        await call.answer()

    @dp.callback_query_handler(lambda c: c.data.startswith("script_mine_full"), state="*")
    async def cb_script_mine_full(call: types.CallbackQuery):
        """Full script description with pagination"""
        # Determine current page
        try:
            page = int(call.data.split(":")[1]) if ":" in call.data else 1
        except:
            page = 1
        
        # Page 1: Auto-start + Statistics + Display
        page1_caption = (
            "⛏ <b>Скрипт Шахты — Полное описание</b>\n"
            "📄 <b>Страница 1/2</b>\n\n"
            
            "❗️ <b>Автоматический запуск</b>\n"
            "Скрипт сам включается при заходе на Подземную Шахту! Укажите в настройках СВОЕ время начала и конца.\n"
            "<i>Пример: начало 19:30, конец 21:05 → вводите 1930 и 2105</i>\n\n"
            
            "🔥 <b>Главные возможности:</b>\n\n"
            
            "📊 <b>Статистика ресурсов (3 вкладки):</b>\n"
            "• <b>Общая</b> — вся статистика за день\n"
            "• <b>Удвоенные (охр)</b> — ресурсы от охранника + стоимость\n"
            "• <b>С МайнСкелета</b> — добыча с МайнСкелета + стоимость\n\n"
            
            "⚙️ <b>Отображение на экране:</b>\n"
            "• ХП/Армор (на экране и на персонаже)\n"
            "• Таймер АВТОАРМОРА\n"
            "• Красный розыск шахты\n"
            "• Таймер до завала (за 1 мин до события)\n"
            "• Таймер спавна ресурсов"
        )
        
        # Page 2: Commands + Additional features + Hint
        page2_caption = (
            "⛏ <b>Скрипт Шахты — Полное описание</b>\n"
            "📄 <b>Страница 2/2</b>\n\n"
            
            "⌨️ <b>Команды управления:</b>\n"
            "• <code>/shh</code> — вкл/выкл скрипта вручную\n"
            "• <code>/resic</code> — меню настроек скрипта\n"
            "• <code>/timer</code> — запуск/пауза/возобновление таймера\n"
            "• <code>/timerr</code> — сброс таймера на 6:20\n\n"
            
            "✔️ <b>Дополнительные фишки:</b>\n"
            "• Функциональные бинды\n"
            "• КД убийств/смертей (для статистики PvP)\n"
            "• Уведомления о выходе игроков (выход/краш/кик)\n\n"
            
            "💡 <b>Подсказка:</b>\n"
            "<i>Чтобы включить уведомления о выходе игроков БЕЗ шахты — кликните 3 раза по синему тексту (станет зеленым)</i>\n\n"
        )
        
        caption = page1_caption if page == 1 else page2_caption
        
        # Build buttons
        markup = InlineKeyboardMarkup()
        
        # First row: Back to card + Page navigation
        nav_buttons = [InlineKeyboardButton("🔙 К карточке", callback_data="script_mine")]
        if page > 1:
            nav_buttons.append(InlineKeyboardButton("◀️ Страница 1", callback_data=f"script_mine_full:{page-1}"))
        if page < 2:
            nav_buttons.append(InlineKeyboardButton("Страница 2 ▶️", callback_data=f"script_mine_full:{page+1}"))
        markup.row(*nav_buttons)
        
        # Second row: Main menu
        markup.add(InlineKeyboardButton("🏠 Главное меню", callback_data="menu_start"))
        
        photo = MINE_SCRIPT_BANNER_ID if MINE_SCRIPT_BANNER_ID and MINE_SCRIPT_BANNER_ID != "ВСТАВЬ_СЮДА_FILE_ID_БАННЕРА" else PHOTO_FILE_ID
        await send_ui(call, caption, markup, photo=photo)
        await call.answer()

    @dp.callback_query_handler(text="download_mine", state="*")
    async def cb_download_mine(call: types.CallbackQuery):
        """Download mine script file"""
        # Check access
        from bot.database.queries import has_script_access
        if not await has_script_access(call.from_user.id, 'mine'):
            await call.answer("❌ У вас нет доступа к этому скрипту!", show_alert=True)
            return
        
        if not MINE_SCRIPT_FILE_ID or MINE_SCRIPT_FILE_ID == "ВСТАВЬ_СЮДА_FILE_ID_ФАЙЛА":
            await call.answer("⚠️ Файл скрипта еще не загружен. Обратитесь к администратору.", show_alert=True)
            return
        
        try:
            msg = await call.bot.send_document(
                call.from_user.id, 
                MINE_SCRIPT_FILE_ID, 
                caption="<b>Удачного использования! 🚀</b>", 
                parse_mode="HTML"
            )
            # Save file message ID for later deletion
            last_bot_msg[f"{call.from_user.id}_file"] = msg.message_id
            
            await call.answer("📥 Скрипт отправлен!")
        except Exception as e:
            logger.error(f"Ошибка отправки файла скрипта: {e}")
            await call.answer("❌ Ошибка при отправке файла. Попробуйте позже.", show_alert=True)

    # --- OSKOLKI COUNTER SCRIPT ---
    
    @dp.callback_query_handler(text="script_oskolki", state="*")
    async def cb_script_oskolki(call: types.CallbackQuery):
        """Script card for 'Oskolki Counter'"""
        # Check access
        from bot.database.queries import has_script_access
        if not await has_script_access(call.from_user.id, 'oskolki'):
            await call.answer("❌ У вас нет доступа к этому скрипту!", show_alert=True)
            return
        
        from bot.config import OSKOLKI_SCRIPT_BANNER_ID
        
        caption = (
            "🔮 <b>Счетчик Осколков</b>\n\n"
            "📊 <b>Главные возможности:</b>\n"
            "• Статистика выпадений осколков по дням/месяцам\n"
            "• Напоминание о взятии квеста на осколок х4\n"
            "• Напоминание о заборе осколка\n"
            "• Просмотр истории за все время\n\n"
        )
        
        markup = InlineKeyboardMarkup()
        markup.row(
            InlineKeyboardButton("📥 Скачать", callback_data="download_oskolki")
        )
        markup.row(
            InlineKeyboardButton("🔙 Назад", callback_data="menu_scripts"),
            InlineKeyboardButton("🏠 Главное меню", callback_data="menu_start")
        )
        
        # Send with banner if available
        try:
            if OSKOLKI_SCRIPT_BANNER_ID and OSKOLKI_SCRIPT_BANNER_ID != "ВСТАВЬ_СЮДА_FILE_ID_БАННЕРА_ОСКОЛКОВ":
                await call.message.delete()
                msg = await call.bot.send_photo(call.from_user.id, OSKOLKI_SCRIPT_BANNER_ID, caption=caption, reply_markup=markup, parse_mode="HTML")
                last_bot_msg[call.from_user.id] = msg.message_id
            else:
                await send_ui(call, caption, markup)
        except Exception as e:
            logger.error(f"Ошибка отправки карточки скрипта: {e}")
            await send_ui(call, caption, markup)
        
        await call.answer()


    @dp.callback_query_handler(text="download_oskolki", state="*")
    async def cb_download_oskolki(call: types.CallbackQuery):
        """Download oskolki counter script file"""
        # Check access
        from bot.database.queries import has_script_access
        if not await has_script_access(call.from_user.id, 'oskolki'):
            await call.answer("❌ У вас нет доступа к этому скрипту!", show_alert=True)
            return
        
        from bot.config import OSKOLKI_SCRIPT_FILE_ID
        
        if not OSKOLKI_SCRIPT_FILE_ID or OSKOLKI_SCRIPT_FILE_ID == "ВСТАВЬ_СЮДА_FILE_ID_ФАЙЛА_ОСКОЛКОВ":
            await call.answer("⚠️ Файл скрипта еще не загружен. Обратитесь к администратору.", show_alert=True)
            return
        
        try:
            msg = await call.bot.send_document(
                call.from_user.id, 
                OSKOLKI_SCRIPT_FILE_ID, 
                caption="<b>Удачного использования! 💎</b>", 
                parse_mode="HTML"
            )
            # Save file message ID for later deletion
            last_bot_msg[f"{call.from_user.id}_file"] = msg.message_id
            
            await call.answer("📥 Скрипт отправлен!")
        except Exception as e:
            logger.error(f"Ошибка отправки файла скрипта: {e}")
            await call.answer("❌ Ошибка при отправке файла. Попробуйте позже.", show_alert=True)


    # --- CENTRALIZED SUGGESTION FLOW ---
    
    @dp.callback_query_handler(text="menu_suggest", state="*")
    async def cb_menu_suggest(call: types.CallbackQuery):
        """Show script selection menu for suggestions"""
        from bot.database.queries import get_access_nickname
        
        # Check access
        nick = await get_access_nickname(call.from_user.id)
        if not nick:
            return await call.answer("⚠️ У вас нет активного доступа к скриптам.", show_alert=True)
        
        caption = (
            "💡 <b>Предложить изменения</b>\n\n"
            "Выберите скрипт, к которому хотите предложить изменения:"
        )
        
        markup = InlineKeyboardMarkup(row_width=2)
        markup.row(
            InlineKeyboardButton("⛏ Скрипт Шахты", callback_data="suggest_script:mine"),
            InlineKeyboardButton("🔮 Счетчик осколков", callback_data="suggest_script:oskolki")
        )
        markup.add(InlineKeyboardButton("🏠 Главное меню", callback_data="menu_start"))
        
        await send_ui(call, caption, markup)
        await call.answer()
    
    @dp.callback_query_handler(lambda c: c.data.startswith("suggest_script:"), state="*")
    async def cb_suggest_select_script(call: types.CallbackQuery, state: FSMContext):
        """Handle script selection and prompt for suggestion"""
        script_name = call.data.split(":")[1]
        
        script_display = {
            "mine": "Шахты",
            "oskolki": "Счетчик осколков"
        }
        
        await AdminStates.waiting_for_suggestion.set()
        await state.update_data(suggest_mid=call.message.message_id, suggest_script=script_name)
        
        markup = InlineKeyboardMarkup().add(InlineKeyboardButton("❌ Отмена", callback_data="menu_suggest"))
        text = (
            f"💡 <b>Предложить изменения</b>\n\n"
            f"Напишите, что бы вы хотели видеть в скрипте <b>{script_display.get(script_name, script_name)}</b>.\n"
            "Вы можете прислать описание фич или ссылки на идеи.\n\n"
        )
        
        if call.message.caption:
            await call.message.edit_caption(caption=text, reply_markup=markup, parse_mode="HTML")
        else:
            await call.message.edit_text(text, reply_markup=markup, parse_mode="HTML")
        await call.answer()

    @dp.callback_query_handler(text="script_dev", state="*")
    async def cb_script_dev(call: types.CallbackQuery):
        """Placeholder for scripts in development"""
        await call.answer("🛠 Этот скрипт находится в разработке. Ожидайте обновлений!", show_alert=True)


async def show_profile_logic(event, state):
    """
    Show user profile (shared logic for command and callback)
    
    Args:
        event: Message or CallbackQuery
        state: FSM context
    """
    if not await check_user_status(event if isinstance(event, types.Message) else event.message, state):
        return
    if not check_db_ready():
        return
    
    user_id = event.from_user.id
    text = ""
    markup = InlineKeyboardMarkup()
    
    try:
        from bot.database.connection import db_fetch_with_retry
        
        res = await db_fetch_with_retry(
            "SELECT nickname, approved FROM access_list WHERE tg_user_id = %s",
            (user_id,),
            fetch="one",
            action_desc="Ошибка загрузки профиля"
        )
        
        if res:
            nickname, approved = res
            
            # If approved (has some access)
            if approved:
                from bot.utils.access_control import format_user_access_status, get_user_accessible_scripts
                
                # Get access status
                access_status = await format_user_access_status(user_id)
                accessible_scripts = await get_user_accessible_scripts(user_id)
                
                text = (
                    f"👤 <b>Ваш профиль:</b>\n\n"
                    f"Ник: <code>{nickname}</code>\n"
                    f"Статус: <b>Активен - ✅</b>\n\n"
                    f"📜 <b>Доступ к скриптам:</b>\n{access_status}"
                )
                
                # Check if user has access to all scripts
                has_all_scripts = len(accessible_scripts) >= 2  # mine and oskolki
                
                markup.row(
                    InlineKeyboardButton("🗑 Удалить ник", callback_data=f"del_my:{nickname}"),
                    InlineKeyboardButton("🏠 Главное меню", callback_data="menu_start")
                )
                
                # Add "Request Additional Access" button if user doesn't have all scripts
                if not has_all_scripts:
                    markup.add(InlineKeyboardButton("➕ Запросить доступ к скрипту", callback_data="request_additional_access"))
            # If pending
            else:
                text = (
                    f"👤 <b>Ваш профиль:</b>\n\n"
                    f"🎮 Ник: <code>{nickname}</code>\n"
                    f"⏳ Статус: <b>На рассмотрении</b>\n\n"
                    f"Ожидайте решения администратора."
                )
                markup.add(InlineKeyboardButton("🏠 Главное меню", callback_data="menu_start"))
        else:
            markup.row(
                InlineKeyboardButton("📝 Подать заявку", callback_data="menu_apply"),
                InlineKeyboardButton("📚 Помощь", callback_data="menu_help")
            )
            text = "🕵️‍♂️ <b>Профиль не найден.</b>\n\nУ вас нет активного доступа к скрипту."
            markup.add(InlineKeyboardButton("🏠 Главное меню", callback_data="menu_start"))
            
        await send_ui(event, text, markup)
    except Exception as e:
        logger.error(e)
