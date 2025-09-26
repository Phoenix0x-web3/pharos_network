import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


if getattr(sys, "frozen", False):
    ROOT_DIR = Path(sys.executable).parent.absolute()
else:
    ROOT_DIR = Path(__file__).parent.parent.absolute()

FILES_DIR = os.path.join(ROOT_DIR, "files")
WALLETS_DB = os.path.join(FILES_DIR, "wallets.db")
SETTINGS_FILE = os.path.join(FILES_DIR, "settings.yaml")

TEMPLATE_SETTINGS_FILE = os.path.join(ROOT_DIR, "utils", "settings_template.yaml")
ABIS_DIR = os.path.join(ROOT_DIR, "data", "abis")

SALT_PATH = os.path.join(FILES_DIR, "salt.dat")

CIPHER_SUITE = None
LOCK = asyncio.Lock()

LOGS_DIR = os.path.join(FILES_DIR, "logs")
LOG_FILE = os.path.join(LOGS_DIR, "log.log")
