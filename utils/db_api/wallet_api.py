from data.config import WALLETS_DB
from utils.db_api.db import DB
from utils.db_api.models import Base, Wallet


def get_wallets(sqlite_query: bool = False) -> list[Wallet]:
    if sqlite_query:
        return db.execute("SELECT * FROM wallets")

    return db.all(entities=Wallet)


def get_wallet_by_private_key(private_key: str, sqlite_query: bool = False) -> Wallet | None:
    if sqlite_query:
        return db.execute("SELECT * FROM wallets WHERE private_key = ?", (private_key,), True)

    return db.one(Wallet, Wallet.private_key == private_key)


def get_wallet_by_address(address: str, sqlite_query: bool = False) -> Wallet | None:
    if sqlite_query:
        return db.execute("SELECT * FROM wallets WHERE address = ?", (address,), True)

    return db.one(Wallet, Wallet.address == address)


def update_twitter_token(private_key: str, updated_token: str | None) -> bool:
    """
    Updates the Twitter token for a wallet with the given private_key.

    Args:
        private_key: The private key of the wallet to update
        new_token: The new Twitter token to set

    Returns:
        bool: True if update was successful, False if wallet not found
    """
    if not updated_token:
        return False

    wallet = db.one(Wallet, Wallet.private_key == private_key)
    if not wallet:
        return False

    wallet.twitter_token = updated_token
    db.commit()
    return True


db = DB(f"sqlite:///{WALLETS_DB}", echo=False, pool_recycle=3600, connect_args={"check_same_thread": False})
db.create_tables(Base)
