import random
import traceback
from datetime import datetime

from loguru import logger

from data.settings import Settings
from libs.eth_async.data.models import TokenAmount, Networks
from libs.eth_async.utils.utils import randfloat
# from zksync_explorer.explorer_api import APIFunctions
from functions.controller import Controller
from data.models import Contracts
from utils.db_api.models import Wallet

async def select_random_action(controller: Controller, wallet: Wallet):
    settings = Settings()

    possible_actions = []
    weights = []


    wallet_balance = await controller.client.wallet.balance()

    if wallet_balance.Ether == 0:
        return lambda: controller.faucet_task(registration=True)

    if wallet_balance:

        faucet_status = await controller.pharos_portal.get_faucet_status()

        if faucet_status.get('data').get('is_able_to_faucet'):

            possible_actions += [
                lambda: controller.faucet_task(),
            ]
            weights += [
                10
            ]

        possible_actions += [
            lambda: controller.random_swap(),
        ]
        weights += [
            4
        ]

    if possible_actions:

        action = None
        while not action:
            action = random.choices(possible_actions, weights=weights)[0]

        else:
            return action

    return None
