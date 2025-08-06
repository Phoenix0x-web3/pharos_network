import random
from datetime import datetime, timedelta

from loguru import logger
from sqlalchemy import select, and_, or_

from data.config import LOCK
from data.settings import Settings
from utils.db_api.wallet_api import db, get_wallet_by_private_key
from utils.db_api.models import Wallet


def update_expired() -> None:
    now = datetime.now()

    stmt = select(Wallet).where(
        or_(
            Wallet.next_activity_action_time <= now,
            Wallet.next_activity_action_time.is_(None),
        )
    )

    expired_wallets: list[Wallet] = db.all(stmt=stmt)

    if not expired_wallets:
        return

    settings = Settings()
    
    for wallet in expired_wallets:

        wallet.next_activity_action_time = now + timedelta(
            seconds=random.randint(0, int(settings.random_pause_wallet_after_completion_max / 3 ))
        )
        logger.info(
            f'{wallet}: Action time was re-generated: '
            f'{wallet.next_activity_action_time}.'
        )

    db.commit()

async def update_next_action_time(private_key: str, seconds: int) -> bool:
    try:
        now = datetime.now()
        wallet = get_wallet_by_private_key(private_key=private_key)
        wallet.next_activity_action_time = now + timedelta(seconds=seconds)
        
        async with LOCK:
            db.commit()
        return True
    except BaseException:
        return False

async def update_points_invites(private_key: str, points: int, invite_code : str) -> bool:
    try:
        wallet = get_wallet_by_private_key(private_key=private_key)
        wallet.points = points
        wallet.invite_code = invite_code
        
        async with LOCK:
            db.commit()
        return True
    except BaseException:
        return False