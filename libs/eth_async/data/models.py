import json
from dataclasses import dataclass
from decimal import Decimal

import requests
from eth_typing import ChecksumAddress
from web3 import Web3

from libs.eth_async import exceptions
from libs.eth_async.blockscan_api import APIFunctions
from libs.eth_async.classes import AutoRepr
from libs.eth_async.data import config


class TokenAmount:
    Wei: int
    Ether: Decimal
    decimals: int

    def __init__(self, amount: int | float | str | Decimal, decimals: int = 18, wei: bool = False, gwei: bool = False) -> None:
        if wei:
            self.Wei: int = int(amount)
            self.Ether: Decimal = Decimal(str(amount)) / 10**decimals
            self.Gwei: Decimal = self.Wei / Decimal(10**9)
        elif gwei:
            self.Gwei: Decimal = Decimal(str(amount))
            self.Wei: int = int(self.Gwei * 10**9)
            self.Ether: Decimal = Decimal(self.Wei) / 10**decimals
        else:
            self.Ether: Decimal = Decimal(str(amount))
            self.Wei: int = int(self.Ether * 10**decimals)
            self.Gwei: Decimal = self.Wei / Decimal(10**9)

        self.decimals = decimals

    def __str__(self):
        return f"{float(self.Ether):.5f}"

    def __repr__(self):
        return str(self)


@dataclass
class DefaultABIs:
    Token = [
        {
            "constant": True,
            "inputs": [],
            "name": "name",
            "outputs": [{"name": "", "type": "string"}],
            "payable": False,
            "stateMutability": "view",
            "type": "function",
        },
        {
            "constant": True,
            "inputs": [],
            "name": "symbol",
            "outputs": [{"name": "", "type": "string"}],
            "payable": False,
            "stateMutability": "view",
            "type": "function",
        },
        {
            "constant": True,
            "inputs": [],
            "name": "totalSupply",
            "outputs": [{"name": "", "type": "uint256"}],
            "payable": False,
            "stateMutability": "view",
            "type": "function",
        },
        {
            "constant": True,
            "inputs": [],
            "name": "decimals",
            "outputs": [{"name": "", "type": "uint256"}],
            "payable": False,
            "stateMutability": "view",
            "type": "function",
        },
        {
            "constant": True,
            "inputs": [{"name": "account", "type": "address"}],
            "name": "balanceOf",
            "outputs": [{"name": "", "type": "uint256"}],
            "payable": False,
            "stateMutability": "view",
            "type": "function",
        },
        {
            "constant": True,
            "inputs": [{"name": "owner", "type": "address"}, {"name": "spender", "type": "address"}],
            "name": "allowance",
            "outputs": [{"name": "remaining", "type": "uint256"}],
            "payable": False,
            "stateMutability": "view",
            "type": "function",
        },
        {
            "constant": False,
            "inputs": [{"name": "spender", "type": "address"}, {"name": "value", "type": "uint256"}],
            "name": "approve",
            "outputs": [],
            "payable": False,
            "stateMutability": "nonpayable",
            "type": "function",
        },
        {
            "constant": False,
            "inputs": [{"name": "to", "type": "address"}, {"name": "value", "type": "uint256"}],
            "name": "transfer",
            "outputs": [],
            "payable": False,
            "stateMutability": "nonpayable",
            "type": "function",
        },
    ]


@dataclass
class API:
    """
    An instance that contains an API related information.

    Attributes:
        key (str): an API-key.
        url (str): an API entrypoint URL.
        docs (str): a docs URL.
        functions (Optional[APIFunctions]): the functions instance.

    """

    key: str
    url: str
    docs: str | None = None
    functions: APIFunctions | None = None


class Network:
    def __init__(
        self,
        name: str,
        rpc: str,
        decimals: int | None = None,
        chain_id: int | None = None,
        tx_type: int = 0,
        coin_symbol: str | None = None,
        explorer: str | None = None,
        api: API | None = None,
    ) -> None:
        self.name: str = name.lower()
        self.rpc: str = rpc
        self.chain_id: int | None = chain_id
        self.tx_type: int = tx_type
        self.coin_symbol: str | None = coin_symbol
        self.explorer: str | None = explorer
        self.decimals = decimals
        self.api = api
        # todo: добавить поле decimals

        if not self.chain_id:
            try:
                self.chain_id = Web3(Web3.HTTPProvider(self.rpc)).eth.chain_id
            except Exception as err:
                raise exceptions.WrongChainID(f"Can not get chain id: {err}")

        if not self.coin_symbol or not self.decimals:
            try:
                network = None
                networks_info_response = requests.get("https://chainid.network/chains.json").json()
                for network_ in networks_info_response:
                    if network_["chainId"] == self.chain_id:
                        network = network_
                        break

                if not self.coin_symbol:
                    self.coin_symbol = network["nativeCurrency"]["symbol"]
                if not self.decimals:
                    self.decimals = int(network["nativeCurrency"]["decimals"])

            except Exception as err:
                raise exceptions.WrongCoinSymbol(f"Can not get coin symbol: {err}")

        if self.coin_symbol:
            self.coin_symbol = self.coin_symbol.upper()

        self.set_api_functions()

    def set_api_functions(self) -> None:
        """
        Update API functions after API key change.
        """
        if self.api and self.api.key and self.api.url:
            self.api.functions = APIFunctions(self.api.key, self.api.url)

    def __repr__(self):
        return f"{self.name.capitalize()}"


from data.rpc import RPC_MAP


class Networks:
    # Mainnets
    Ethereum = Network(
        name="ethereum",
        rpc=RPC_MAP["ethereum"],
        chain_id=1,
        tx_type=2,
        coin_symbol="ETH",
        decimals=18,
        explorer="https://etherscan.io/",
        api=API(key=config.ETHEREUM_API_KEY, url="https://api.etherscan.io/api", docs="https://docs.etherscan.io/"),
    )

    Arbitrum = Network(
        name="arbitrum",
        rpc=RPC_MAP["arbitrum"],
        chain_id=42161,
        tx_type=2,
        coin_symbol="ETH",
        decimals=18,
        explorer="https://arbiscan.io/",
        api=API(key=config.ARBITRUM_API_KEY, url="https://api.arbiscan.io/api", docs="https://docs.arbiscan.io/"),
    )

    Base = Network(
        name="base",
        rpc=RPC_MAP["base"],
        chain_id=8453,
        tx_type=2,
        coin_symbol="ETH",
        explorer="https://base.blockscout.com/",
        api=API(key=config.BASE_API_KEY, url="https://api.basescan.org/api", docs="https://docs.basescan.org/"),
    )

    Optimism = Network(
        name="optimism",
        rpc=RPC_MAP["optimism"],
        chain_id=10,
        tx_type=2,
        coin_symbol="ETH",
        decimals=18,
        explorer="https://optimism.blockscout.com/",
        api=API(key=config.OPTIMISM_API_KEY, url="https://api-optimistic.etherscan.io/api", docs="https://docs.optimism.etherscan.io/"),
    )

    Ink = Network(
        name="ink",
        rpc=RPC_MAP["ink"],
        chain_id=57073,
        tx_type=2,
        coin_symbol="ETH",
        decimals=18,
        explorer="https://explorer.inkonchain.com/",
        # api=API(
        #     key=config.OPTIMISM_API_KEY, url='https://api-optimistic.etherscan.io/api',
        #     docs='https://docs.optimism.etherscan.io/'
        # ),
    )

    Mode = Network(
        name="mode",
        rpc=RPC_MAP["mode"],
        chain_id=34443,
        tx_type=2,
        coin_symbol="ETH",
        decimals=18,
        explorer="https://explorer.mode.network/",
        # api=API(
        #     key=config.OPTIMISM_API_KEY, url='https://api-optimistic.etherscan.io/api',
        #     docs='https://docs.optimism.etherscan.io/'
        # ),
    )

    BSC = Network(
        name="BSC",
        rpc=RPC_MAP["bsc"],
        chain_id=56,
        tx_type=2,
        coin_symbol="BNB",
        decimals=18,
        explorer="https://bscscan.com/",
        api=API(key=config.BSC_API_KEY, url="https://api.bscscan.com/api", docs="https://docs.bscscan.com/"),
    )

    opBNB = Network(
        name="op_bnb",
        rpc=RPC_MAP["op_bnb"],
        chain_id=204,
        tx_type=2,
        coin_symbol="BNB",
        decimals=18,
        explorer="https://opbnbscan.com/",
        api=API(key=config.BSC_API_KEY, url="https://api.bscscan.com/api", docs="https://docs.bscscan.com/"),
    )

    Polygon = Network(
        name="polygon",
        rpc=RPC_MAP["polygon"],
        chain_id=137,
        tx_type=2,
        coin_symbol="MATIC",
        decimals=18,
        explorer="https://polygonscan.com/",
        api=API(key=config.POLYGON_API_KEY, url="https://api.polygonscan.com/api", docs="https://docs.polygonscan.com/"),
    )

    Soneium = Network(
        name="Soneium",
        rpc=RPC_MAP["soneium"],
        chain_id=1868,
        tx_type=0,
        coin_symbol="ETH",
        decimals=18,
        explorer="https://soneium.blockscout.com/",
        api=API(
            key="UNICHAIN_SEPOLIA_API_KEY", url="https://soneium.blockscout.com/api/v2", docs="https://docs.blockscout.com/devs/apis/rpc"
        ),
    )

    LISK = Network(
        name="LISK",
        rpc=RPC_MAP["lisk"],
        chain_id=1135,
        tx_type=2,
        coin_symbol="ETH",
        decimals=18,
        explorer="https://blockscout.lisk.com/",
        # api=API(key=config.HECO_API_KEY, url='https://api.hecoinfo.com/api', docs='https://hecoinfo.com/apis')
    )

    Unichain = Network(
        name="unichain",
        rpc=RPC_MAP["unichain"],
        chain_id=130,
        tx_type=2,
        coin_symbol="ETH",
        decimals=18,
        explorer="https://unichain.blockscout.com/",
        # api=API(key=config.HECO_API_KEY, url='https://api.hecoinfo.com/api', docs='https://hecoinfo.com/apis')
    )

    Avalanche = Network(
        name="avalanche",
        rpc="https://rpc.ankr.com/avalanche/",
        chain_id=43114,
        tx_type=2,
        coin_symbol="AVAX",
        decimals=18,
        explorer="https://snowtrace.io/",
        api=API(key=config.AVALANCHE_API_KEY, url="https://api.snowtrace.io/api", docs="https://docs.snowtrace.io/"),
    )

    ArbitrumNova = Network(
        name="arbitrum_nova",
        rpc="https://nova.arbitrum.io/rpc/",
        chain_id=42170,
        tx_type=2,
        coin_symbol="ETH",
        decimals=18,
        explorer="https://nova.arbiscan.io/",
        api=API(key=config.ARBITRUM_API_KEY, url="https://api-nova.arbiscan.io/api", docs="https://nova.arbiscan.io/apis/"),
    )

    Moonbeam = Network(
        name="moonbeam",
        rpc="https://rpc.api.moonbeam.network/",
        chain_id=1284,
        tx_type=2,
        coin_symbol="GLMR",
        decimals=18,
        explorer="https://moonscan.io/",
        api=API(key=config.MOONBEAM_API_KEY, url="https://api-moonbeam.moonscan.io/api", docs="https://moonscan.io/apis/"),
    )

    Fantom = Network(
        name="fantom",
        rpc="https://fantom.publicnode.com",
        chain_id=250,
        tx_type=0,
        coin_symbol="FTM",
        decimals=18,
        explorer="https://ftmscan.com/",
        api=API(key=config.FANTOM_API_KEY, url="https://api.ftmscan.com/api", docs="https://docs.ftmscan.com/"),
    )

    Celo = Network(
        name="celo",
        rpc="https://1rpc.io/celo",
        chain_id=42220,
        tx_type=0,
        coin_symbol="CELO",
        decimals=18,
        explorer="https://celoscan.io/",
        api=API(key=config.CELO_API_KEY, url="https://api.celoscan.io/api", docs="https://celoscan.io/apis/"),
    )

    ZkSync = Network(
        name="zksync",
        rpc="https://mainnet.era.zksync.io",
        # rpc='https://rpc.ankr.com/zksync_era',
        chain_id=324,
        tx_type=2,
        coin_symbol="ETH",
        decimals=18,
        explorer="https://explorer.zksync.io/",
    )

    Gnosis = Network(
        name="gnosis",
        rpc="https://rpc.ankr.com/gnosis",
        chain_id=100,
        tx_type=2,
        coin_symbol="xDAI",
        decimals=18,
        explorer="https://gnosisscan.io/",
        api=API(key=config.GNOSIS_API_KEY, url="https://api.gnosisscan.io/api", docs="https://docs.gnosisscan.io/"),
    )

    HECO = Network(
        name="heco",
        rpc="https://http-mainnet.hecochain.com",
        chain_id=128,
        tx_type=2,
        coin_symbol="HECO",
        decimals=18,
        explorer="https://www.hecoinfo.com/en-us/",
        api=API(key=config.HECO_API_KEY, url="https://api.hecoinfo.com/api", docs="https://hecoinfo.com/apis"),
    )

    KAIA = Network(
        name="KAIA",
        rpc="https://public-en.node.kaia.io",
        chain_id=8217,
        tx_type=2,
        coin_symbol="KAIA",
        decimals=18,
        explorer="https://kaiascan.io",
        # api=API(key=config.HECO_API_KEY, url='https://api.hecoinfo.com/api', docs='https://hecoinfo.com/apis')
    )

    Sepolia = Network(
        name="sepolia",
        rpc="https://rpc.sepolia.org",
        chain_id=11155111,
        tx_type=2,
        coin_symbol="ETH",
        decimals=18,
        explorer="https://sepolia.etherscan.io",
        api=API(
            key=config.SEPOLIA_API_KEY, url="https://api-sepolia.etherscan.io/api", docs="https://docs.etherscan.io/v/sepolia-etherscan/"
        ),
    )

    PharosTestnet = Network(
        name="pharos testnet", rpc=RPC_MAP["pharos"], chain_id=688688, tx_type=2, coin_symbol="PHRS", decimals=18, explorer="", api=None
    )

    MonadTestnet = Network(
        name="Monad",
        rpc=RPC_MAP["monad"],
        chain_id=10143,
        tx_type=0,
        coin_symbol="MON",
        decimals=18,
        explorer="https://sepolia.etherscan.io",
    )


class RawContract(AutoRepr):
    """
    An instance of a raw contract.

    Attributes:
        title str: a contract title.
        address (ChecksumAddress): a contract address.
        abis list[dict[str, Any]] | str: an ABI of the contract.

    """

    title: str
    address: ChecksumAddress
    abi: list[dict[str, ...]]

    def __init__(self, address: str, abi: list[dict[str, ...]] | str | None = None, title: str = "") -> None:
        """
        Initialize the class.

        Args:
            title (str): a contract title.
            address (str): a contract address.
            abi (Union[List[Dict[str, Any]], str]): an ABI of the contract.

        """
        self.title = title
        self.address = Web3.to_checksum_address(address)
        self.abi = json.loads(abi) if isinstance(abi, str) else abi

    def __eq__(self, other) -> bool:
        if self.address == other.address and self.abi == other.abi:
            return True
        return False

    def __hash__(self):
        return hash((self.address, self.title))

    def __repr__(self):
        return f"<RawContract title='{self.title}' address='{self.address}'>"


@dataclass
class CommonValues:
    """
    An instance with common values used in transactions.
    """

    Null: str = "0x0000000000000000000000000000000000000000000000000000000000000000"
    InfinityStr: str = "0xffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"
    InfinityInt: int = int("0xffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff", 16)


class TxArgs(AutoRepr):
    """
    An instance for named transaction arguments.
    """

    def __init__(self, **kwargs) -> None:
        """
        Initialize the class.

        Args:
            **kwargs: named arguments of a contract transaction.

        """
        self.__dict__.update(kwargs)

    def list(self) -> list[...]:
        """
        Get list of transaction arguments.

        Returns:
            List[Any]: list of transaction arguments.

        """
        return list(self.__dict__.values())

    def tuple(self) -> tuple[str, ...]:
        """
        Get tuple of transaction arguments.

        Returns:
            Tuple[Any]: tuple of transaction arguments.

        """
        return tuple(self.__dict__.values())
