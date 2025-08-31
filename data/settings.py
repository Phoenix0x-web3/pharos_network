from __future__ import annotations
import sys
from libs.eth_async.classes import Singleton
from data.config import LOG_FILE, SETTINGS_FILE
from loguru import logger
import yaml


class Settings(Singleton):
    def __init__(self):
        with open(SETTINGS_FILE, 'r') as file:
            json_data = yaml.safe_load(file) or {}

        self.private_key_encryption = json_data.get("private_key_encryption", False)
        self.threads = json_data.get("threads", 4)
        self.range_wallets_to_run = json_data.get("range_wallets_to_run", [0, 0])
        self.exact_wallets_to_run = json_data.get("exact_wallets_to_run", [])
        self.shuffle_wallets = json_data.get("shuffle_wallets", True)
        self.hide_wallet_address_log = json_data.get("hide_wallet_address_log", True)
        self.log_level = json_data.get("log_level", "INFO")
        self.check_git_updates = json_data.get("check_git_updates", True)
        self.sleep_after_each_cycle_hours = json_data.get("sleep_after_each_cycle_hours", 0)
        self.random_pause_start_wallet_min = json_data.get("random_pause_start_wallet", {}).get("min")
        self.random_pause_start_wallet_max = json_data.get("random_pause_start_wallet", {}).get("max")
        self.random_pause_between_actions_min = json_data.get("random_pause_between_actions", {}).get("min")
        self.random_pause_between_actions_max = json_data.get("random_pause_between_actions", {}).get("max")
        self.random_pause_wallet_after_completion_min = json_data.get("random_pause_wallet_after_completion", {}).get('min')
        self.random_pause_wallet_after_completion_max = json_data.get("random_pause_wallet_after_completion", {}).get('max')
        self.swap_percent_from = json_data.get("swap_percent", {}).get("min")
        self.swap_percent_to = json_data.get("swap_percent", {}).get("max")
        self.autostake_percent_min = json_data.get("autostake_percent", {}).get("min")
        self.autostake_percent_max = json_data.get("autostake_percent", {}).get("max")
        self.tg_bot_id = json_data.get("tg_bot_id", "")
        self.tg_user_id = json_data.get("tg_user_id", "")
        self.invite_codes = json_data.get("invite_codes", [])
        self.swaps_count_min = json_data.get("swaps_count", {}).get('min')
        self.swaps_count_max = json_data.get("swaps_count", {}).get('max')
        self.tips_count_min = json_data.get("tips_count", {}).get('min')
        self.tips_count_max = json_data.get("tips_count", {}).get('max')
        self.autostake_count_min = json_data.get("autostake_count", {}).get('min')
        self.autostake_count_max = json_data.get("autostake_count", {}).get('max')
        self.liquidity_count_min = json_data.get("liquidity_count", {}).get('min')
        self.liquidity_count_max = json_data.get("liquidity_count", {}).get('max')
        self.lending_count_min = json_data.get("lending_count", {}).get('min')
        self.lending_count_max = json_data.get("lending_count", {}).get('max')
        self.liquidity_percent_min = json_data.get("liquidity_percent", {}).get('min')
        self.liquidity_percent_max = json_data.get("liquidity_percent", {}).get('max')
        self.brokex_percent_min = json_data.get("brokex_percent", {}).get('min')
        self.brokex_percent_max = json_data.get("brokex_percent", {}).get('max')
        self.brokex_count_min = json_data.get("brokex_count", {}).get('min')
        self.brokex_count_max = json_data.get("brokex_count", {}).get('max')
        self.retry = json_data.get("retry", {})
        self.discord_proxy = json_data.get("discord_proxy", {})
        self.capmonster_api_key = json_data.get("capmonster_api_key", {})

# Configure the logger based on the settings
settings = Settings()

if settings.log_level not in ["DEBUG", "INFO", "WARNING", "ERROR"]:
    raise ValueError(f"Invalid log level: {settings.log_level}. Must be one of: DEBUG, INFO, WARNING, ERROR")
logger.remove()  # Remove the default logger
logger.add(sys.stderr, level=settings.log_level)

logger.add(LOG_FILE, level="DEBUG")
