from data.config import ABIS_DIR
from libs.eth_async.classes import Singleton
from libs.eth_async.data.models import DefaultABIs, RawContract
from libs.eth_async.utils.files import read_json


class Contracts(Singleton):
    PHRS = RawContract(title="PHRS", address="0x0000000000000000000000000000000000000000", abi=DefaultABIs.Token)

    USDT = RawContract(title="USDT", address="0xe7e84b8b4f39c507499c40b4ac199b050e2882d5", abi=DefaultABIs.Token)

    USDC = RawContract(title="USDC", address="0xe0be08c77f415f577a1b3a9ad7a1df1479564ec8", abi=DefaultABIs.Token)

    WBTC = RawContract(title="WBTC", address="0x0c64f03eea5c30946d5c55b4b532d08ad74638a4", abi=DefaultABIs.Token)

    WPHRS = RawContract(title="WPHRS", address="0x838800b758277cc111b2d48ab01e5e164f8e9471", abi=read_json(path=(ABIS_DIR, "weth.json")))
