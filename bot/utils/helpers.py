"""
Helper utilities module
Miscellaneous helper functions
"""

import asyncio
from aiogram import types


async def delete_after_delay(message: types.Message, delay: int):
    """
    Delete a message after a delay
    
    Args:
        message: Message to delete
        delay: Delay in seconds
    """
    await asyncio.sleep(delay)
    try:
        await message.delete()
    except:
        pass
