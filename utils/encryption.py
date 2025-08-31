import getpass
import os

from cryptography.fernet import InvalidToken
import sys

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from loguru import logger

from data.settings import Settings
from data import config
from data.config import SALT_PATH

import base64
import hashlib
from cryptography.fernet import Fernet

from data.config import SALT_PATH
from utils.db_api.models import Wallet
from utils.db_api.wallet_api import db

def _derive_fernet_key(password: bytes, salt=None) -> bytes:

    try:
        if salt:
            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32,
                salt=salt,
                iterations=100000,
                backend=default_backend()
            )
            return base64.urlsafe_b64encode(kdf.derive(password))

        else:
            digest = hashlib.sha256(password).digest()
            return base64.urlsafe_b64encode(digest)

    except TypeError:
        logger.error('Error! Check salt file! Salt must be bites string')
        sys.exit(1)




def set_cipher_suite(password) -> None:
    if Settings().private_key_encryption:
        cipher = Fernet(_derive_fernet_key(password))

        if not os.path.exists(SALT_PATH):

            cipher = Fernet(_derive_fernet_key(password))

            config.CIPHER_SUITE = cipher

        else:
            with open(SALT_PATH, 'rb') as f:
                salt = f.read()

            cipher = Fernet(_derive_fernet_key(password, salt))
            config.CIPHER_SUITE = cipher


def get_private_key(enc_value: str) -> str:
    try:
        if Settings().private_key_encryption:
            if 'gAAAA' in enc_value:
                return config.CIPHER_SUITE.decrypt(enc_value.encode()).decode()

        return enc_value
    except Exception:
        raise InvalidToken(f"{enc_value} | wrong password! Decrypt failed")
        #sys.exit(f"{enc_value} | wrong password! Decrypt failed")

def prk_encrypt(value: str) -> str:
    if Settings().private_key_encryption:
        if not 'gAAAA' in value:
            return config.CIPHER_SUITE.encrypt(value.encode()).decode()

    return value

def check_encrypt_param(confirm: bool = False, attempts: int = 3):
    if not Settings().private_key_encryption:
        return True

    for try_num in range(1, attempts + 1):
        pwd1 = getpass.getpass(
            "[DECRYPTOR] Enter password (input hidden): "
        ).strip().encode()

        if confirm:
            pwd2 = getpass.getpass(
                "[DECRYPTOR] Repeat password: "
            ).strip().encode()

            if pwd1 != pwd2:
                print(f"Passwords do not match (attempt {try_num}/{attempts})\n")
                continue

        if not pwd1:
            print("Password cannot be empty.\n")
            continue
        
        set_cipher_suite(pwd1)
        check_password_wallet = db.one(Wallet, Wallet.id == 1)
        if check_password_wallet:
            try:
                # Should raise a specific error on wrong key
                get_private_key(check_password_wallet.private_key)
                return True 
            except Exception:
                print(f"Invalid password (attempt {try_num}/{attempts})\n")
                continue
        else:
            return True



    raise RuntimeError("Password confirmation failed – too many attempts.")
