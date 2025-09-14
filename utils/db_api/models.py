import random
from datetime import datetime

from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.orm import Mapped, mapped_column
from data.settings import Settings
from data.constants import PROJECT_SHORT_NAME

class Base(DeclarativeBase):
    pass

class Wallet(Base):
    __tablename__ = 'wallets'

    id: Mapped[int] = mapped_column(primary_key=True)
    private_key: Mapped[str] = mapped_column(unique=True, index=True)
    address: Mapped[str] = mapped_column(unique=True)
    proxy: Mapped[str] = mapped_column(default=None, nullable=True)
    discord_token: Mapped[str] = mapped_column(default=None, nullable=True)
    twitter_token: Mapped[str] = mapped_column(default=None, nullable=True)
    #next_activity_action_time: Mapped[datetime | None] = mapped_column(default=None, nullable=True)
    points: Mapped[int] = mapped_column(default=0)
    invite_code: Mapped[str] = mapped_column(default="")
    wallet_type: Mapped[str] = mapped_column(default='')
    discord_proxy: Mapped[str] = mapped_column(default=None, nullable=True)
    discord_status: Mapped[str] = mapped_column(default=None, nullable=True)
    completed: Mapped[bool] = mapped_column(default=False)


    def __repr__(self):
        if Settings().hide_wallet_address_log:
            return f'[{PROJECT_SHORT_NAME} | {self.id}]'
        return f'[{PROJECT_SHORT_NAME} | {self.id} | {self.address}]'