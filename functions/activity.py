import asyncio
import os
import random
from datetime import datetime, timedelta
from typing import List

from loguru import logger

from data.config import FILES_DIR
from data.settings import Settings
from functions.controller import Controller
from libs.eth_async.client import Client
from libs.eth_async.data.models import Networks
from modules.euclid import EuclidSwap
from utils.db_api.models import Wallet
from utils.db_api.wallet_api import db
from utils.discord.discord import DiscordStatus
from utils.encryption import check_encrypt_param
from utils.resource_manager import replace_twitter_tokens
from utils.twitter.twitter_client import TwitterStatuses


async def random_sleep_before_start(wallet):
    random_sleep = random.randint(Settings().random_pause_start_wallet_min, Settings().random_pause_start_wallet_max)
    now = datetime.now()

    logger.info(f"{wallet} Start at {now + timedelta(seconds=random_sleep)} sleep {random_sleep} seconds before start actions")
    await asyncio.sleep(random_sleep)


async def random_activity_task(wallet):
    try:
        await random_sleep_before_start(wallet=wallet)

        if wallet.twitter_status and wallet.twitter_status in [
            TwitterStatuses.bad_token,
            TwitterStatuses.relogin,
            TwitterStatuses.locked,
            TwitterStatuses.not_found,
        ]:
            wallet = await replace_twitter_tokens(wallet=wallet)

        client = Client(private_key=wallet.private_key, network=Networks.PharosTestnet, proxy=wallet.proxy)
        controller = Controller(client=client, wallet=wallet)

        actions = await controller.build_actions()

        if isinstance(actions, str):
            logger.warning(actions)

        else:
            logger.info(f"{wallet} | Started Activity Tasks | Wallet will do {len(actions)} actions")

            for action in actions:
                sleep = random.randint(Settings().random_pause_between_actions_min, Settings().random_pause_between_actions_max)
                try:
                    status = await action()

                    if "Failed" not in status:
                        logger.success(status)
                    else:
                        logger.error(status)

                except Exception as e:
                    logger.error(e)
                    continue

                finally:
                    await asyncio.sleep(sleep)

        await controller.update_db_by_user_info()

    except asyncio.CancelledError:
        raise

    except Exception as e:
        logger.error(f"Core | Random Activity | {wallet} | {e}")
        raise e


async def execute(wallets: List[Wallet], task_func, random_pause_wallet_after_completion: int = 0):
    while True:
        semaphore = asyncio.Semaphore(min(len(wallets), Settings().threads))

        if Settings().shuffle_wallets:
            random.shuffle(wallets)

        async def sem_task(wallet: Wallet):
            async with semaphore:
                try:
                    await asyncio.wait_for(task_func(wallet), timeout=3600)

                except asyncio.TimeoutError:
                    logger.error(f"[{wallet.id}] Core Execution Tasks |{task_func.__name__} timed out after 60m")

                except Exception as e:
                    logger.error(f"[{wallet.id}] failed: {e}")

        tasks = [asyncio.create_task(sem_task(wallet)) for wallet in wallets]
        await asyncio.gather(*tasks, return_exceptions=True)

        if random_pause_wallet_after_completion == 0:
            break

        # update dynamically the pause time
        random_pause_wallet_after_completion = random.randint(
            Settings().random_pause_wallet_after_completion_min, Settings().random_pause_wallet_after_completion_max
        )

        next_run = datetime.now() + timedelta(seconds=random_pause_wallet_after_completion)
        logger.info(f"Sleeping {random_pause_wallet_after_completion} seconds. Next run at: {next_run.strftime('%Y-%m-%d %H:%M:%S')}")
        await asyncio.sleep(random_pause_wallet_after_completion)


async def activity(action: int):
    if not check_encrypt_param():
        logger.error(f"Decryption Failed | Wrong Password")
        return

    wallets = db.all(Wallet)

    range_wallets = Settings().range_wallets_to_run
    if range_wallets != [0, 0]:
        start, end = range_wallets
        wallets = [wallet for i, wallet in enumerate(wallets, start=1) if start <= i <= end]
    else:
        if Settings().exact_wallets_to_run:
            wallets = [wallet for i, wallet in enumerate(wallets, start=1) if i in Settings().exact_wallets_to_run]

    if action == 1:
        await execute(
            wallets,
            random_activity_task,
            random.randint(Settings().random_pause_wallet_after_completion_min, Settings().random_pause_wallet_after_completion_max),
        )

    elif action == 2:
        await execute(wallets, twitter_tasks, Settings().sleep_after_each_cycle_hours)

    elif action == 3:
        wallets = [wallet for wallet in wallets if wallet.discord_token is not None and wallet.discord_status in [None, DiscordStatus.ok]]

        if len(wallets) == 0:
            logger.warning(f"Core | Founded {len(wallets)} wallets with discord tokens, import some tokens in DB. Exiting...")
            return

        if Settings().discord_proxy:
            file_path = os.path.join(FILES_DIR, "discord_proxy.txt")

            with open(file_path, "r", encoding="utf-8") as f:
                discord_proxies = f.read().splitlines()

            if len(discord_proxies) == 0:
                logger.warning("Core | No discord proxies provided, add some proxies in files/discord_proxy.txt. Exiting...")
                return

            n_proxies = len(discord_proxies)

            for i, w in enumerate(wallets):
                w.discord_proxy = discord_proxies[i % n_proxies]

        await execute(wallets, join_discord, 0)

    elif action == 4:
        await execute(wallets, update_points)

    elif action == 5:
        await execute(wallets, mint_nft_badges)

    elif action == 6:
        await execute(wallets, transfer_from_monad)


async def transfer_from_monad(wallet):
    await random_sleep_before_start(wallet=wallet)
    monad_transfer = EuclidSwap(wallet=wallet)

    try:
        result = await monad_transfer.swap_controller()

        if "Failed" not in result:
            logger.success(result)

            return result

        logger.error(result)

    except Exception as e:
        logger.error(e)


async def join_discord(wallet):
    client = Client(private_key=wallet.private_key, proxy=wallet.proxy, network=Networks.PharosTestnet)

    controller = Controller(client=client, wallet=wallet)

    try:
        result = await controller.bind_discord_flow()

        if "Failed" not in result:
            logger.success(result)

            return result

        logger.error(result)

    except Exception as e:
        logger.error(e)


async def random_swaps(wallet):
    client = Client(private_key=wallet.private_key, proxy=wallet.proxy, network=Networks.PharosTestnet)

    controller = Controller(client=client, wallet=wallet)
    try:
        result = await controller.random_swap()

        if "Failed" not in result:
            logger.success(result)

            return result

        logger.error(result)

    except Exception as e:
        logger.error(e)


async def twitter_tasks(wallet):
    client = Client(private_key=wallet.private_key, proxy=wallet.proxy, network=Networks.PharosTestnet)

    controller = Controller(client=client, wallet=wallet)
    try:
        user_data = await controller.pharos_portal.get_user_info()

        if user_data.get("XId") == "":
            auth_url = await controller.pharos_portal.get_twitter_link()

            oauth2 = await controller.twitter.connect_twitter_to_site_oauth2(twitter_auth_url=auth_url)

            bind = await controller.pharos_portal.bind_twitter(redirect_url=oauth2.callback_url)

            if "Failed" not in bind:
                logger.success(f"{wallet} | {bind}")

                await asyncio.sleep(random.randint(5, 10))

            user_data = await controller.pharos_portal.get_user_info()

        if user_data.get("XId") != "":
            user_tasks = await controller.user_tasks()

            twitter_tasks, discord_tasks = await controller.pharos_portal.tasks_flow()

            twitter_tasks = await controller.pharos_portal.prepare_twitter_tasks(twitter_tasks=twitter_tasks, user_tasks=user_tasks)
            if not twitter_tasks:
                logger.info(f"{wallet} No new twitter tasks available")
                return

            result = await controller.twitter_tasks(twitter_tasks)

            if "Failed" not in result:
                logger.success(result)

                return result

            logger.exception(result)

    except Exception as e:
        logger.error(e)


async def update_points(wallet):
    client = Client(private_key=wallet.private_key, proxy=wallet.proxy, network=Networks.PharosTestnet, check_proxy=False)

    controller = Controller(client=client, wallet=wallet)

    await controller.update_db_by_user_info()


async def mint_nft_badges(wallet):
    await random_sleep_before_start(wallet=wallet)

    client = Client(private_key=wallet.private_key, proxy=wallet.proxy, network=Networks.PharosTestnet, check_proxy=False)

    controller = Controller(client=client, wallet=wallet)
    # native = await controller.zenith.swaps_controller(to_native=True)
    # logger.success(native)
    await controller.mint_nft_badges()
