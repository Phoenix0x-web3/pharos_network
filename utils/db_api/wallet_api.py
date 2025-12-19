from data.config import WALLETS_DB
from utils.db_api.db import DB
from utils.db_api.models import Base, Wallet


def get_wallets(sqlite_query: bool = False) -> list[Wallet]:
    if sqlite_query:
        return db.execute("SELECT * FROM wallets")

    return db.all(entities=Wallet)


def get_wallet_by_id(id: int, sqlite_query: bool = False) -> Wallet | None:
    return db.one(Wallet, Wallet.id == id)


def get_wallet_by_email_data(email_data: str) -> Wallet | None:
    return db.one(Wallet, Wallet.email_data == email_data)


def save_bearer_token(id: int, bearer_token: str) -> bool:
    wallet = db.one(Wallet, Wallet.id == id)
    if not wallet:
        return False
    wallet.bearer_token = bearer_token
    db.commit()
    return True


def save_refresh_token(id: int, refresh_token: str) -> bool:
    wallet = db.one(Wallet, Wallet.id == id)
    if not wallet:
        return False
    wallet.refresh_token = refresh_token
    db.commit()
    return True


def update_points_and_top(id: int, points: int, top: int) -> bool:
    wallet = db.one(Wallet, Wallet.id == id)
    if not wallet:
        return False
    wallet.points = points
    wallet.top = top
    db.commit()
    return True


def update_discord_connect(id: int) -> bool:
    wallet = db.one(Wallet, Wallet.id == id)
    if not wallet:
        return False
    wallet.discord_connected = True
    db.commit()
    return True


def update_twitter_token(id: int, updated_token: str | None) -> bool:
    """
    Updates the Twitter token for a wallet with the given private_key.

    Args:
        id: The id of the wallet to update
        new_token: The new Twitter token to set

    Returns:
        bool: True if update was successful, False if wallet not found
    """
    if not updated_token:
        return False

    wallet = db.one(Wallet, Wallet.id == id)
    if not wallet:
        return False

    wallet.twitter_token = updated_token
    db.commit()
    return True


def replace_bad_proxy(id: int, new_proxy: str) -> bool:
    wallet = db.one(Wallet, Wallet.id == id)
    if not wallet:
        return False
    wallet.proxy = new_proxy
    wallet.proxy_status = "OK"
    db.commit()
    return True


def replace_bad_twitter(id: int, new_token: str) -> bool:
    wallet = db.one(Wallet, Wallet.id == id)
    if not wallet:
        return False
    wallet.twitter_token = new_token
    wallet.twitter_status = "OK"
    db.commit()
    return True


def mark_proxy_as_bad(id: int) -> bool:
    wallet = db.one(Wallet, Wallet.id == id)
    if not wallet:
        return False
    wallet.proxy_status = "BAD"
    db.commit()
    return True


def mark_discord_as_bad(id: int) -> bool:
    wallet = db.one(Wallet, Wallet.id == id)
    if not wallet:
        return False
    wallet.discord_status = "BAD"
    db.commit()
    return True


def mark_twitter_as_bad(id: int) -> bool:
    wallet = db.one(Wallet, Wallet.id == id)
    if not wallet:
        return False
    wallet.twitter_status = "BAD"
    db.commit()
    return True


def set_fs_form_status(id: int, status: str) -> bool:
    wallet = db.one(Wallet, Wallet.id == id)
    if not wallet:
        return False
    wallet.hs_form_status = status
    db.commit()
    return True


def get_wallets_with_bad_proxy() -> list:
    return db.all(Wallet, Wallet.proxy_status == "BAD")


def get_wallets_with_bad_twitter() -> list:
    return db.all(Wallet, Wallet.twitter_status == "BAD")


db = DB(f"sqlite:///{WALLETS_DB}", echo=False, pool_recycle=3600, connect_args={"check_same_thread": False})
db.create_tables(Base)
