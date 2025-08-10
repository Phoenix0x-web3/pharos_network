import asyncio
import json
import os
import random
import string

from loguru import logger
from requests import session
from web3 import Web3
from web3.types import TxParams
from hexbytes import HexBytes

from data.config import ABIS_DIR
from libs.base import Base
from libs.baseAsyncSession import BaseAsyncSession
from libs.eth_async.client import Client
from libs.eth_async.data.models import RawContract, TokenAmount, TxArgs
from libs.eth_async.utils.files import read_json
from utils.db_api.models import Wallet
from utils.logs_decorator import action_log, controller_log

PNS_CONTROLLER = RawContract(
    title="PNS_Controller",
    address="0x51be1ef20a1fd5179419738fc71d95a8b6f8a175",
    abi=read_json((ABIS_DIR, "pns_controller.json")),
)


RESOLVER = RawContract(
    title="Resolver",
    address="0x9a43dcA1C3BB268546b98eb2AB1401bFc5b58505",
    abi=read_json((ABIS_DIR, "pns_controller.json")),
)

DURATION = 31_536_000


class PNS(Base):
    __module_name__ = "Pharos Name Service"

    def __init__(self, client: Client, wallet: Wallet):
        self.client = client
        self.wallet = wallet
        self.session = BaseAsyncSession(proxy=self.wallet.proxy)


    @staticmethod
    async def _rand_domain(length: int = 9) -> str:
        from faker import Faker
        prefix = random.randint(3, 5)
        name = Faker().user_name()

        symbols = ['-', '_', '|']

        new_nickname = name + random.choice(symbols) + Faker().word()[:prefix]

        return new_nickname

    @controller_log("Domain Mint")
    async def mint(self) -> str:
        contract = await self.client.contracts.get(contract_address=PNS_CONTROLLER)
        name = await self._rand_domain()
        owner = self.client.account.address
        secret = HexBytes(os.urandom(32))

        price = await contract.functions.rentPrice(name, DURATION).call()
        value = int(price[0]) + int(price[1])
        amount = TokenAmount(amount=value, wei=True)

        balance = await self.client.wallet.balance()

        if float(balance.Ether) < float(amount.Ether):
            return f'Failed | Not enough balance {balance.Ether} PNS for mint PNS domain - {amount.Ether}'

        # 1) makeCommitment (view)
        commitment = await contract.functions.makeCommitment(
            name,
            owner,
            DURATION,
            secret,
            RESOLVER.address,
            [],
            True,
            0
        ).call()


        commit_data = contract.encode_abi("commit", args=[commitment])
        tx_commit = TxParams(
            to=contract.address,
            data=commit_data,
            value=0
        )

        tx1 = await self.client.transactions.sign_and_send(tx_params=tx_commit)
        await asyncio.sleep(random.randint(2, 4))
        rcpt1 = await tx1.wait_for_receipt(client=self.client, timeout=300)

        if not rcpt1:
            return f"Failed | commit | {name}.phrs"

        delay = random.randint(60, 90)

        logger.debug(f'{self.wallet} | {self.__module_name__} | Awaiting {delay} secs for commintment applying ')
        await asyncio.sleep(delay)

        price = await contract.functions.rentPrice(name, DURATION).call()
        value = int(price[0]) + int(price[1])
        amount = TokenAmount(amount=value, wei=True)

        reg_data = contract.encode_abi(
            "register",
            args=[name, owner, DURATION, secret, RESOLVER.address, [], True, 0]
        )

        tx_register = TxParams(
            to=contract.address,
            data=reg_data,
            value=amount.Wei
        )
        tx2 = await self.client.transactions.sign_and_send(tx_params=tx_register)
        await asyncio.sleep(random.randint(2, 4))
        rcpt2 = await tx2.wait_for_receipt(client=self.client, timeout=300)

        if rcpt2:
            logger.success(f'{self.wallet} | {self.__module_name__} | Domain Minted | Awaiting {delay} secs for set PNS ')
            await asyncio.sleep(delay)
            return await self.set_address()

        return f"Failed | register | {name}.phrs"

    async def check_pns_domain(self):
        headers = {
            'content-type': 'application/json',
            'origin': 'https://test.pharosname.com',
            'referer': 'https://test.pharosname.com/',
        }
        payload = {
            'query': 'query getNamesForAddress($orderBy: Domain_orderBy, $orderDirection: OrderDirection, $first: Int, $whereFilter: Domain_filter) {\n  domains(\n    orderBy: $orderBy\n    orderDirection: $orderDirection\n    first: $first\n    where: $whereFilter\n  ) {\n    ...DomainDetails\n    registration {\n      ...RegistrationDetails\n    }\n    wrappedDomain {\n      ...WrappedDomainDetails\n    }\n  }\n}\n\nfragment DomainDetails on Domain {\n  ...DomainDetailsWithoutParent\n  parent {\n    name\n    id\n  }\n}\n\nfragment DomainDetailsWithoutParent on Domain {\n  id\n  labelName\n  labelhash\n  name\n  isMigrated\n  createdAt\n  resolvedAddress {\n    id\n  }\n  owner {\n    id\n  }\n  registrant {\n    id\n  }\n  wrappedOwner {\n    id\n  }\n}\n\nfragment RegistrationDetails on Registration {\n  registrationDate\n  expiryDate\n}\n\nfragment WrappedDomainDetails on WrappedDomain {\n  expiryDate\n  fuses\n}',
            'variables': {
                'orderBy': 'createdAt',
                'orderDirection': 'asc',
                'first': 20,
                'whereFilter': {
                    'and': [
                        {
                            'or': [
                                {
                                    'owner': self.client.account.address.lower(),
                                },
                                {
                                    'registrant': self.client.account.address.lower(),
                                },
                                {
                                    'wrappedOwner': self.client.account.address.lower(),
                                },
                            ],
                        },
                        {
                            'or': [
                                {
                                    'owner_not': '0x0000000000000000000000000000000000000000',
                                },
                                {
                                    'resolver_not': None,
                                },
                                {
                                    'and': [
                                        {
                                            'registrant_not': '0x0000000000000000000000000000000000000000',
                                        },
                                        {
                                            'registrant_not': None,
                                        },
                                    ],
                                },
                            ],
                            },
                            ],
                        },
                    },
                    'operationName': 'getNamesForAddress',
                }

        r = await self.session.post(
            url='https://graphql.pharosname.com/',
            json=payload,
            headers=headers
        )

        r.raise_for_status()
        return r.json().get('data').get('domains')

    async def set_address(self):

        contract = await self.client.contracts.get(contract_address=RESOLVER)

        req = await self.check_pns_domain()

        node = req[0].get('id')
        name = req[0].get('labelName')

        data = TxArgs(
            node = Web3.to_bytes(hexstr=node),
            coin_type = int("0x800a8230", 16),
            a = Web3.to_bytes(hexstr=self.client.account.address)
        ).tuple()

        data = contract.encode_abi("setAddr", args=data)

        tx_register = TxParams(
            to=contract.address,
            data=data,
            value=0
        )

        tx2 = await self.client.transactions.sign_and_send(tx_params=tx_register)
        await asyncio.sleep(random.randint(2, 4))
        reciept = await tx2.wait_for_receipt(client=self.client, timeout=300)

        if reciept:
            return f"Success | Registered and set {name}.phrs domain as primary"

        return f"Failed | Set {name}.phrs domain"
