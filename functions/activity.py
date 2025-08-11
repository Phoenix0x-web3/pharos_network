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

_running_wallets: set[int] = set()
_pending_tasks: set[asyncio.Task] = set()
semaphore = asyncio.Semaphore(Settings().threads)

async def random_activity():
    #check_encrypt_param()
 
    delay = 10

    update_expired()
   
    while True:
        try:
            now = datetime.now()

            if Settings().exact_wallets_to_run:

                wallets: List[Wallet] = db.all(
                    Wallet
                )

                wallets = [w for i, w in enumerate(wallets, start=1) if i in Settings().exact_wallets_to_run]

            else:
                wallets: List[Wallet] = db.all(
                    Wallet,
                    Wallet.next_activity_action_time <= now,
                    order_by=Wallet.next_activity_action_time.asc()
                )
            if not wallets:
                continue

            logger.info(f'Currently Running Wallets: {_running_wallets}')

            settings = Settings()

            async def sem_task(wallet: Wallet, timeout: float | int = 1200):

                async with semaphore:
                    try:
                        async with asyncio.timeout(timeout):
                            await random_activity_task(wallet=wallet)

                    except asyncio.CancelledError:

                        raise

                    except asyncio.TimeoutError:
                        logger.error(f"{wallet} | wallet-loop timeout after {timeout}s -> drop task")

                        await update_next_action_time(
                            private_key=wallet.private_key,
                            seconds=random.randint(settings.random_pause_wallet_after_completion_min, settings.random_pause_wallet_after_completion_max)
                        )

                    except Exception:
                        await update_next_action_time(
                            private_key=wallet.private_key,
                            seconds=random.randint(1200, 1600)
                        )

                    finally:
                        _running_wallets.discard(wallet.id)

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

        if isinstance(actions, str):
            logger.warning(actions)

        else:
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

    except asyncio.CancelledError:
        raise

    except Exception as e:
        logger.error(f'Core | Activity | {wallet} |{e}')
        raise e



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
                
