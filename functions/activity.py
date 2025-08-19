import asyncio
import random
from datetime import datetime, timedelta
from typing import List

from curl_cffi import AsyncSession
from loguru import logger

from functions.controller import Controller
from functions.select_random_action import select_random_action
from libs.eth_async.client import Client
from libs.eth_async.data.models import Networks
from utils.db_api.models import Wallet
from utils.db_api.wallet_api import db
from data.settings import Settings
from utils.encryption import check_encrypt_param
from utils.db_update import update_next_action_time, update_expired

async def random_sleep_before_start(wallet):
    random_sleep = random.randint(Settings().random_pause_start_wallet_min, Settings().random_pause_start_wallet_max)
    now = datetime.now()

    logger.info(f"{wallet} Start at {now + timedelta(seconds=random_sleep)} sleep {random_sleep} seconds before start actions")
    await asyncio.sleep(random_sleep)

async def random_activity_task(wallet):

    try:
        await random_sleep_before_start(wallet=wallet)

        client = Client(private_key=wallet.private_key, network=Networks.PharosTestnet, proxy=wallet.proxy)
        controller = Controller(client=client, wallet=wallet)

        actions = await controller.build_actions()

        if isinstance(actions, str):
            logger.warning(actions)

        else:
            logger.info(f'{wallet} | Started Activity Tasks | Wallet will do {len(actions)} actions')

            for action in actions:

                sleep = random.randint(Settings().random_pause_between_actions_min,
                                       Settings().random_pause_between_actions_max)
                try:
                    status = await action()

                    if 'Failed' not in status:
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
        logger.error(f'Core | Activity | {wallet} |{e}')
        raise e


async def execute(wallets : Wallet, task_func, random_pause_wallet_after_completion : int = 0):
    
    while True:
        
        semaphore = asyncio.Semaphore(min(len(wallets), Settings().threads))

        if Settings().shuffle_wallets:
            random.shuffle(wallets)
            
        async def sem_task(wallet : Wallet):
            async with semaphore:
                try:
                    await task_func(wallet)
                except Exception as e:
                    logger.error(f"[{wallet.id}] failed: {e}")

        tasks = [asyncio.create_task(sem_task(wallet)) for wallet in wallets]
        await asyncio.gather(*tasks, return_exceptions=True)

        if random_pause_wallet_after_completion == 0:
            break
 
        next_run = datetime.now() + timedelta(seconds=random_pause_wallet_after_completion)
        logger.info(
            f"Sleeping {random_pause_wallet_after_completion} seconds. "
            f"Next run at: {next_run.strftime('%Y-%m-%d %H:%M:%S')}"
        )
        await asyncio.sleep(random_pause_wallet_after_completion)
        

async def activity(action: int):
    check_encrypt_param()

    try:
        check_password_wallet = db.one(Wallet, Wallet.id == 1)
        client = Client(private_key=check_password_wallet.private_key)

    except Exception as e:
        logger.error(f"Decryption Failed | Wrong Password")
        return


    all_wallets = db.all(Wallet)

    # Filter wallets if EXACT_WALLETS_TO_USE is defined
    if Settings().exact_wallets_to_run:
        wallets = [wallet for i, wallet in enumerate(all_wallets, start=1) if i in Settings().exact_wallets_to_run]
    else:
        wallets = all_wallets

    if action == 1:
        await execute(wallets, random_activity_task, random.randint(Settings().random_pause_wallet_after_completion_min, Settings().random_pause_wallet_after_completion_max))

    if action == 2:
        await execute(wallets, twitter_tasks, Settings().sleep_after_each_cycle_hours)
        
    if action == 3:
        await execute(wallets, random_swaps, Settings().sleep_after_each_cycle_hours)


async def random_swaps(wallet):
    client = Client(private_key=wallet.private_key, proxy=wallet.proxy, network=Networks.PharosTestnet)

    controller = Controller(client=client, wallet=wallet)
    try:
        result = await controller.random_swap()

        if 'Failed' not in result:
            logger.success(result)

            return result

        logger.error(result)

    except Exception as e:
        logger.error(e)
        
async def twitter_tasks(wallet):
    client = Client(private_key=wallet.private_key, proxy=wallet.proxy, network=Networks.PharosTestnet)

    controller = Controller(client=client, wallet=wallet)
    try:
        twitter_tasks, discord_tasks = await controller.pharos_portal.tasks_flow()
        if not twitter_tasks:
            logger.info(f"{wallet} No new twitter tasks available")
            return
        result = await controller.twitter_tasks(twitter_tasks=twitter_tasks)

        if 'Failed' not in result:
            logger.success(result)

            return result

        logger.error(result)

    except Exception as e:
        logger.error(e)
                
