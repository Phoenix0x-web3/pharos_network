import copy
from dataclasses import dataclass
from curl_cffi.requests import Response
import urllib.parse
from typing import Optional, Any, Tuple, Dict
from utils.browser import Browser
from loguru import logger
import libs.twitter as twitter
from libs.twitter.utils import remove_at_sign
from utils.db_api.models import Wallet
from utils.db_api.wallet_api import update_twitter_token
import libs.baseAsyncSession as BaseAsyncSession

#TODO Move to Exception file
class BadTwitter(Exception):
    pass

@dataclass
class TwitterOauthData:
    auth_token: str
    state_verifier_token: str
    callback_url: str
    callback_response: Response


class TwitterClient():

    def __init__(
        self,
        user: Wallet,
        twitter_auth_token: str | None = None,
        twitter_username: str | None = None,
        twitter_password: str | None = None,
        totp_secret: str | None = None,
        ct0: str | None = None,
        email: str | None = None
    ):
        """
        Initialize Twitter client

        Args:
            user: User object
            twitter_auth_token: Twitter authorization token
            twitter_username: Twitter username (without @)
            twitter_password: Twitter account password
            totp_secret: TOTP secret (if 2FA is enabled)
        """

        if not twitter_auth_token:
            twitter_auth_token = user.twitter_token
        # Create Twitter account
        self.user = user
        self.twitter_account = twitter.Account(
            auth_token=twitter_auth_token,
            username=twitter_username,
            password=twitter_password,
            totp_secret=totp_secret,
            ct0=ct0,
            email=email
        )

        # Twitter client configuration
        self.client_config = {
            "wait_on_rate_limit": True,
            "auto_relogin": False,
            "update_account_info_on_startup": True,
            #TODO: Import CAPMONSTER_API_KEY
            "capsolver_api_key": "CAPMONSTER_API_KEY",
        }

        # Add proxy if specified
        if user.proxy:
            self.client_config["proxy"] = user.proxy

        # Initialize Twitter client as None
        self.twitter_client = None
        self.is_connected = False

        # Add fields for tracking errors
        self.last_error = None
        self.error_count = 0

    async def initialize(self) -> bool:
        """
        Initializes the Twitter client

        Returns:
            Success status
        """
        # Create Twitter client
        self.twitter_client = twitter.Client(
            self.twitter_account, **self.client_config,
            headers=BaseAsyncSession.FINGERPRINT_DEFAULT.get("headers", {}),
            impersonate=BaseAsyncSession.FINGERPRINT_DEFAULT.get("impersonate", "chrome136")
        )

        # Establish connection
        await self.twitter_client.__aenter__()

        # Check account status
        await self.twitter_client.establish_status()

        if self.twitter_account.status == twitter.AccountStatus.GOOD:
            logger.success(f"{self.user} Twitter client initialized")
            update_twitter_token(private_key=self.user.private_key, updated_token=self.twitter_account.auth_token)
            return True
        else:
            error_msg = f"Problem with Twitter account status: {self.twitter_account.status}"
            logger.error(f"{self.user} {error_msg}")
            self.last_error = error_msg
            self.error_count += 1

            # If authorization issue, mark token as bad
            if self.twitter_account.status in [
                twitter.AccountStatus.BAD_TOKEN,
                twitter.AccountStatus.SUSPENDED,
            ]:
                #TODO Replace Twitter Token to DB
                raise BadTwitter

            return False


    async def close(self):
        """Closes the Twitter connection"""
        if self.twitter_client:
            try:
                await self.twitter_client.__aexit__(None, None, None)
                self.twitter_client = None
                logger.debug(f"{self.user} Twitter client closed")
            except Exception as e:
                logger.error(
                    f"{self.user} Error closing Twitter client: {str(e)}"
                )

    async def __aenter__(self):
        """Context manager for entering"""
        await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Context manager for exiting"""
        await self.close()

    async def follow_account(
        self, account_name: str
    ) -> bool:
        """
        Follows the specified Twitter account

        Args:
            account_name: Account name to follow (with or without @)

        Returns:
            - Success status
        """

        if not self.twitter_client:
            initialize = await self.initialize()
            if not initialize:
                raise Exception("Can't initialize twitter client")

        # Remove @ from account name if present
        clean_account_name = remove_at_sign(account_name)

        # Get user by username
        user = await self.twitter_client.request_user_by_username(
            clean_account_name
        )

        if not user or not user.id:
            logger.error(
                f"{self.user} Could not find user @{clean_account_name}"
            )
            return False

        # Check if already following the user
        is_following = await self._check_if_following(user_id=user.id)

        if is_following:
            logger.info(f"{self.user} Already following @{clean_account_name}")
            return True

        # Follow the user
        is_followed = await self.twitter_client.follow(user.id)

        if is_followed:
            logger.success(f"{self.user} Followed @{clean_account_name}")
            return True
        else:
            logger.warning(
                f"{self.user} Failed to follow @{clean_account_name}"
            )
            return False


    async def _check_if_following(self, user_id: int) -> bool:
        """
        Checks if the current user is following the specified user

        Args:
            user_id: ID of the user to check

        Returns:
            True if already following, False otherwise
        """

        following = await self.twitter_client.request_followings()
        if following:
            for followed_user in following:
                if str(followed_user.id) == str(user_id):
                    return True
        return False

    async def post_tweet(self, text: str) -> Optional[Any]:
        """
        Posts a tweet with the specified text

        Args:
            text: Tweet text

        Returns:
            Tweet object on success, None on error
        """
        if not self.twitter_client:
            initialize = await self.initialize()
            if not initialize:
                raise Exception("Can't initialize twitter client")
        # Post the tweet
        tweet = await self.twitter_client.tweet(text)

        if tweet:
            logger.success(f"{self.user} Tweet posted (ID: {tweet.id})")
            return tweet
        else:
            logger.warning(f"{self.user} Failed to post tweet")
            return None


    async def retweet(self, tweet_id: int) -> bool:
        """
        Retweets the specified tweet

        Args:
            tweet_id: ID of the tweet to retweet

        Returns:
            Success status
        """

        if not self.twitter_client:
            initialize = await self.initialize()
            if not initialize:
                raise Exception("Can't initialize twitter client")

        # Perform retweet
        retweet_id = await self.twitter_client.repost(tweet_id)

        if retweet_id:
            logger.success(f"{self.user} Retweet successful")
            return True
        else:
            logger.warning(f"{self.user} Failed to retweet")
            return False

    async def reply(self, tweet_id: int, reply_text: str) -> bool:
        """
        Reply the specified tweet

        Args:
            tweet_id: ID of the tweet to retweet
            reply_text: Text for reply
        Returns:
            Success status
        """

        if not self.twitter_client:
            initialize = await self.initialize()
            if not initialize:
                raise Exception("Can't initialize twitter client")

        reply_id = await self.twitter_client.reply(tweet_id=tweet_id, text=reply_text)

        if reply_id:
            logger.success(f"{self.user} Reply successful {reply_id}")
            return True
        else:
            logger.warning(f"{self.user} Failed to reply ")
            return False

    async def like_tweet(self, tweet_id: int) -> bool:
        """
        Likes the specified tweet

        Args:
            tweet_id: ID of the tweet to like

        Returns:
            Success status
        """

        if not self.twitter_client:
            initialize = await self.initialize()
            if not initialize:
                raise Exception("Can't initialize twitter client")

        # Like the tweet
        is_liked = await self.twitter_client.like(tweet_id)

        if is_liked:
            logger.success(f"{self.user} Like successful")
            return True
        else:
            logger.warning(f"{self.user} Failed to like")
            return False




    async def connect_twitter_to_site_oauth(self, twitter_auth_url:str) -> TwitterOauthData:
        """
        Connects Twitter to Site using oauth

        Returns:
            TwitterOauthData
        """

        if not self.twitter_client:
            initialize = await self.initialize()
            if not initialize:
                raise Exception("Can't initialize twitter client")

        browser = Browser(wallet=self.user)
        logger.debug(f"{self.user} Requesting Twitter authorization parameters")

        parsed_url = urllib.parse.urlparse(twitter_auth_url)
        query_params = urllib.parse.parse_qs(parsed_url.query)

        # Extract required parameters
        oauth_token = query_params.get("oauth_token", [""])[0]

        auth_code,redirect_url  = await self.twitter_client.oauth(oauth_token=oauth_token)

        if not auth_code:
            logger.error(
                f"{self.user} Failed to obtain authorization code from Twitter"
            )
            raise Exception("Not auth code")

        parsed_url = urllib.parse.urlparse(redirect_url)
        query_params = urllib.parse.parse_qs(parsed_url.query)

        # Extract required parameters
        oauth_token = query_params.get("oauth_token", [""])[0]
        oauth_verifer = query_params.get("oauth_verifier", [""])[0]

        logger.debug(redirect_url)


        callback_headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
            "Referer": "https://x.com/",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "cross-site",
        }

        resp = await browser.get(
            url=redirect_url,
            headers=callback_headers,
            timeout=30,
        )

        return TwitterOauthData(auth_token=oauth_token, state_verifier_token=oauth_verifer, callback_url=redirect_url, callback_response=resp)


    async def connect_twitter_to_site_oauth2(self, twitter_auth_url:str) -> TwitterOauthData:
        """
        Connects Twitter to Site using oauth2

        Returns:
            TwitterOauthData
        """

        if not self.twitter_client:
            initialize = await self.initialize()
            if not initialize:
                raise Exception("Can't initialize twitter client")

        browser = Browser(wallet=self.user)
        logger.debug(f"{self.user} Requesting Twitter authorization parameters")

        parsed_url = urllib.parse.urlparse(twitter_auth_url)
        query_params = urllib.parse.parse_qs(parsed_url.query)

        state = query_params.get("state", [""])[0]
        code_challenge = query_params.get("code_challenge", [""])[0]
        client_id = query_params.get(
            "client_id", [""]
        )[0]
        redirect_uri = query_params.get(
            "redirect_uri",
            [""],
        )[0]
        response_type = query_params.get("response_type", [""])[0]
        scope = query_params.get("scope", [""])[0]
        code_challenge_method = query_params.get("code_challenge_method", [""])[0]

        if not state or not code_challenge:
            raise Exception("Failed to extract parameters from authorization URL")

        oauth2_data = {
            "response_type": response_type,
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": scope,
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": code_challenge_method
        }

        auth_code = await self.twitter_client.oauth2(**oauth2_data)

        if not auth_code:
            logger.error(
                f"{self.user} Failed to obtain authorization code from Twitter"
            )
            raise Exception("Not auth code")

        callback_url = f"{redirect_uri}?state={state}&code={auth_code}"

        callback_headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            'Accept-Encoding': 'gzip, deflate',
            "Referer": "https://x.com/",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "cross-site",
        }

        resp = await browser.get(
            url=callback_url,
            headers=callback_headers,
        )
        return TwitterOauthData(auth_token=auth_code, state_verifier_token=state, callback_url=callback_url, callback_response=resp)


