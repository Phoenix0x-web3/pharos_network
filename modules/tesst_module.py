import asyncio
from libs.eth_async.client import Client
from libs.base import Base
from utils.browser import Browser
from utils.db_api.models import Wallet
from utils.logs_decorator import controller_log
from utils.twitter.twitter_client import TwitterClient


class TestModule(Base):
    __module_name__ = "Test Module 1"

    def __init__(self, client: Client, wallet: Wallet):
        self.client = client
        self.wallet = wallet
        self.browser = Browser(wallet=self.wallet)
        self.twitter = TwitterClient(user=wallet)

        self.headers = {
            "Origin": "https://app.testings.Headers"
            }

    @controller_log("Testing Requests")
    async def test_module_reqs(self):

        url = 'https://webhook.site/30f29d59-5974-43ed-8e7d-e87e61a2cc46'

        r = await self.browser.get(url=url, headers=self.headers)
        r.raise_for_status()
        r = await self.browser.get(url=url)

        return r.json()

    @controller_log("Testing Twitter")
    async def twitter_test_module_initialize_with_token(self):
        return await self.twitter.initialize()

    @controller_log("Testing Twitter")
    async def twitter_test_module_initialize_with_login(self):
        twitter = TwitterClient(user=self.wallet, twitter_username="Na66252527", twitter_password="2qP20c8KZ9")
        return await twitter.initialize()

    @controller_log("Testing Twitter")
    async def twitter_test_follow_account_and_check_already_follow(self):
        await self.twitter.follow_account(account_name="playcambria")
        return 

    @controller_log("Testing Twitter")
    async def twitter_test_like_tweet(self):
        await self.twitter.like_tweet(tweet_id=1915140195629904126)
        await asyncio.sleep(5)
        await self.twitter.like_tweet(tweet_id=1915140195629904126)
        return 

    @controller_log("Testing Twitter")
    async def twitter_test_retweet(self):
        await self.twitter.retweet(tweet_id=1915140195629904126)
        await asyncio.sleep(5)
        await self.twitter.retweet(tweet_id=1915140195629904126)
        return 

    @controller_log("Testing Twitter")
    async def twitter_test_post(self):
        await self.twitter.post_tweet(text="Hello World!")
        await asyncio.sleep(5)
        await self.twitter.post_tweet(text="Hello World!")
        return 


    @controller_log("Testing Twitter")
    async def connect_pharos(self):
        # PASS
        url = ("https://twitter.com/i/oauth2/authorize?client_id=TGQwNktPQWlBQzNNd1hyVkFvZ2E6MTpjaQ&code_challenge=75n30zliaiuudJJfwo6-1Tmyz21LabzUNqMUNd5m6nQ&code_challenge_method=S256"
               "&redirect_uri=https://testnet.pharosnetwork.xyz&response_type=code&scope=users.read tweet.read follows.read&state=twitterHQP-LbSi6BYLc3A04y-TiOmFHwyJFgJlwThoZsA9EBG")

        #URL - всегда получаем новый корректный линк от АПИ проекта на oauth (с allow_redirect=false)


        # на стороне TwitterLIB (( твиттерлиб не должен ничего в проект отправлять, только отдавать коды и заниматься твиттером)
            #Получили link - начинаем через либу твиттера получать код ouath
            #Получу код - подтвердили
            #Вернули подтверждение в переменную в запускающий модуль

        #Привязали через апи проекта
        #Получили код -> вернули код в проект (api_url)
        api_url = "https://api.pharosnetwork.xyz/auth/bind/twitter"

        json_template = {
            'state': '{{state}}',
            'code': '{{auth_code}}',
            'address': '0x5de75856754f6482f131B8BEd19769e6E0445F42'
        }
        headers = {
            'Referer': 'https://testnet.pharosnetwork.xyz/',
        }
        resp = await self.twitter.connect_twitter_to_site_oauth2(twitter_auth_url=url, api_url=api_url, json_template=json_template, additional_headers=headers)
        if resp:
            logger.debug(resp.status_code)
            logger.debug(resp.json())



