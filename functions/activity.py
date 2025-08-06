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
from utils.update_db import update_next_action_time, update_expired

_running_wallets: set[int] = set()
_pending_tasks: set[asyncio.Task] = set()

async def random_activity():
    #check_encrypt_param()
 
    delay = 10

    update_expired()
   
    while True:
        try:
            now = datetime.now()

            wallets: List[Wallet] = db.all(
                Wallet,
                Wallet.next_activity_action_time <= now
            )
            
            if Settings().exact_wallets_to_run:
                wallets = [w for i, w in enumerate(wallets, start=1) if i in Settings().exact_wallets_to_run]


            if not wallets:
                continue

            semaphore = asyncio.Semaphore(Settings().threads)

            async def sem_task(wallet: Wallet):

                async with semaphore:
                    try:
                        await random_activity_task(wallet=wallet)

                    except Exception as e:
                        logger.error(f"[{wallet.id}] failed: {e}")

            if wallets:

                for wallet in wallets:

                    if wallet.id in _running_wallets:
                        continue

                    _running_wallets.add(wallet.id)

                    t = asyncio.create_task(sem_task(wallet))
                    _pending_tasks.add(t)
                    t.add_done_callback(_pending_tasks.discard)

        except Exception as e:
            logger.error(f"Activity Main Task | Error {e}")

        finally:
            await asyncio.sleep(delay)

async def random_activity_task(wallet, semaphore = None):
    settings = Settings()
    delay = 10

    #async with semaphore:

    try:
        client = Client(private_key=wallet.private_key, network=Networks.PharosTestnet, proxy=wallet.proxy)
        controller = Controller(client=client, wallet=wallet)



        actions = await controller.build_actions()

        logger.info(f'{wallet} | Started Activity Tasks | Wallet will do {len(actions)} actions')

        for action in actions:

            sleep = random.randint(settings.random_pause_between_actions_min,
                                   settings.random_pause_between_actions_max)
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
               # logger.info(f"{wallet} | Start sleeping {sleep} secs for next action ")
                await asyncio.sleep(sleep)

        await update_next_action_time(
            private_key=wallet.private_key,
            seconds=random.randint(settings.random_pause_wallet_after_completion_min, settings.random_pause_wallet_after_completion_max)
        )
        
        await controller.update_db_by_user_info()

    except Exception as e:
 
        logger.error(f'Core | Activity | {wallet} |{e}')
        
    logger.info(f'{wallet} | finished activity tasks points [{wallet.points}]')

 
            
async def execute(wallets : Wallet, task_func, timeout_hours : int = 0):
    
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

        if timeout_hours == 0:
            break
        
        logger.info(f"Sleeping for {timeout_hours} hours before the next iteration")
        await asyncio.sleep(timeout_hours * 60 * 60)
        

async def activity(action: int):
    check_encrypt_param()
    if action == 1:
        await random_activity()

    all_wallets = db.all(Wallet)

    # Filter wallets if EXACT_WALLETS_TO_USE is defined
    if Settings().exact_wallets_to_run:
        wallets = [wallet for i, wallet in enumerate(all_wallets, start=1) if i in Settings().exact_wallets_to_run]
    else:
        wallets = all_wallets

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