import os
import random
import sys
from pathlib import Path
from typing import Dict, List

from loguru import logger
from dotenv import load_dotenv
import asyncio


load_dotenv()


if getattr(sys, 'frozen', False):
    ROOT_DIR = Path(sys.executable).parent.absolute()
else:
    ROOT_DIR = Path(__file__).parent.parent.absolute()

FILES_DIR = os.path.join(ROOT_DIR, 'files')
WALLETS_DB = os.path.join(FILES_DIR, 'wallets.db')
SETTINGS_FILE = os.path.join(FILES_DIR, 'settings.yaml')

TEMPLATE_SETTINGS_FILE = os.path.join(ROOT_DIR, 'utils', 'settings_template.yaml') 
ABIS_DIR = os.path.join(ROOT_DIR, 'data', 'abis')

SALT_PATH = os.path.join(FILES_DIR, 'salt.dat')

CIPHER_SUITE = None
LOCK = asyncio.Lock()


# Configure the logger based on the settings
from data.settings import Settings 
settings = Settings()
LOGS_DIR = os.path.join(FILES_DIR, 'logs')
LOG_FILE = os.path.join(LOGS_DIR, 'log.log')

if settings.log_level not in ["DEBUG", "INFO", "WARNING", "ERROR"]:
    raise ValueError(f"Invalid log level: {settings.log_level}. Must be one of: DEBUG, INFO, WARNING, ERROR")
logger.remove()  # Remove the default logger
logger.add(sys.stderr, level=settings.log_level)

logger.add(LOG_FILE, level="DEBUG")