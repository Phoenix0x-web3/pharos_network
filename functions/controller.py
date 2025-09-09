import asyncio
import json
import random

from faker import Faker
from loguru import logger
from sqlalchemy.testing.suite.test_reflection import users

from data.models import Contracts
from data.settings import Settings
from libs.eth_async.data.models import TokenAmount
from libs.eth_async.utils.utils import randfloat
from modules.R2 import R2, USDC_R2
from modules.autostaking import AutoStaking
from libs.eth_async.client import Client
from libs.base import Base
from modules.bitverse import Bitverse
from modules.brokex import Brokex
from modules.faroswap import Faroswap, FaroswapLiquidity
from modules.gotchipus import Gotchipus
from modules.nft_badges import NFTS
from modules.openfi import OpenFi
from modules.pharos_portal import PharosPortal
from modules.pns import PNS
from modules.primus import Primus
from modules.rwafi import AquaFlux
from modules.spout import Spout
from modules.zenith import Zenith, ZenithLiquidity

from utils.db_api.models import Wallet
from utils.db_api.wallet_api import db
from utils.discord.discord import DiscordOAuth, DiscordInviter, DiscordStatus
from utils.logs_decorator import controller_log
from utils.query_json import query_to_json
from utils.twitter.twitter_client import TwitterClient
from utils.db_update import update_points_invites
from utils.retry import async_retry


class Controller:
    __controller__ = 'Controller'

    def __init__(self, client: Client, wallet: Wallet):
        # super().__init__(client)
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
        self.openfi = OpenFi(client=client, wallet=wallet)
        self.bitverse = Bitverse(client=client, wallet=wallet)
        self.r2 = R2(client=client, wallet=wallet)
        self.spout = Spout(client=client, wallet=wallet)
        self.gotchipus = Gotchipus(client=client, wallet=wallet)

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

    @controller_log('Zenith Faucet')
    async def zenith_faucet(self):
        twitter_link = await self.zenith.zenith_faucet_get_twitter()

        if 'Failed' not in twitter_link:

            if twitter_link.get('state') == 0:
                await self.twitter.initialize()
                bind_url = await self.twitter.connect_twitter_to_site_oauth2(twitter_auth_url=twitter_link.get('url'))
                await asyncio.sleep(random.randint(2, 7))
                twitter_link = await self.zenith.zenith_faucet_get_twitter()

            if twitter_link.get('state') == 1:
                faucet = await self.zenith.zenith_faucet()

                if 'Failed' not in faucet:
                    return faucet
                if 'IP' in faucet:
                    logger.warning(f"{self.wallet} | Zenith Faucet | IP already fauceted today")

                return f'Failed | {faucet}'

        return 'Failed | Twitter Bind'

    @controller_log('Twitter Tasks')
    async def twitter_tasks(self, twitter_tasks: list):

        results = []

        try:
            await self.twitter.initialize()

            for task in twitter_tasks:
                if task['task_type'] == 'twitter':
                    # todo follow, retweet, reply in twitter
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
                await asyncio.sleep(random.randint(5, 10))
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
            await asyncio.sleep(
                random.randint(settings.random_pause_between_actions_min, settings.random_pause_between_actions_max))

            combine = await self.aquaflux.combine()
            if 'Failed' not in combine:
                logger.success(combine)
                await asyncio.sleep(
                    random.randint(settings.random_pause_between_actions_min,
                                   settings.random_pause_between_actions_max))

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
            self.brokex.open_position_controller,
            self.brokex.open_position_controller,
            self.brokex.open_position_controller,
        ]

        positions = await self.brokex.get_user_open_ids()

        if len(positions) >= 1:
            actions.append(self.brokex.close_position_controller)

        position_action = random.choice(actions)

        return await position_action()

    @staticmethod
    async def form_actions(have: int, factory, count: int):
        limit = 91

        n = count if have < limit else random.randint(1, 2)
        return [factory for _ in range(n)]

    async def bitverse_positions(self, refill=None):

        balance = await self.bitverse.get_all_balance()

        settings = Settings()

        percent = randfloat(
            from_=settings.bitverse_percent_min,
            to_=settings.bitverse_percent_max,
            step=0.001
        ) / 100

        if not balance or refill:
            usdt_balance = await self.client.wallet.balance(token=Contracts.USDT.address)

            if float(usdt_balance.Ether) < 10:

                swap = await self.zenith_liq.process_back_swap_from_natve(token=Contracts.USDT, amount=TokenAmount(
                    amount=random.randint(30, 50),
                    decimals=6)
                                                                          )
                return await self.bitverse_positions()

            else:
                deposit = await self.bitverse.deposit(
                    token=Contracts.USDT,
                    amount=TokenAmount(
                        amount=float(usdt_balance.Ether) * percent, decimals=6)
                )
                logger.success(deposit)
                return await self.bitverse_positions()

        balance = float(balance[0]['availableBalanceSize'])

        if balance < 10:
            return await self.bitverse_positions(refill=True)

        amount = max(int(float(balance) * percent), 2)

        return await self.bitverse.bitverse_controller(amount=amount)

    async def r2_stake(self):
        return await self.r2.r2_controller(action='stake')

    async def r2_swap(self):
        return await self.r2.r2_controller(action='swap')

    @controller_log('Send Tokens Onchain')
    async def send_tokens(self):
        amount = randfloat(from_=0.00001, to_=0.0001, step=0.00001)
        amount = TokenAmount(amount=amount)

        tx = await self.base.send_eth(to_address=self.client.account.address, amount=amount)
        tx = tx['transactionHash'].hex()

        return await self.pharos_portal.send_verify(tx=tx)

    async def build_actions(self):

        final_actions = []

        settings = Settings()

        build_array = []

        swaps_count = random.randint(settings.swaps_count_min, settings.swaps_count_max)
        swaps_faroswap = random.randint(settings.swaps_count_min, settings.swaps_count_max)
        tips_count = random.randint(settings.tips_count_min, settings.tips_count_max)
        autostake_count = random.randint(settings.autostake_count_min, settings.autostake_count_max)
        brokex_count = random.randint(settings.brokex_count_min, settings.brokex_count_max)

        # todo check TX in brokex and zentih for liq
        lp_count = random.randint(settings.liquidity_count_min, settings.liquidity_count_max)
        defi_lp_count = random.randint(settings.liquidity_count_min, settings.liquidity_count_max)
        faro_lp_count = random.randint(settings.liquidity_count_min, settings.liquidity_count_max)
        lending_count = random.randint(settings.lending_count_min, settings.lending_count_max)
        bitverse_count = random.randint(settings.bitverse_count_min, settings.bitverse_count_max)

        r2_swap_count = random.randint(settings.r2_count_min, settings.r2_count_max)
        r2_stake_count = random.randint(settings.r2_count_min, settings.r2_count_max)

        spout_count = random.randint(settings.spout_count_min, settings.spout_count_max)

        wallet_balance = await self.client.wallet.balance()

        if wallet_balance.Ether == 0:
            register = await self.faucet_task(registration=True)
            logger.success(register)

            await asyncio.sleep(9, 12)
            wallet_balance = await self.client.wallet.balance()

            if wallet_balance.Ether == 0:
                raise Exception(f'{self.wallet} | Failed Faucet | Got 0 PHRS after registration task')

        if wallet_balance:

            wphrs = await self.client.wallet.balance(token=Contracts.WPHRS)

            if float(wphrs.Ether) > 0:
                await self.base.unwrap_eth(amount=wphrs)

            await asyncio.sleep(3, 5)

            wallet_balance = await self.client.wallet.balance()

            faucet_status = await self.pharos_portal.get_faucet_status()

            if faucet_status.get('data').get('is_able_to_faucet'):
                final_actions.append(lambda: self.faucet_task())


            if float(wallet_balance.Ether) <= 0.0001:
                if len(final_actions) == 0:
                    return f"{self.wallet} | Not enought balance for actions | Awaiting for next faucet"

            usdc_r2_balance = await self.client.wallet.balance(token=USDC_R2)

            if float(usdc_r2_balance.Ether) < 0.3:
                await self.zenith.swap_to_r2_usdc()
                await asyncio.sleep(3, 7)

                usdc_r2_balance = await self.client.wallet.balance(token=USDC_R2)
                wallet_balance = await self.client.wallet.balance()

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
            build_array += await self.form_actions(user_tasks.get("107", 0), self.faroswap.swap_controller,
                                                   swaps_faroswap)
            build_array += await self.form_actions(user_tasks.get("102", 0), self.random_liquidity, defi_lp_count)
            build_array += await self.form_actions(user_tasks.get("108", 0), self.primus.tip, tips_count)
            build_array += await self.form_actions(user_tasks.get("110", 0), self.autostaking_task, autostake_count)
            build_array += await self.form_actions(user_tasks.get("111", 0), self.brokex.deposit_liquidity,
                                                   lp_count // 2)
            build_array += await self.form_actions(user_tasks.get("111", 0), self.brokex_positions, brokex_count)
            build_array += await self.form_actions(user_tasks.get("106", 0),
                                                   self.faroswap_liqudity.liquidity_controller, faro_lp_count)
            build_array += await self.form_actions(user_tasks.get("114", 0), self.openfi.lending_controller,
                                                   lending_count)
            build_array += await self.form_actions(user_tasks.get("119", 0), self.bitverse_positions, bitverse_count)

            build_array += await self.form_actions(user_tasks.get("103", 0), self.send_tokens, tips_count)

            usdc_balance = await self.client.wallet.balance(token=USDC_R2)

            if float(usdc_balance.Ether) > 1:
                build_array += await self.form_actions(user_tasks.get("118", 0), self.spout.swap_controller, spout_count)

            zenith_current_lp = await self.zenith_liq.check_any_positions()

            if zenith_current_lp:
                build_array += [self.zenith_liq.remove_liquidity for _ in range(random.randint(2, 5))]

            if settings.capmonster_api_key != '':

                if random.randint(1, 6) == 1:
                    build_array.append(lambda: self.zenith_faucet())

            gotchipus_ids = await self.gotchipus.get_gotchipus_tokens()

            if not gotchipus_ids:
                build_array.append(lambda: self.gotchipus.flow())

            if gotchipus_ids:
                can_check_in = await self.gotchipus.check_in()
                if can_check_in:
                    build_array.append(lambda: self.gotchipus.check_in())

                can_pet = await self.gotchipus.can_check_pet()
                if can_pet:
                    build_array.append(lambda: self.gotchipus.pet())

                gotchipus_count = random.randint(
                    settings.gotchipus_count_min,
                    settings.gotchipus_count_max
                )

                build_array.extend([lambda: self.gotchipus.transfer_from_gotchipus() for _ in range(gotchipus_count)])

            if float(usdc_r2_balance.Ether) > 0:
                build_array += await self.form_actions(user_tasks.get("117", 0),
                                                       self.r2_swap, r2_swap_count)
                build_array += await self.form_actions(user_tasks.get("116", 0),
                                                       self.r2_stake, r2_stake_count)

            random.shuffle(build_array)

            final_actions += build_array

        return final_actions

    @controller_log('Update Points')
    @async_retry(retries=Settings().retry, delay=3, to_raise=False)
    async def update_db_by_user_info(self):

        await self.pharos_portal.login()

        user_data = await self.pharos_portal.get_user_info()

        total_points = user_data.get('TotalPoints')
        invite_code = user_data.get('InviteCode')
        logger.info(f"{self.wallet} | Total Points: [{total_points}] | Invite Code: [{invite_code}]")
        return await update_points_invites(self.wallet.private_key, total_points, invite_code)

    controller_log("Mint NFT Badges")
    @async_retry(retries=Settings().retry, delay=3, to_raise=False)
    async def mint_nft_badges(self):
        faucet_status = await self.pharos_portal.get_faucet_status()

        if faucet_status.get('data').get('is_able_to_faucet'):
            await self.faucet_task()

        nft_badges = await self.nfts.check_badges()
        random.shuffle(nft_badges)
        for nft_badge in nft_badges:
            wallet_balance = await self.client.wallet.balance()
            if wallet_balance.Ether < 1:
                logger.info(
                    f"{self.wallet} | Not enough balance {wallet_balance} for minting badged | Awaiting for next faucet")
                break

            await self.nfts.nfts_controller(not_minted=[nft_badge])

        return f"Done minting badges"

    @controller_log('Bind Discord')
    async def bind_discord_flow(self):

        if self.wallet.discord_status == DiscordStatus.bad_token:
            return 'Failed | Bad Discord Token'

        if self.wallet.discord_status == DiscordStatus.duplicate:
            return 'Failed | Bad Discord Token | Duplicated, please change discord token'

        user_data = await self.pharos_portal.get_user_info()

        if user_data.get('DiscordId') == "":

            guild_id = '1270276651636232282'

            try:
                if not self.wallet.discord_status:
                    discord_inviter = DiscordInviter(
                        wallet=self.wallet,
                        invite_code='pharos',
                        channel_id=guild_id)

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
                        self.wallet.discord_status = DiscordStatus.duplicate
                        db.commit()
                        return bind_discord

                    await asyncio.sleep(random.randint(4, 7))

                    user_data = await self.pharos_portal.get_user_info()

            except Exception as e:
                return f"Failed | {e}"

        if not user_data.get('DiscordId') == "":
            user_tasks = await self.user_tasks()
            if not user_tasks.get('204'):
                _, discord_tasks = await self.pharos_portal.tasks_flow()

                return await self.discord_tasks(tasks=discord_tasks)
            self.wallet.discord_status = DiscordStatus.ok
            db.commit()
            return f"Already verified discord Task"

        return f'Failed | Something Wrong {user_data}'