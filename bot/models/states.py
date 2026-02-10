"""
FSM States module
Defines all state machines for the bot
"""

from aiogram.dispatcher.filters.state import State, StatesGroup


class AdminStates(StatesGroup):
    """Admin FSM states"""
    waiting_for_rejection_reason = State()
    waiting_for_ban_reason = State()
    waiting_for_suggestion = State()
    waiting_for_photo = State()
    waiting_for_file = State()
    waiting_for_broadcast_msg = State()
    waiting_for_broadcast_target = State()
    waiting_for_broadcast_users = State()


class UserStates(StatesGroup):
    """User FSM states"""
    waiting_for_appeal = State()
    waiting_for_nick = State()
    waiting_for_info = State()
    waiting_for_script_selection = State()
