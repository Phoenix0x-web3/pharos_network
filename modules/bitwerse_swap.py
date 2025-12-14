from __future__ import annotations

import asyncio
import random
import time
from dataclasses import dataclass
from typing import Optional, Sequence, Tuple, Union

from eth_abi.abi import encode
from loguru import logger
from web3 import Web3
from web3.exceptions import ContractLogicError
from web3.types import TxParams

from data.models import Contracts
from data.settings import Settings
from libs.eth_async.client import Client
from libs.eth_async.data.models import DefaultABIs, RawContract, TokenAmount
from libs.eth_async.utils.utils import randfloat
from modules.bitverse import Bitverse
from utils.db_api.models import Wallet
from utils.logs_decorator import controller_log

UNIVERSAL_ROUTER_ABI = [
    {
        "inputs": [
            {"internalType": "bytes", "name": "commands", "type": "bytes"},
            {"internalType": "bytes[]", "name": "inputs", "type": "bytes[]"},
            {"internalType": "uint256", "name": "deadline", "type": "uint256"},
        ],
        "name": "execute",
        "outputs": [],
        "stateMutability": "payable",
        "type": "function",
    }
]

PERMIT2_ABI = [
    {
        "type": "function",
        "name": "allowance",
        "inputs": [
            {"name": "", "type": "address", "internalType": "address"},
            {"name": "", "type": "address", "internalType": "address"},
            {"name": "", "type": "address", "internalType": "address"},
        ],
        "outputs": [
            {"name": "amount", "type": "uint160", "internalType": "uint160"},
            {"name": "expiration", "type": "uint48", "internalType": "uint48"},
            {"name": "nonce", "type": "uint48", "internalType": "uint48"},
        ],
        "stateMutability": "view",
    },
    {
        "type": "function",
        "name": "approve",
        "inputs": [
            {"name": "token", "type": "address", "internalType": "address"},
            {"name": "spender", "type": "address", "internalType": "address"},
            {"name": "amount", "type": "uint160", "internalType": "uint160"},
            {"name": "expiration", "type": "uint48", "internalType": "uint48"},
        ],
        "outputs": [],
        "stateMutability": "nonpayable",
    },
]

QUOTER_V4_ABI = [
    {
        "type": "function",
        "name": "quoteExactInputSingle",
        "inputs": [
            {
                "name": "params",
                "type": "tuple",
                "components": [
                    {
                        "name": "poolKey",
                        "type": "tuple",
                        "components": [
                            {"name": "currency0", "type": "address"},
                            {"name": "currency1", "type": "address"},
                            {"name": "fee", "type": "uint24"},
                            {"name": "tickSpacing", "type": "int24"},
                            {"name": "hooks", "type": "address"},
                        ],
                    },
                    {"name": "zeroForOne", "type": "bool"},
                    {"name": "exactAmount", "type": "uint128"},
                    {"name": "hookData", "type": "bytes"},
                ],
            }
        ],
        "outputs": [
            {"name": "amountOut", "type": "uint256"},
            {"name": "gasEstimate", "type": "uint256"},
        ],
        "stateMutability": "nonpayable",
    }
]


@dataclass(frozen=True)
class BitverseProtocolContracts:
    universal_router: str
    permit2: str
    quoter: str


BITVERSE_CONTRACTS_BY_CHAIN_ID: dict[int, BitverseProtocolContracts] = {
    688688: BitverseProtocolContracts(
        universal_router="0x2c1f987D55502C1Df4E90f22148601Fe8A2e9164",
        permit2="0xb7a1a5Dfdea624bEa289B6a0D9Ec51b9053C00b5",
        quoter="0xa4f01c05504f198114FF6C05aE749E0dA283C5D8",
    ),
    688689: BitverseProtocolContracts(
        universal_router="0x585FC3b498B1aBA1F0527663789361d3547aFc88",
        permit2="0xEfEAf7db2672b022B3DaB3d376f74B6a14BD53a2",
        quoter="0xd53175e1775330bb07B38bFD5B97F664F54208C3",
    ),
}


@dataclass(frozen=True)
class V4PoolCandidate:
    fee: int
    tick_spacing: int
    hooks: str = "0x0000000000000000000000000000000000000000"


def _to_uint48(v: int) -> int:
    if v < 0 or v > 2**48 - 1:
        raise ValueError("uint48 overflow")
    return v


def _to_uint160(v: int) -> int:
    if v < 0 or v > 2**160 - 1:
        raise ValueError("uint160 overflow")
    return v


def _to_uint128(v: int) -> int:
    if v < 0 or v > 2**128 - 1:
        raise ValueError("uint128 overflow")
    return v


def _to_uint24(v: int) -> int:
    if v < 0 or v > 0xFFFFFF:
        raise ValueError("uint24 overflow")
    return v


def _to_int24(v: int) -> int:
    if v < -(2**23) or v > 2**23 - 1:
        raise ValueError("int24 overflow")
    return v


def _as_wei(v: Union[int, TokenAmount]) -> int:
    return int(v.Wei) if isinstance(v, TokenAmount) else int(v)


class _V4Planner:
    def __init__(self) -> None:
        self._actions_hex = "0x"
        self._params: list[bytes] = []

    def add(self, action: int, encoded_input: bytes) -> None:
        self._params.append(encoded_input)
        self._actions_hex += int(action).to_bytes(1, "big").hex()

    def encode(self) -> bytes:
        actions_bytes = Web3.to_bytes(hexstr=self._actions_hex)
        return encode(["bytes", "bytes[]"], [actions_bytes, self._params])


class BitverseSpot(Bitverse):
    __module_name__ = "BitverseSpot"

    V4_SWAP_COMMAND = b"\x10"

    A_SWAP_EXACT_IN_SINGLE = 6
    A_SETTLE_ALL = 12
    A_TAKE_ALL = 15

    HOOK_DATA_DEFAULT = b"\x00"

    def __init__(self, client: Client, wallet: Wallet):
        self.client = client
        self.wallet = wallet
        self.chain_id = self.client.network.chain_id

        cfg = BITVERSE_CONTRACTS_BY_CHAIN_ID.get(self.chain_id)
        if not cfg:
            raise ValueError(f"Unknown Bitverse chain_id: {self.chain_id}")

        self.universal_router = RawContract(
            title="UniversalRouter",
            address=cfg.universal_router,
            abi=UNIVERSAL_ROUTER_ABI,
        )
        self.permit2 = RawContract(
            title="Permit2",
            address=cfg.permit2,
            abi=PERMIT2_ABI,
        )
        self.quoter = RawContract(
            title="QuoterV4",
            address=cfg.quoter,
            abi=QUOTER_V4_ABI,
        )

        self.contracts = Contracts()

    def _as_erc20(self, token: RawContract) -> RawContract:
        return RawContract(title=token.title or "ERC20", address=token.address, abi=DefaultABIs.Token)

    def _sorted_currencies(self, a: str, b: str) -> Tuple[str, str]:
        a = Web3.to_checksum_address(a)
        b = Web3.to_checksum_address(b)
        return (a, b) if int(a, 16) < int(b, 16) else (b, a)

    def _build_pool_key_tuple(self, token_a: str, token_b: str, *, cand: V4PoolCandidate) -> tuple:
        c0, c1 = self._sorted_currencies(token_a, token_b)
        return (
            c0,
            c1,
            _to_uint24(int(cand.fee)),
            _to_int24(int(cand.tick_spacing)),
            Web3.to_checksum_address(cand.hooks),
        )

    def _zero_for_one(self, *, token_in: str, pool_key_tuple: tuple) -> bool:
        token_in = Web3.to_checksum_address(token_in)
        currency0 = Web3.to_checksum_address(pool_key_tuple[0])
        return token_in == currency0

    async def _erc20_allowance(self, token: RawContract, owner: str, spender: str) -> int:
        token = self._as_erc20(token)
        t = await self.client.contracts.get(contract_address=token)
        return int(
            await t.functions.allowance(
                Web3.to_checksum_address(owner),
                Web3.to_checksum_address(spender),
            ).call()
        )

    async def _erc20_approve_max(self, token: RawContract, spender: str) -> str:
        token = self._as_erc20(token)
        t = await self.client.contracts.get(contract_address=token)
        data = t.encode_abi("approve", args=[Web3.to_checksum_address(spender), 2**256 - 1])

        tx_params = TxParams(
            to=Web3.to_checksum_address(token.address),
            data=data,
            value=0,
        )
        tx = await self.client.transactions.sign_and_send(tx_params=tx_params)
        receipt = await tx.wait_for_receipt(client=self.client, timeout=300)
        if not receipt:
            raise Exception("approve tx receipt is None")
        return tx.hash.hex() if hasattr(tx.hash, "hex") else str(tx.hash)

    async def _permit2_allowance(self, owner: str, token: str, spender: str) -> tuple[int, int, int]:
        p2 = await self.client.contracts.get(contract_address=self.permit2)
        amount, expiration, nonce = await p2.functions.allowance(
            Web3.to_checksum_address(owner),
            Web3.to_checksum_address(token),
            Web3.to_checksum_address(spender),
        ).call()
        return int(amount), int(expiration), int(nonce)

    async def _permit2_approve(self, token: str, spender: str, amount: int, expiration: int) -> str:
        p2 = await self.client.contracts.get(contract_address=self.permit2)
        data = p2.encode_abi(
            "approve",
            args=[
                Web3.to_checksum_address(token),
                Web3.to_checksum_address(spender),
                _to_uint160(int(amount)),
                _to_uint48(int(expiration)),
            ],
        )

        tx_params = TxParams(
            to=Web3.to_checksum_address(self.permit2.address),
            data=data,
            value=0,
        )
        tx = await self.client.transactions.sign_and_send(tx_params=tx_params)
        receipt = await tx.wait_for_receipt(client=self.client, timeout=300)
        if not receipt:
            raise Exception("permit2.approve tx receipt is None")
        return tx.hash.hex() if hasattr(tx.hash, "hex") else str(tx.hash)

    async def ensure_permit2_pipeline(
        self,
        token: RawContract,
        *,
        min_token_allowance_to_permit2: Union[int, TokenAmount] = 1,
        min_permit2_allowance_to_router: Union[int, TokenAmount] = 1,
        permit2_expiration: Optional[int] = None,
    ) -> None:
        owner = Web3.to_checksum_address(self.client.account.address)
        token_addr = Web3.to_checksum_address(token.address)
        permit2_addr = Web3.to_checksum_address(self.permit2.address)
        router_addr = Web3.to_checksum_address(self.universal_router.address)

        erc20_allow = await self._erc20_allowance(token, owner, permit2_addr)
        if erc20_allow < _as_wei(min_token_allowance_to_permit2):
            txh = await self._erc20_approve_max(token, permit2_addr)
            logger.debug(f"{self.wallet} | {self.__module_name__} | approve token->permit2: {txh}")
            await asyncio.sleep(2)

        p2_amount, p2_exp, _ = await self._permit2_allowance(owner, token_addr, router_addr)

        if permit2_expiration is None:
            permit2_expiration = int(time.time()) + 60 * 60 * 24 * 365 * 2

        need_p2 = _as_wei(min_permit2_allowance_to_router)

        if p2_amount < need_p2 or p2_exp < int(time.time()) + 60:
            txh = await self._permit2_approve(
                token=token_addr,
                spender=router_addr,
                amount=2**160 - 1,
                expiration=int(permit2_expiration),
            )
            logger.debug(f"{self.wallet} | {self.__module_name__} | permit2 approve->router: {txh}")
            await asyncio.sleep(2)

    async def _quote_exact_input_single_v4(
        self,
        *,
        token_in: RawContract,
        token_out: RawContract,
        amount_in: TokenAmount,
        cand: V4PoolCandidate,
    ) -> tuple[int, int, tuple, bool]:
        q = await self.client.contracts.get(contract_address=self.quoter)

        pool_key = self._build_pool_key_tuple(token_in.address, token_out.address, cand=cand)
        zero_for_one = self._zero_for_one(token_in=token_in.address, pool_key_tuple=pool_key)

        params = (
            pool_key,
            bool(zero_for_one),
            _to_uint128(int(amount_in.Wei)),
            self.HOOK_DATA_DEFAULT,
        )

        amount_out, gas_est = await q.functions.quoteExactInputSingle(params).call()
        return int(amount_out), int(gas_est), pool_key, bool(zero_for_one)

    async def discover_pool_and_quote(
        self,
        *,
        token_in: RawContract,
        token_out: RawContract,
        amount_in: TokenAmount,
        candidates: Sequence[V4PoolCandidate],
    ) -> tuple[V4PoolCandidate, tuple, bool, int, int]:
        last_err: Optional[Exception] = None

        for cand in candidates:
            try:
                out, gas, pool_key, zfo = await self._quote_exact_input_single_v4(
                    token_in=token_in,
                    token_out=token_out,
                    amount_in=amount_in,
                    cand=cand,
                )
                if out > 0:
                    return cand, pool_key, zfo, out, gas
            except ContractLogicError as e:
                last_err = e
                continue

        if last_err:
            raise last_err

        raise RuntimeError("Pool discovery failed")

    async def swap_execute(
        self,
        *,
        commands: bytes,
        inputs: list[bytes],
        deadline_sec: int = 300,
        value_wei: Union[int, TokenAmount] = 0,
    ) -> str:
        router = await self.client.contracts.get(contract_address=self.universal_router)

        data = router.encode_abi(
            "execute",
            args=[
                commands,
                inputs,
                int(time.time()) + int(deadline_sec),
            ],
        )

        tx_params = TxParams(
            to=Web3.to_checksum_address(self.universal_router.address),
            data=data,
            value=_as_wei(value_wei),
        )

        tx = await self.client.transactions.sign_and_send(tx_params=tx_params)
        receipt = await tx.wait_for_receipt(client=self.client, timeout=300)
        if not receipt:
            raise Exception("swap receipt is None")

        return tx.hash.hex() if hasattr(tx.hash, "hex") else str(tx.hash)

    async def swap_exact_in_v4_single(
        self,
        *,
        token_in: RawContract,
        token_out: RawContract,
        amount_in: TokenAmount,
        slippage_bps: int = 50,
        candidates: Sequence[V4PoolCandidate] = (
            V4PoolCandidate(fee=3000, tick_spacing=5),
            V4PoolCandidate(fee=500, tick_spacing=1),
            V4PoolCandidate(fee=3000, tick_spacing=10),
            V4PoolCandidate(fee=10000, tick_spacing=200),
        ),
        deadline_sec: int = 300,
    ) -> str:
        if slippage_bps < 0 or slippage_bps > 10_000:
            raise ValueError("slippage_bps must be in [0..10000]")

        await self.ensure_permit2_pipeline(
            token_in,
            min_token_allowance_to_permit2=amount_in,
            min_permit2_allowance_to_router=amount_in,
        )

        cand, pool_key, zero_for_one, quoted_out, gas = await self.discover_pool_and_quote(
            token_in=token_in,
            token_out=token_out,
            amount_in=amount_in,
            candidates=candidates,
        )

        amount_out_min = (int(quoted_out) * (10_000 - int(slippage_bps))) // 10_000

        planner = _V4Planner()

        swap_struct_type = "((address,address,uint24,int24,address),bool,uint128,uint128,bytes)"
        swap_struct_value = (
            pool_key,
            bool(zero_for_one),
            _to_uint128(int(amount_in.Wei)),
            _to_uint128(int(amount_out_min)),
            self.HOOK_DATA_DEFAULT,
        )

        planner.add(self.A_SWAP_EXACT_IN_SINGLE, encode([swap_struct_type], [swap_struct_value]))
        planner.add(self.A_SETTLE_ALL, encode(["address", "uint256"], [Web3.to_checksum_address(token_in.address), int(amount_in.Wei)]))
        planner.add(self.A_TAKE_ALL, encode(["address", "uint256"], [Web3.to_checksum_address(token_out.address), int(amount_out_min)]))

        logger.debug(
            f"{self.wallet} | {self.__module_name__} | v4 swap exact-in single | "
            f"{amount_in} {token_in.title} to {token_out.title}| "
            f"zfo={zero_for_one}"
        )

        return await self.swap_execute(
            commands=self.V4_SWAP_COMMAND,
            inputs=[planner.encode()],
            deadline_sec=int(deadline_sec),
            value_wei=0,
        )

    @controller_log("Bitverse Spot")
    async def swap_controller(self, from_token=None, to_token=None, amount=None):
        settings = Settings()
        percent_to_swap = randfloat(from_=settings.swap_percent_from, to_=settings.swap_percent_to, step=0.001) / 100

        tokens = [Contracts.USDT, Contracts.WETH]

        balance_map = await self.balance_map(tokens)
        if not balance_map:
            return f"{self.wallet} | {self.__module_name__} | No balances try to faucet first"

        if all(float(value) == 0 for value in balance_map.values()):
            return "Failed | No balance in all tokens, try to faucet first"

        if not from_token:
            from_token = random.choice(list(balance_map.keys()))

        tokens.remove(from_token)

        if not to_token:
            to_token = random.choice(tokens)

        amount = float((balance_map[from_token])) * percent_to_swap

        amount = TokenAmount(amount=amount, decimals=await self.client.transactions.get_decimals(contract=from_token.address))

        swap = await self.swap_exact_in_v4_single(
            token_in=from_token,
            token_out=to_token,
            amount_in=amount,
            slippage_bps=50,
            candidates=(V4PoolCandidate(fee=3000, tick_spacing=5),),
            deadline_sec=300,
        )

        if swap:
            return f"Success | Swapped {amount} {from_token.title} to {to_token.title} "

        raise Exception(f"Failed | to swap {amount} {from_token.title} to {to_token.title}")
