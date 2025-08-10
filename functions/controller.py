import asyncio
import random

from faker import Faker
from loguru import logger

from data.settings import Settings
from modules.autostaking import AutoStaking
from libs.eth_async.client import Client
from libs.base import Base
from modules.brokex import Brokex
from modules.pharos_portal import PharosPortal
from modules.pns import PNS
from modules.primus import Primus
from modules.rwafi import AquaFlux
from modules.zenith import Zenith

from utils.db_api.models import Wallet
from utils.db_api.wallet_api import db
from utils.logs_decorator import controller_log
from utils.query_json import query_to_json
from utils.twitter.twitter_client import TwitterClient
from utils.db_update import update_points_invites

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
        self.autostaking = AutoStaking(client=client, wallet=wallet)
        self.brokex = Brokex(client=client, wallet=wallet)
        self.aquaflux = AquaFlux(client=client, wallet=wallet)

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
            return f'Failed | {e}'

        finally:
            await self.twitter.close()

    @controller_log('AutoStaking')
    async def autostaking_task(self):
        return await self.autostaking.autostacking_flow()

    @controller_log('Brokex USDC Faucet')
    async def brokex_faucet(self):

        return await self.brokex.claim_faucet()

    @controller_log('Aquaflux Flow')
    async def aquaflux_flow(self):
        settings = Settings()
        aquaflux_twitter_bound = await self.aquaflux.twitter_bound()

        if not aquaflux_twitter_bound:
            twitter_auth_url = await self.aquaflux.twitter_initiate()

            oauth2 = await self.twitter.connect_twitter_to_site_oauth2(twitter_auth_url=twitter_auth_url)

            bind_twitter = await self.aquaflux.bind_twitter(callback_data=oauth2)

            if 'Failed' not in bind_twitter:
                logger.success(bind_twitter)
                await asyncio.sleep(random.randint(5,10))
                result = await self.twitter.follow_account(account_name='AquaFluxPro')
                await asyncio.sleep(random.randint(3, 7))

        check_twitter_following = await self.aquaflux.check_twitter_following()

        if not check_twitter_following:
            result = await self.twitter.follow_account(account_name='AquaFluxPro')
            await asyncio.sleep(random.randint(3, 7))

            return await self.aquaflux_flow()

        claim_tokens = await self.aquaflux.claim_tokens()

        if 'Failed' not in claim_tokens:
            logger.success(claim_tokens)
            await asyncio.sleep(random.randint(settings.random_pause_between_actions_min, settings.random_pause_between_actions_max))

            combine = await self.aquaflux.combine()
            if 'Failed' not in combine:
                logger.success(combine)
                await asyncio.sleep(
                    random.randint(settings.random_pause_between_actions_min, settings.random_pause_between_actions_max))

                mint = await self.aquaflux.mint()
                if 'Failed' not in mint:
                    return mint

        return 'Failed'



    async def build_actions(self):

        final_actions = []

        settings = Settings()

        build_array = []

        swaps_count = random.randint(settings.swaps_count_min, settings.swaps_count_max)
        tips_count = random.randint(settings.tips_count_min, settings.tips_count_max)
        autostake_count = random.randint(settings.autostake_count_min, settings.autostake_count_max)

        wallet_balance = await self.client.wallet.balance()

        if wallet_balance.Ether == 0:
            register = await self.faucet_task(registration=True)
            logger.success(register)

        if wallet_balance:
            faucet_status = await self.pharos_portal.get_faucet_status()

            twitter_tasks, discord_tasks = await self.pharos_portal.tasks_flow()

            aquaflux_nft = await self.aquaflux.already_minted(premium=True)

            if faucet_status.get('data').get('is_able_to_faucet'):
                final_actions.append(lambda: self.faucet_task())

            if len(twitter_tasks) > 0:
                build_array.append(lambda: self.twitter_tasks(twitter_tasks=twitter_tasks))

            if wallet_balance.Ether > 0.35:
                domains = await self.pns.check_pns_domain()

                if len(domains) == 0:
                    build_array.append(lambda: self.pns.mint())

            if not aquaflux_nft:
                build_array.append(lambda: self.aquaflux_flow())

            swaps = [lambda: self.random_swap() for _ in range(swaps_count)]

            tips = [lambda: self.primus.tip() for _ in range(tips_count)]

            autostake = [lambda: self.autostaking_task() for _ in range(autostake_count)]

            brokex = [lambda: self.brokex_faucet()]

            all_actions = swaps + tips + autostake + brokex + build_array

            random.shuffle(all_actions)

            final_actions += all_actions

        return final_actions


    async def update_db_by_user_info(self):
        await self.pharos_portal.login()

        user_data = await self.pharos_portal.get_user_info()
        
        total_points = user_data.get('TotalPoints')
        invite_code = user_data.get('InviteCode')
        
        await update_points_invites(self.wallet.private_key, total_points, invite_code)
        