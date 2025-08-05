import asyncio
import random

from faker import Faker
from loguru import logger

from libs.eth_async.client import Client
from libs.base import Base
from modules.pharos_portal import PharosPortal
from modules.pns import PNS
from modules.primus import Primus
from modules.zenith import Zenith

from utils.db_api.models import Wallet
from utils.db_api.wallet_api import db
from utils.logs_decorator import controller_log
from utils.query_json import query_to_json
from utils.twitter.twitter_client import TwitterClient


class Controller:
    __controller__ = 'Controller'

    def __init__(self, client: Client, wallet: Wallet):
        #super().__init__(client)
        self.client = client
        self.wallet = wallet
        self.base = Base(client=client, wallet=wallet)
        self.pharos_portal = PharosPortal(client=client, wallet=wallet)
        self.twitter = TwitterClient(user=wallet)
        self.zenith = Zenith(client=client, wallet=wallet)
        self.primus = Primus(client=client, wallet=wallet)
        self.pns = PNS(client=client, wallet=wallet)

    @controller_log('CheckIn')
    async def check_in_task(self):
        check_in = await self.pharos_portal.check_in()
        return check_in

    @controller_log('Random Swap')
    async def random_swap(self):
        swap_protocols = [
            self.zenith.swaps_controller(),
        ]

        swap = random.choice(swap_protocols)

        return await swap

    @controller_log('Bind Twitter Task')
    async def twitter_bind(self):

        return await self.pharos_portal.bind_twitter_task()

    @controller_log('Faucet Task')
    async def faucet_task(self, registration=False):

        await self.pharos_portal.login(registration=registration)

        user_data = await self.pharos_portal.get_user_info()

        if user_data.get('XId') == '':
            auth_url = await self.pharos_portal.get_twitter_link()

            oauth2 = await self.twitter.connect_twitter_to_site_oauth2(twitter_auth_url=auth_url)

            bind = await self.pharos_portal.bind_twitter(redirect_url=oauth2.callback_url)

            logger.success(f'{self.wallet} | {bind}')

            await asyncio.sleep(random.randint(5, 10))

        status = await self.pharos_portal.faucet()

        if 'Failed' not in status:
            return status

        raise Exception(status)

    @controller_log('Twitter Tasks')
    async def twitter_tasks(self, twitter_tasks: list):

        results = []

        try:
            await self.twitter.initialize()

            for task in twitter_tasks:
                if task['task_type'] == 'twitter':
                    #todo follow, retweet, reply in twitter
                    name = task['name']
                    if 'Follow' in name:
                        follow = query_to_json(task['url'])
                        result = await self.twitter.follow_account(account_name=follow['screen_name'])

                        await asyncio.sleep(random.randint(3, 7))

                        if result:
                            task_status = await self.pharos_portal.verify_task(task=task)
                            results.append(task_status)

                    if 'Retweet' in name:
                        retweet = query_to_json(task['url'])
                        result = await self.twitter.retweet(tweet_id=retweet['tweet_id'])

                        await asyncio.sleep(random.randint(3, 7))

                        if result:
                            task_status = await self.pharos_portal.verify_task(task=task)
                            results.append(task_status)

                    if 'Reply' in name:
                        retweet = query_to_json(task['url'])
                        faker = Faker()

                        fake_sentence = faker.sentence(variable_nb_words=False)
                        result = await self.twitter.reply(tweet_id=retweet['in_reply_to'], reply_text=fake_sentence)

                        await asyncio.sleep(random.randint(3, 7))

                        if result:
                            task_status = await self.pharos_portal.verify_task(task=task)
                            results.append(task_status)

            return results

        except Exception as e:
            logger.error(e)

        finally:
            await self.twitter.close()

                    #task = await self.pharos_portal.verify_task(task=task)

        #return social_to_do



    async def stake_tasks(self):
        # todo random stake with logs
        pass