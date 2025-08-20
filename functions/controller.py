import asyncio
import json
import random

from faker import Faker
from loguru import logger
from sqlalchemy.testing.suite.test_reflection import users

from data.settings import Settings
from modules.autostaking import AutoStaking
from libs.eth_async.client import Client
from libs.base import Base
from modules.brokex import Brokex
from modules.faroswap import Faroswap, FaroswapLiquidity
from modules.nft_badges import NFTS
from modules.pharos_portal import PharosPortal
from modules.pns import PNS
from modules.primus import Primus
from modules.rwafi import AquaFlux
from modules.zenith import Zenith, ZenithLiquidity

from utils.db_api.models import Wallet
from utils.db_api.wallet_api import db
from utils.discord.discord import DiscordOAuth, DiscordInviter, DiscordStatus
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
        self.zenith_liq = ZenithLiquidity(client=client, wallet=wallet)
        self.primus = Primus(client=client, wallet=wallet)
        self.pns = PNS(client=client, wallet=wallet)
        self.autostaking = AutoStaking(client=client, wallet=wallet)
        self.brokex = Brokex(client=client, wallet=wallet)
        self.aquaflux = AquaFlux(client=client, wallet=wallet)
        self.nfts = NFTS(client=client, wallet=wallet)
        self.faroswap = Faroswap(client=client, wallet=wallet)
        self.faroswap_liqudity = FaroswapLiquidity(client=client, wallet=wallet)


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

    async def random_liquidity(self):

        liq_protocols = [
            self.zenith_liq.liquidity_controller(),
        ]

        liq = random.choice(liq_protocols)

        return await liq

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

            if 'Failed' not in bind:
                logger.success(f'{self.wallet} | {bind}')

                await asyncio.sleep(random.randint(5, 10))

        status = await self.pharos_portal.faucet()

        if 'Failed' not in status:
            return status

        raise Exception(f"{self.wallet} | Error in Faucet Task")


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

    async def discord_tasks(self, tasks: list):
        try:
            for task in tasks:
                if task['task_type'] == 'discord':
                    name = task['name']
                    task_status = await self.pharos_portal.verify_task(task=task)
                    return f'Success | Verify {name} {task_status}'

        except Exception as e:
            logger.error(e)
            return f'Failed | {e}'

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

    async def user_tasks(self) -> dict:
        """
        108 - tips
        101 - swaps
        102 - liq
        110 - Autostacking
        111 - Brokex
        """
        tasks = await self.pharos_portal.get_user_tasks(user=True)
        result = {str(task.get("TaskId")): task.get("CompleteTimes") for task in tasks}
        return result

    async def brokex_positions(self):
        actions = [
            self.brokex.open_position_controller
        ]

        positions = await self.brokex.get_user_open_ids()

        if len(positions) >= 1:
            actions.append(self.brokex.close_position_controller)

        position_action = random.choice(actions)

        return await position_action()

    @staticmethod
    async def form_actions(have: int, factory, count: int):
        limit = 91

        n = count if have < limit else random.randint(1, 3)
        return [factory for _ in range(n)]

    async def build_actions(self):

        final_actions = []

        settings = Settings()

        build_array = []

        swaps_count = random.randint(settings.swaps_count_min, settings.swaps_count_max)
        swaps_faroswap = random.randint(settings.swaps_count_min, settings.swaps_count_max)
        tips_count = random.randint(settings.tips_count_min, settings.tips_count_max)
        autostake_count = random.randint(settings.autostake_count_min, settings.autostake_count_max)
        brokex_count = random.randint(settings.brokex_count_min, settings.brokex_count_max)

        #todo check TX in brokex and zentih for liq
        lp_count = random.randint(settings.liquidity_count_min, settings.liquidity_count_max)
        defi_lp_count = random.randint(settings.liquidity_count_min, settings.liquidity_count_max)
        faro_lp_count = random.randint(settings.liquidity_count_min, settings.liquidity_count_max)

        wallet_balance = await self.client.wallet.balance()

        if wallet_balance.Ether == 0:
            register = await self.faucet_task(registration=True)
            logger.success(register)

            await asyncio.sleep(9, 12)
            wallet_balance = await self.client.wallet.balance()

            if wallet_balance.Ether == 0:
                raise Exception(f'{self.wallet} | Failed Faucet | Got 0 PHRS after registration task')


        if wallet_balance:
            faucet_status = await self.pharos_portal.get_faucet_status()

            if faucet_status.get('data').get('is_able_to_faucet'):
                final_actions.append(lambda: self.faucet_task())

            if float(wallet_balance.Ether) <= 0.0001:
                if len(final_actions) == 0:

                    return f"{self.wallet} | Not enought balance for actions | Awaiting for next faucet"

            twitter_tasks, discord_tasks = await self.pharos_portal.tasks_flow()

            aquaflux_nft = await self.aquaflux.already_minted(premium=True)

            brokex_faucet = await self.brokex.has_claimed()

            if len(twitter_tasks) > 0:
                build_array.append(lambda: self.twitter_tasks(twitter_tasks=twitter_tasks))

            if wallet_balance.Ether > 0.35:
                domains = await self.pns.check_pns_domain()

                if len(domains) == 0:
                    final_actions.append(lambda: self.pns.mint())

            if wallet_balance.Ether > 1:
                nft_badges = await self.nfts.check_badges()

                if len(nft_badges) > 0:
                    final_actions.append(lambda: self.nfts.nfts_controller(not_minted=nft_badges))

            if not aquaflux_nft:
                build_array.append(lambda: self.aquaflux_flow())
            if not brokex_faucet:
                build_array.append(lambda: self.brokex_faucet())


            user_tasks = await self.user_tasks()

            build_array += await self.form_actions(user_tasks.get("101", 0), self.zenith.swaps_controller, swaps_count)
            build_array += await self.form_actions(user_tasks.get("107", 0), self.faroswap.swap_controller, swaps_faroswap)
            build_array += await self.form_actions(user_tasks.get("102", 0), self.random_liquidity, defi_lp_count)
            build_array += await self.form_actions(user_tasks.get("108", 0), self.primus.tip, tips_count)
            build_array += await self.form_actions(user_tasks.get("110", 0), self.autostaking_task, autostake_count)
            build_array += await self.form_actions(user_tasks.get("111", 0), self.brokex.deposit_liquidity, lp_count // 2)
            build_array += await self.form_actions(user_tasks.get("111", 0), self.brokex_positions, brokex_count)
            build_array += await self.form_actions(user_tasks.get("106", 0), self.faroswap_liqudity.liquidity_controller, faro_lp_count)

            zenith_current_lp = await self.zenith_liq.check_any_positions()

            if zenith_current_lp:
                build_array += [self.zenith_liq.remove_liquidity for _ in range(random.randint(2, 5))]

            random.shuffle(build_array)

            final_actions += build_array

        return final_actions


    async def update_db_by_user_info(self):
        await self.pharos_portal.login()

        user_data = await self.pharos_portal.get_user_info()
        
        total_points = user_data.get('TotalPoints')
        invite_code = user_data.get('InviteCode')
        
        await update_points_invites(self.wallet.private_key, total_points, invite_code)

    @controller_log('Bind Discord')
    async def bind_discord_flow(self):

        user_data = await self.pharos_portal.get_user_info()

        if user_data.get('DiscordId') == "":

            guild_id = '1270276651636232282'

            try:
                if not self.wallet.discord_status:
                    discord_inviter = DiscordInviter(wallet=self.wallet, invite_code='pharos', channel_id=guild_id)

                    join_to_channel = await discord_inviter.start_accept_discord_invite()

                    if 'Failed' not in join_to_channel:

                        self.wallet.discord_status = DiscordStatus.ok
                        db.commit()
                    else:
                        return f'Join Failed | {join_to_channel}'

                if self.wallet.discord_status == DiscordStatus.ok:
                    discord = DiscordOAuth(wallet=self.wallet, guild_id=guild_id)

                    discord_oauth = await self.pharos_portal.get_discord_oauth_code()
                    await asyncio.sleep(random.randint(1, 3))

                    oauth_url, state = await discord.start_oauth2(oauth_url=discord_oauth)
                    await asyncio.sleep(random.randint(1, 3))

                    bind_discord = await self.pharos_portal.bind_discord(url=oauth_url, state=state)
                    if 'Failed' not in bind_discord:
                        logger.success(f"{self.wallet} | {bind_discord}")
                    else:
                        return bind_discord

                    await asyncio.sleep(random.randint(4, 7))

                    user_data = await self.pharos_portal.get_user_info()

                if self.wallet.discord_status == DiscordStatus.bad_token:
                    return 'Failed | Bad Discord Token'

            except Exception as e:
                return f"Failed | {e}"

        if not user_data.get('DiscordId') == "":
            user_tasks = await self.user_tasks()
            if not user_tasks.get('204'):
                _, discord_tasks = await self.pharos_portal.tasks_flow()

                return await self.discord_tasks(tasks=discord_tasks)

            return f"Already verified discord Task"

        return f'Failed | Something Wrong {user_data}'