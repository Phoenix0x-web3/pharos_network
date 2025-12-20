import os
import random
from typing import List, Optional, Tuple

from loguru import logger

from data import config
from utils.db_api.models import Wallet
from utils.db_api.wallet_api import (
    db,
    get_wallets_with_bad_proxy,
    get_wallets_with_bad_twitter,
    mark_proxy_as_bad,
    mark_twitter_as_bad,
    replace_bad_proxy,
    replace_bad_twitter,
)


class ResourceManager:
    """Class for managing resources (proxies, Twitter tokens)"""

    def __init__(self):
        """Initialize the resource manager"""
        pass

    @staticmethod
    def _load_from_file(file_path: str) -> List[str]:
        """
        Load data from a file

        Args:
            file_path: Path to the file

        Returns:
            List of strings from the file
        """
        if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
            with open(file_path, "r") as file:
                return [line.strip() for line in file if line.strip()]
        return []

    @staticmethod
    def _save_to_file(file_path: str, data: List[str]) -> bool:
        """
        Save data to a file

        Args:
            file_path: Path to the file
            data: List of strings to save

        Returns:
            Success status
        """
        try:
            with open(file_path, "w") as file:
                for line in data:
                    file.write(f"{line}\n")
            return True
        except Exception as e:
            logger.error(f"Error saving to file {file_path}: {str(e)}")
            return False

    def _get_available_proxy(self) -> Optional[str]:
        """
        Get an available reserve proxy and remove it from the file

        Returns:
            Proxy or None if no proxies are available
        """
        # Load list of proxies from file
        all_proxies = self._load_from_file(config.RESERVE_PROXY_FILE)

        if not all_proxies:
            logger.warning("No available proxies in file")
            return None

        # Select a random proxy
        proxy = random.choice(all_proxies)

        # Remove selected proxy from list
        all_proxies.remove(proxy)

        # Save updated list back to file
        if self._save_to_file(config.RESERVE_PROXY_FILE, all_proxies):
            logger.info(f"Proxy successfully selected and removed from file. Remaining: {len(all_proxies)}")
        else:
            logger.warning("Failed to update proxy file, but proxy was selected")

        return proxy

    def _get_available_twitter(self) -> Optional[str]:
        """
        Get an available reserve Twitter token and remove it from the file

        Returns:
            Token or None if no tokens are available
        """
        # Load list of tokens from file
        all_tokens = self._load_from_file(config.RESERVE_TWITTER_FILE)

        if not all_tokens:
            logger.warning("No available Twitter tokens in file")
            return None

        # Select a random token
        token = random.choice(all_tokens)

        # Remove selected token from list
        all_tokens.remove(token)

        # Save updated list back to file
        if self._save_to_file(config.RESERVE_TWITTER_FILE, all_tokens):
            logger.info(f"Twitter token successfully selected and removed from file. Remaining: {len(all_tokens)}")
        else:
            logger.warning("Failed to update Twitter token file, but token was selected")

        return token

    async def replace_proxy(self, id: int) -> Tuple[bool, str]:
        """
        Replace a user's proxy

        Args:
            id: User id

        Returns:
            (success, message): Success status and message
        """
        new_proxy = self._get_available_proxy()
        if not new_proxy:
            return False, "No available reserve proxies"

        success = replace_bad_proxy(id, new_proxy)

        if success:
            return True, f"Proxy successfully replaced with {new_proxy}"
        else:
            return False, "Failed to replace proxy"

    async def replace_twitter(self, id: int) -> Tuple[bool, str]:
        """
        Replace a user's Twitter token

        Args:
            id: User id

        Returns:
            (success, message): Success status and message
        """
        new_token = self._get_available_twitter()
        if not new_token:
            return False, "No available reserve Twitter tokens"

        success = replace_bad_twitter(id, new_token)

        if success:
            logger.success("Twitter token successfully replaced in database")
            return True, "Twitter token successfully replaced"
        else:
            # Do not return token to file as it may already be used
            logger.error("Failed to replace Twitter token in database")
            return False, "Failed to replace Twitter token"

    async def mark_proxy_as_bad(self, id: int) -> bool:
        """
        Mark a user's proxy as bad

        Args:
            id: User id

        Returns:
            Success status
        """
        return mark_proxy_as_bad(id)

    async def mark_twitter_as_bad(self, id: int) -> bool:
        """
        Mark a user's Twitter token as bad

        Args:
            id: User id

        Returns:
            Success status
        """
        return mark_twitter_as_bad(id)

    async def get_bad_proxies(self) -> List:
        """
        Get list of wallets with bad proxies

        Returns:
            List of wallets
        """
        return get_wallets_with_bad_proxy()

    async def get_bad_twitter(self) -> List:
        """
        Get list of wallets with bad Twitter tokens

        Returns:
            List of wallets
        """
        return get_wallets_with_bad_twitter()

    async def replace_all_bad_proxies(self) -> Tuple[int, int]:
        """
        Replace all bad proxies

        Returns:
            (replaced, total): Number of replaced proxies and total number of bad proxies
        """
        replaced = 0

        bad_proxies = await self.get_bad_proxies()

        for wallet in bad_proxies:
            success, _ = await self.replace_proxy(wallet.id)
            if success:
                replaced += 1

        return replaced, len(bad_proxies)

    async def replace_all_bad_twitter(self) -> Tuple[int, int]:
        """
        Replace all bad Twitter tokens

        Returns:
            (replaced, total): Number of replaced tokens and total number of bad tokens
        """
        replaced = 0

        bad_twitter = await self.get_bad_twitter()

        for wallet in bad_twitter:
            success, _ = await self.replace_twitter(wallet.id)
            if success:
                replaced += 1

        return replaced, len(bad_twitter)


async def replace_twitter_tokens(wallet: Wallet):
    wallets = db.all(Wallet)
    all_twitter_tokens = [wallet.twitter_token for wallets in wallets]

    all_tokens = ResourceManager._load_from_file(config.RESERVE_TWITTER_FILE)

    if not all_tokens:
        logger.warning("No available Twitter tokens in file")
        return wallet

    token = random.choice(all_tokens)

    if token not in all_twitter_tokens:
        wallet.twitter_token = token

        all_tokens.remove(token)

        # Save updated list back to file
        if ResourceManager._save_to_file(config.RESERVE_TWITTER_FILE, all_tokens):
            db.commit()
            logger.success(f"{wallet} | Twitter token successfully replaced and removed from file. Remaining: {len(all_tokens)}")

        else:
            logger.warning("Failed to update Twitter token file, but token was selected")

        return wallet

    logger.warning(f"{wallet} | No availible twitter tokens, all tokens are in use by other wallets")

    return wallet
