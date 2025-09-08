from data.config import ABIS_DIR
from libs.eth_async.classes import Singleton
from libs.eth_async.data.models import RawContract, DefaultABIs
from libs.eth_async.utils.files import read_json


class Contracts(Singleton):

    PHRS = RawContract(
        title='PHRS',
        address='0x0000000000000000000000000000000000000000',
        abi=DefaultABIs.Token
    )

    USDT = RawContract(
        title='USDT',
        address='0xd4071393f8716661958f766df660033b3d35fd29',
        abi=DefaultABIs.Token
    )

    USDC = RawContract(
        title='USDC',
        address='0x72df0bcd7276f2dfbac900d1ce63c272c4bccced',
        abi=DefaultABIs.Token
    )

    WBTC = RawContract(
        title='WBTC',
        address='0x8275c526d1bcec59a31d673929d3ce8d108ff5c7',
        abi=DefaultABIs.Token
    )

    WPHRS = RawContract(
        title='WPHRS',
        address='0x76aaada469d23216be5f7c596fa25f282ff9b364',
        abi=read_json(path=(ABIS_DIR, 'WETH.json'))
    )