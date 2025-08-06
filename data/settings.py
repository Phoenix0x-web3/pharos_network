from libs.eth_async.classes import Singleton
from data.config import SETTINGS_FILE
import yaml


class Settings(Singleton):
    def __init__(self):
        with open(SETTINGS_FILE, 'r') as file:
            json_data = yaml.safe_load(file) or {}

        self.private_key_encryption = json_data.get("private_key_encryption", False)
        self.threads = json_data.get("threads", 4)
        self.exact_wallets_to_run = json_data.get("exact_wallets_to_run", [])
        self.shuffle_wallets = json_data.get("shuffle_wallets", True)
        self.sleep_after_each_cycle_hours = json_data.get("sleep_after_each_cycle_hours", 0)
        self.random_pause_between_wallets_min = json_data.get("random_pause_between_wallets",{}).get("min")
        self.random_pause_between_wallets_max = json_data.get("random_pause_between_wallets", {}).get("max")
        self.random_pause_between_actions_min = json_data.get("random_pause_between_actions", {}).get("min")
        self.random_pause_between_actions_max = json_data.get("random_pause_between_actions", {}).get("max")
        self.swap_percent_from = json_data.get("swap_percent", {}).get("min")
        self.swap_percent_to = json_data.get("swap_percent", {}).get("max")
        self.tg_bot_id = json_data.get("tg_bot_id", "")
        self.tg_user_id = json_data.get("tg_user_id", "")
        self.invite_codes = json_data.get("invite_codes", [])
        self.random_pause_wallet_after_completion_min = json_data.get("random_pause_wallet_after_completion", {}).get('min')
        self.random_pause_wallet_after_completion_max = json_data.get("random_pause_wallet_after_completion", {}).get('max')
        self.swaps_count_min = json_data.get("swaps_count", {}).get('min')
        self.swaps_count_max = json_data.get("swaps_count", {}).get('max')
        self.tips_count_min = json_data.get("tips_count", {}).get('min')
        self.tips_count_max = json_data.get("tips_count", {}).get('max')


