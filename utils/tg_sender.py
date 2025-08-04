from curl_cffi.requests import AsyncSession
from loguru import logger

from data.settings import Settings
 

async def tg_sender(msg=None):
 
    special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    for char in special_chars:
        msg = msg.replace(char, f'\\{char}')

    try:
        json_data = {
            'parse_mode':'MarkdownV2',
            'chat_id': Settings().tg_user_id,
            'text': msg
        }
        url = f'https://api.telegram.org/bot{Settings().tg_bot_id}/sendMessage'

        async with AsyncSession() as session:
            r = await session.post(url=url, json=json_data)

            return r.json()

    except Exception as err:
        logger.error(f'Send Telegram message error |{err} | {msg}')
