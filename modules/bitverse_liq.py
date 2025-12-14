from __future__ import annotations

import asyncio
import math
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Optional, Sequence, Tuple

from eth_abi.abi import encode
from loguru import logger
from web3 import Web3
from web3.exceptions import ContractLogicError
from web3.types import TxParams

from data.models import Contracts
from data.settings import Settings
from libs.baseAsyncSession import BaseAsyncSession
from libs.eth_async.client import Client
from libs.eth_async.data.models import DefaultABIs, RawContract, TokenAmount
from libs.eth_async.utils.utils import randfloat
from modules.bitwerse_swap import BitverseSpot, V4PoolCandidate
from utils.db_api.models import Wallet
from utils.logs_decorator import controller_log
from utils.retry import async_retry

POSITION_MANAGER_ABI = [
    {
        "type": "function",
        "name": "modifyLiquidities",
        "inputs": [
            {"name": "unlockData", "type": "bytes", "internalType": "bytes"},
            {"name": "deadline", "type": "uint256", "internalType": "uint256"},
        ],
        "outputs": [],
        "stateMutability": "payable",
    },
    {
        "type": "function",
        "name": "multicall",
        "inputs": [
            {"name": "data", "type": "bytes[]", "internalType": "bytes[]"},
        ],
        "outputs": [
            {"name": "results", "type": "bytes[]", "internalType": "bytes[]"},
        ],
        "stateMutability": "payable",
    },
    {
        "type": "function",
        "name": "permitBatch",
        "inputs": [
            {"name": "owner", "type": "address", "internalType": "address"},
            {
                "name": "permitBatch",
                "type": "tuple",
                "internalType": "struct IAllowanceTransfer.PermitBatch",
                "components": [
                    {
                        "name": "details",
                        "type": "tuple[]",
                        "internalType": "struct IAllowanceTransfer.PermitDetails[]",
                        "components": [
                            {"name": "token", "type": "address", "internalType": "address"},
                            {"name": "amount", "type": "uint160", "internalType": "uint160"},
                            {"name": "expiration", "type": "uint48", "internalType": "uint48"},
                            {"name": "nonce", "type": "uint48", "internalType": "uint48"},
                        ],
                    },
                    {"name": "spender", "type": "address", "internalType": "address"},
                    {"name": "sigDeadline", "type": "uint256", "internalType": "uint256"},
                ],
            },
            {"name": "signature", "type": "bytes", "internalType": "bytes"},
        ],
        "outputs": [],
        "stateMutability": "payable",
    },
]

STATE_VIEW_ABI = [
    {
        "type": "function",
        "name": "getSlot0",
        "inputs": [{"name": "poolId", "type": "bytes32", "internalType": "bytes32"}],
        "outputs": [
            {"name": "sqrtPriceX96", "type": "uint160", "internalType": "uint160"},
            {"name": "tick", "type": "int24", "internalType": "int24"},
            {"name": "protocolFee", "type": "uint24", "internalType": "uint24"},
            {"name": "lpFee", "type": "uint24", "internalType": "uint24"},
        ],
        "stateMutability": "view",
    }
]


@dataclass(frozen=True)
class BitverseLiquidityProtocolContracts:
    position_manager: str
    state_view: str


BITVERSE_LIQUIDITY_CONTRACTS_BY_CHAIN_ID: dict[int, BitverseLiquidityProtocolContracts] = {
    688689: BitverseLiquidityProtocolContracts(
        position_manager="0x4638A8E4d6Df3376c1c6761AdEf2a49525ffaA89",
        state_view="0xb86dE4a21766Ec8B951BCD28fefb04F93cF9571A",
    )
}


@dataclass(frozen=True)
class SpotLiquidityPoolAsset:
    address: str
    symbol: str
    decimals: int

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "SpotLiquidityPoolAsset":
        return SpotLiquidityPoolAsset(
            address=Web3.to_checksum_address(d["address"]),
            symbol=str(d.get("symbol") or ""),
            decimals=int(d.get("decimals") or 18),
        )


@dataclass(frozen=True)
class SpotLiquidityPool:
    pool_id: str
    pool_symbol: str
    fee: int
    tick_spacing: int
    token0: SpotLiquidityPoolAsset
    token1: SpotLiquidityPoolAsset

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "SpotLiquidityPool":
        assets = d.get("assetList") or []
        if len(assets) != 2:
            raise ValueError("pool.assetList must have 2 items")

        a0 = SpotLiquidityPoolAsset.from_dict(assets[0])
        a1 = SpotLiquidityPoolAsset.from_dict(assets[1])

        return SpotLiquidityPool(
            pool_id=str(d.get("poolId")),
            pool_symbol=str(d.get("poolSymbol") or ""),
            fee=int(d.get("fee") or 0),
            tick_spacing=int(d.get("tickSpacing") or 0),
            token0=a0,
            token1=a1,
        )


@dataclass(frozen=True)
class LiquidityMintResult:
    tx_hash: str
    token_id: Optional[int] = None


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


def _as_wei(v: int | TokenAmount) -> int:
    return int(v.Wei) if isinstance(v, TokenAmount) else int(v)


def _js_round(x: float) -> int:
    if x >= 0:
        return int(math.floor(x + 0.5))
    return int(math.ceil(x - 0.5))


MIN_TICK = -887272
MAX_TICK = 887272
Q96 = 2**96


def nearest_usable_tick(tick: int, tick_spacing: int) -> int:
    if tick_spacing <= 0:
        raise ValueError("tick_spacing must be > 0")

    rounded = _js_round(tick / tick_spacing) * tick_spacing

    if rounded < MIN_TICK:
        rounded += tick_spacing
    if rounded > MAX_TICK:
        rounded -= tick_spacing

    return int(rounded)


def get_sqrt_ratio_at_tick(tick: int) -> int:
    if tick < MIN_TICK or tick > MAX_TICK:
        raise ValueError("tick out of range")

    abs_tick = -tick if tick < 0 else tick

    ratio = 0x100000000000000000000000000000000
    if abs_tick & 0x1:
        ratio = (ratio * 0xFFFCB933BD6FAD37AA2D162D1A594001) >> 128
    if abs_tick & 0x2:
        ratio = (ratio * 0xFFF97272373D413259A46990580E213A) >> 128
    if abs_tick & 0x4:
        ratio = (ratio * 0xFFF2E50F5F656932EF12357CF3C7FDCC) >> 128
    if abs_tick & 0x8:
        ratio = (ratio * 0xFFE5CACA7E10E4E61C3624EAA0941CD0) >> 128
    if abs_tick & 0x10:
        ratio = (ratio * 0xFFCB9843D60F6159C9DB58835C926644) >> 128
    if abs_tick & 0x20:
        ratio = (ratio * 0xFF973B41FA98C081472E6896DFB254C0) >> 128
    if abs_tick & 0x40:
        ratio = (ratio * 0xFF2EA16466C96A3843EC78B326B52861) >> 128
    if abs_tick & 0x80:
        ratio = (ratio * 0xFE5DEE046A99A2A811C461F1969C3053) >> 128
    if abs_tick & 0x100:
        ratio = (ratio * 0xFCBE86C7900A88AEDCFFC83B479AA3A4) >> 128
    if abs_tick & 0x200:
        ratio = (ratio * 0xF987A7253AC413176F2B074CF7815E54) >> 128
    if abs_tick & 0x400:
        ratio = (ratio * 0xF3392B0822B70005940C7A398E4B70F3) >> 128
    if abs_tick & 0x800:
        ratio = (ratio * 0xE7159475A2C29B7443B29C7FA6E889D9) >> 128
    if abs_tick & 0x1000:
        ratio = (ratio * 0xD097F3BDFD2022B8845AD8F792AA5825) >> 128
    if abs_tick & 0x2000:
        ratio = (ratio * 0xA9F746462D870FDF8A65DC1F90E061E5) >> 128
    if abs_tick & 0x4000:
        ratio = (ratio * 0x70D869A156D2A1B890BB3DF62BAF32F7) >> 128
    if abs_tick & 0x8000:
        ratio = (ratio * 0x31BE135F97D08FD981231505542FCFA6) >> 128
    if abs_tick & 0x10000:
        ratio = (ratio * 0x9AA508B5B7A84E1C677DE54F3E99BC9) >> 128
    if abs_tick & 0x20000:
        ratio = (ratio * 0x5D6AF8DEDB81196699C329225EE604) >> 128
    if abs_tick & 0x40000:
        ratio = (ratio * 0x2216E584F5FA1EA926041BEDFE98) >> 128
    if abs_tick & 0x80000:
        ratio = (ratio * 0x48A170391F7DC42444E8FA2) >> 128

    if tick > 0:
        ratio = ((1 << 256) - 1) // ratio

    sqrt_price_x96 = (ratio >> 32) + (1 if ratio & ((1 << 32) - 1) else 0)
    return int(sqrt_price_x96)


def liquidity_for_amount0(sqrt_a: int, sqrt_b: int, amount0: int) -> int:
    if sqrt_a > sqrt_b:
        sqrt_a, sqrt_b = sqrt_b, sqrt_a
    intermediate = (sqrt_a * sqrt_b) // Q96
    return (amount0 * intermediate) // (sqrt_b - sqrt_a)


def liquidity_for_amount1(sqrt_a: int, sqrt_b: int, amount1: int) -> int:
    if sqrt_a > sqrt_b:
        sqrt_a, sqrt_b = sqrt_b, sqrt_a
    return (amount1 * Q96) // (sqrt_b - sqrt_a)


def max_liquidity_for_amounts(sqrt_p: int, sqrt_a: int, sqrt_b: int, amount0: int, amount1: int) -> int:
    if sqrt_a > sqrt_b:
        sqrt_a, sqrt_b = sqrt_b, sqrt_a

    if sqrt_p <= sqrt_a:
        return liquidity_for_amount0(sqrt_a, sqrt_b, amount0)

    if sqrt_p < sqrt_b:
        l0 = liquidity_for_amount0(sqrt_p, sqrt_b, amount0)
        l1 = liquidity_for_amount1(sqrt_a, sqrt_p, amount1)
        return int(min(l0, l1))

    return liquidity_for_amount1(sqrt_a, sqrt_b, amount1)


class _V4Planner:
    def __init__(self) -> None:
        self._actions_hex = "0x"
        self._params: list[bytes] = []

    def add(self, action: int, encoded_input: bytes) -> None:
        self._params.append(encoded_input)
        self._actions_hex += int(action).to_bytes(1, "big").hex()

    def finalize(self) -> bytes:
        actions_bytes = Web3.to_bytes(hexstr=self._actions_hex)
        return encode(["bytes", "bytes[]"], [actions_bytes, self._params])


class BitverseLiquidity(BitverseSpot):
    __module_name__ = "BitverseLiquidity"

    A_MINT_POSITION = 2
    A_SETTLE_PAIR = 13
    HOOK_DATA_DEFAULT = b""

    API_BASE = "https://api.bitverse.zone"

    def __init__(self, client: Client, wallet: Wallet):
        super().__init__(client=client, wallet=wallet)

        cfg = BITVERSE_LIQUIDITY_CONTRACTS_BY_CHAIN_ID.get(self.chain_id)
        if not cfg:
            raise ValueError(f"Unknown Bitverse chain_id for liquidity: {self.chain_id}")

        self.position_manager = RawContract(
            title="PositionManager",
            address=cfg.position_manager,
            abi=POSITION_MANAGER_ABI,
        )
        self.state_view = RawContract(
            title="StateView",
            address=cfg.state_view,
            abi=STATE_VIEW_ABI,
        )

    def _as_erc20(self, token: RawContract) -> RawContract:
        return RawContract(title=token.title or "ERC20", address=token.address, abi=DefaultABIs.Token)

    def _sorted_currencies(self, a: str, b: str) -> Tuple[str, str]:
        a = Web3.to_checksum_address(a)
        b = Web3.to_checksum_address(b)
        return (a, b) if int(a, 16) < int(b, 16) else (b, a)

    def _build_pool_key_tuple_liquidity(self, token_a: str, token_b: str, *, fee: int, tick_spacing: int, hooks: str) -> tuple:
        c0, c1 = self._sorted_currencies(token_a, token_b)
        return (c0, c1, _to_uint24(int(fee)), _to_int24(int(tick_spacing)), Web3.to_checksum_address(hooks))

    async def _erc20_allowance(self, token: RawContract, owner: str, spender: str) -> int:
        token = self._as_erc20(token)
        t = await self.client.contracts.get(contract_address=token)
        return int(await t.functions.allowance(Web3.to_checksum_address(owner), Web3.to_checksum_address(spender)).call())

    async def _erc20_approve_max(self, token: RawContract, spender: str) -> str:
        token = self._as_erc20(token)
        t = await self.client.contracts.get(contract_address=token)
        data = t.encode_abi("approve", args=[Web3.to_checksum_address(spender), 2**256 - 1])

        tx_params = TxParams(to=Web3.to_checksum_address(token.address), data=data, value=0)
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

    async def _sign_typed_data(self, typed_data: dict[str, Any]) -> str:
        from eth_account.messages import encode_typed_data

        msg = encode_typed_data(full_message=typed_data)
        signed = self.client.account.sign_message(msg)
        sig = signed.signature.hex()
        return sig if sig.startswith("0x") else "0x" + sig

    @async_retry(retries=3, delay=2, to_raise=True)
    async def fetch_spot_liquidity_pools(self, *, address: str, tab_type: int = 1, tenant_id: str = "ATLANTIC") -> list[SpotLiquidityPool]:
        url = f"{self.API_BASE}/bitverse/quote-all-in-one/v1/public/market/spot-liquidity-pool-all"
        params = {"address": Web3.to_checksum_address(address), "tabType": int(tab_type)}

        headers = {
            "accept": "application/json, text/plain, */*",
            "content-type": "application/json",
            "origin": "https://testnet.bitverse.zone",
            "referer": "https://testnet.bitverse.zone/",
            "chain-id": str(self.chain_id),
            "tenant-id": tenant_id,
        }

        async with BaseAsyncSession(headers=headers) as s:
            r = await s.get(url, params=params)
            if r.status_code != 200:
                raise RuntimeError(f"Bitverse pools http={r.status_code}: {r.text[:200]}")
            j = r.json()

        if int(j.get("retCode") or 0) != 0:
            raise RuntimeError(f"Bitverse pools error: {j.get('retMsg')}")

        pool_list = ((j.get("result") or {}).get("poolList")) or []
        return [SpotLiquidityPool.from_dict(p) for p in pool_list]

    def _pick_pool(self, pools: Sequence[SpotLiquidityPool], token_a: RawContract, token_b: RawContract) -> SpotLiquidityPool:
        a = Web3.to_checksum_address(token_a.address)
        b = Web3.to_checksum_address(token_b.address)

        for p in pools:
            t0 = Web3.to_checksum_address(p.token0.address)
            t1 = Web3.to_checksum_address(p.token1.address)
            if {t0, t1} == {a, b}:
                return p

        raise RuntimeError(f"Pool not found for pair: {token_a.title}/{token_b.title}")

    async def _ensure_erc20_approve_to_permit2(self, token: RawContract, *, min_allowance_wei: int) -> None:
        owner = Web3.to_checksum_address(self.client.account.address)
        permit2_addr = Web3.to_checksum_address(self.permit2.address)

        allow = await self._erc20_allowance(token, owner, permit2_addr)
        if allow >= int(min_allowance_wei):
            return

        txh = await self._erc20_approve_max(token, permit2_addr)
        logger.debug(f"{self.wallet} | {self.__module_name__} | approve token->permit2: {txh}")
        await asyncio.sleep(2)

    async def _build_permit2_batch_if_needed(
        self,
        *,
        tokens: Sequence[RawContract],
        spender: str,
        sig_deadline: int,
        amount_uint160: Optional[int] = None,
        expiration_uint48: Optional[int] = None,
    ) -> Optional[tuple[tuple, str]]:
        owner = Web3.to_checksum_address(self.client.account.address)
        spender = Web3.to_checksum_address(spender)

        now = int(time.time())
        details: list[tuple] = []

        amt160 = _to_uint160(int(amount_uint160 or (2**160 - 1)))
        exp48 = _to_uint48(int(expiration_uint48 or sig_deadline))

        for t in tokens:
            token_addr = Web3.to_checksum_address(t.address)
            p2_amount, p2_exp, p2_nonce = await self._permit2_allowance(owner, token_addr, spender)

            need = 1
            if p2_exp <= now or p2_amount < need:
                details.append((token_addr, amt160, exp48, _to_uint48(int(p2_nonce))))

        if not details:
            return None

        permit_batch = (details, spender, int(sig_deadline))

        typed = {
            "domain": {
                "name": "Permit2",
                "chainId": int(self.chain_id),
                "verifyingContract": Web3.to_checksum_address(self.permit2.address),
            },
            "primaryType": "PermitBatch",
            "types": {
                "EIP712Domain": [
                    {"name": "name", "type": "string"},
                    {"name": "chainId", "type": "uint256"},
                    {"name": "verifyingContract", "type": "address"},
                ],
                "PermitDetails": [
                    {"name": "token", "type": "address"},
                    {"name": "amount", "type": "uint160"},
                    {"name": "expiration", "type": "uint48"},
                    {"name": "nonce", "type": "uint48"},
                ],
                "PermitBatch": [
                    {"name": "details", "type": "PermitDetails[]"},
                    {"name": "spender", "type": "address"},
                    {"name": "sigDeadline", "type": "uint256"},
                ],
            },
            "message": {
                "details": [{"token": d[0], "amount": str(d[1]), "expiration": str(d[2]), "nonce": str(d[3])} for d in details],
                "spender": spender,
                "sigDeadline": str(sig_deadline),
            },
        }

        sig = await self._sign_typed_data(typed)
        return permit_batch, sig

    async def _get_slot0(self, pool_id_hex: str) -> tuple[int, int]:
        sv = await self.client.contracts.get(contract_address=self.state_view)
        sqrt_price_x96, tick, _, _ = await sv.functions.getSlot0(Web3.to_bytes(hexstr=pool_id_hex)).call()
        return int(sqrt_price_x96), int(tick)

    def _extract_token_id_from_receipt(self, receipt: Any) -> Optional[int]:
        try:
            logs = receipt.get("logs") if isinstance(receipt, dict) else getattr(receipt, "logs", None)
            if not logs:
                return None

            transfer_sig = Web3.keccak(text="Transfer(address,address,uint256)").hex().lower()

            for lg in logs:
                topics = lg.get("topics") if isinstance(lg, dict) else getattr(lg, "topics", None)
                if not topics or len(topics) < 4:
                    continue

                t0 = topics[0].hex().lower() if hasattr(topics[0], "hex") else str(topics[0]).lower()
                if t0 != transfer_sig:
                    continue

                token_id_topic = topics[3]
                token_id_hex = token_id_topic.hex() if hasattr(token_id_topic, "hex") else str(token_id_topic)
                return int(token_id_hex, 16)
        except Exception:
            return None

        return None

    @async_retry(retries=3, delay=2, to_raise=True, exceptions=(ContractLogicError, Exception))
    async def add_liquidity_v4_mint_full_range(
        self,
        *,
        token_a: RawContract,
        token_b: RawContract,
        amount_a: TokenAmount,
        amount_b: TokenAmount,
        slippage_bps: int = 500,
        hooks: str = "0x0000000000000000000000000000000000000000",
        deadline_sec: int = 300,
        tenant_id: str = "ATLANTIC",
    ) -> LiquidityMintResult:
        if slippage_bps < 0 or slippage_bps > 10_000:
            raise ValueError("slippage_bps must be in [0..10000]")

        pools = await self.fetch_spot_liquidity_pools(address=self.client.account.address, tab_type=1, tenant_id=tenant_id)
        pool = self._pick_pool(pools, token_a=token_a, token_b=token_b)

        fee = int(pool.fee)
        tick_spacing = int(pool.tick_spacing)

        tick_lower = nearest_usable_tick(MIN_TICK, tick_spacing)
        tick_upper = nearest_usable_tick(MAX_TICK, tick_spacing)

        pool_key = self._build_pool_key_tuple_liquidity(
            token_a.address,
            token_b.address,
            fee=fee,
            tick_spacing=tick_spacing,
            hooks=hooks,
        )

        sqrt_price_x96, _tick = await self._get_slot0(pool.pool_id)

        token0_addr = Web3.to_checksum_address(pool_key[0])
        token1_addr = Web3.to_checksum_address(pool_key[1])

        a_addr = Web3.to_checksum_address(token_a.address)
        b_addr = Web3.to_checksum_address(token_b.address)

        if {a_addr, b_addr} != {token0_addr, token1_addr}:
            raise RuntimeError("pool_key currency mismatch")

        amount0_desired = int(amount_a.Wei) if a_addr == token0_addr else int(amount_b.Wei)
        amount1_desired = int(amount_b.Wei) if b_addr == token1_addr else int(amount_a.Wei)

        sqrt_a = get_sqrt_ratio_at_tick(int(tick_lower))
        sqrt_b = get_sqrt_ratio_at_tick(int(tick_upper))

        liquidity = max_liquidity_for_amounts(
            int(sqrt_price_x96),
            int(sqrt_a),
            int(sqrt_b),
            int(amount0_desired),
            int(amount1_desired),
        )

        if liquidity <= 0:
            raise RuntimeError("liquidity computed as 0")

        amount0_max = (int(amount0_desired) * (10_000 + int(slippage_bps))) // 10_000
        amount1_max = (int(amount1_desired) * (10_000 + int(slippage_bps))) // 10_000

        await self._ensure_erc20_approve_to_permit2(
            RawContract(title="token0", address=token0_addr, abi=DefaultABIs.Token), min_allowance_wei=1
        )
        await self._ensure_erc20_approve_to_permit2(
            RawContract(title="token1", address=token1_addr, abi=DefaultABIs.Token), min_allowance_wei=1
        )

        now = int(time.time())
        sig_deadline = now + 60 * 60 * 24 * 365 * 2

        permit = await self._build_permit2_batch_if_needed(
            tokens=(
                RawContract(title="token0", address=token0_addr, abi=DefaultABIs.Token),
                RawContract(title="token1", address=token1_addr, abi=DefaultABIs.Token),
            ),
            spender=self.position_manager.address,
            sig_deadline=int(sig_deadline),
        )

        planner = _V4Planner()

        pool_key_type = "(address,address,uint24,int24,address)"
        mint_types = [pool_key_type, "int24", "int24", "uint256", "uint128", "uint128", "address", "bytes"]
        mint_params = [
            pool_key,
            _to_int24(int(tick_lower)),
            _to_int24(int(tick_upper)),
            int(liquidity),
            _to_uint128(int(amount0_max)),
            _to_uint128(int(amount1_max)),
            Web3.to_checksum_address(self.client.account.address),
            self.HOOK_DATA_DEFAULT,
        ]

        planner.add(self.A_MINT_POSITION, encode(mint_types, mint_params))
        planner.add(self.A_SETTLE_PAIR, encode(["address", "address"], [token0_addr, token1_addr]))

        unlock_data = planner.finalize()
        deadline = int(time.time()) + int(deadline_sec)

        pm = await self.client.contracts.get(contract_address=self.position_manager)

        calls: list[bytes] = []

        if permit:
            permit_batch, sig = permit
            permit_call = pm.encode_abi(
                "permitBatch",
                args=[
                    Web3.to_checksum_address(self.client.account.address),
                    permit_batch,
                    Web3.to_bytes(hexstr=sig),
                ],
            )
            calls.append(Web3.to_bytes(hexstr=permit_call) if isinstance(permit_call, str) else permit_call)

        modify_call = pm.encode_abi("modifyLiquidities", args=[unlock_data, int(deadline)])
        calls.append(Web3.to_bytes(hexstr=modify_call) if isinstance(modify_call, str) else modify_call)

        multicall_data = pm.encode_abi("multicall", args=[calls])

        tx_params = TxParams(
            to=Web3.to_checksum_address(self.position_manager.address),
            data=multicall_data,
            value=0,
        )

        logger.debug(
            f"{self.wallet} | {self.__module_name__} | add liquidity | pool={pool.pool_symbol} | "
            f"fee={fee} spacing={tick_spacing} | tick=[{tick_lower},{tick_upper}] | "
            f"amount0Max={amount0_max} amount1Max={amount1_max} | permit={'yes' if permit else 'no'}"
        )

        tx = await self.client.transactions.sign_and_send(tx_params=tx_params)
        receipt = await tx.wait_for_receipt(client=self.client, timeout=300)
        if not receipt:
            raise Exception("liquidity receipt is None")

        txh = tx.hash.hex() if hasattr(tx.hash, "hex") else str(tx.hash)
        token_id = self._extract_token_id_from_receipt(receipt)

        return LiquidityMintResult(tx_hash=txh, token_id=token_id)

    @controller_log("Bitverse Liquidity")
    async def liquidity_controller(self) -> str:
        settings = Settings()

        percent = randfloat(from_=settings.bitverse_liquidity_percent_min, to_=settings.bitverse_liquidity_percent_max, step=0.011) / 100

        # tokens = [Contracts.USDT, Contracts.WETH]
        #
        # balance_map = await self.balance_map(tokens)
        # if not balance_map:
        #     return f"{self.wallet} | {self.__module_name__} | No balances try to faucet first"
        #
        # if all(float(value) == 0 for value in balance_map.values()):
        #     return "Failed | No balance in all tokens, try to faucet first"
        #
        #
        # token_a = random.choice(list(balance_map.keys()))
        # tokens.remove(token_a)
        #
        # token_b = random.choice(tokens)

        token_a = Contracts.USDT
        token_b = Contracts.WETH

        bal_a = await self.client.wallet.balance(token_a.address)
        bal_b = await self.client.wallet.balance(token_b.address)

        if bal_a.Wei <= 0 and bal_b.Wei <= 0:
            return f"{self.wallet} | {self.__module_name__} | No balances, try faucet first"

        if float(bal_a.Ether) <= 0.0001 and bal_b.Wei > 0:
            swap_amt = TokenAmount(
                amount=float(bal_b.Ether) * float(Decimal("0.2")),
                decimals=await self.client.transactions.get_decimals(contract=token_b.address),
            )
            await self.swap_exact_in_v4_single(
                token_in=token_b,
                token_out=token_a,
                amount_in=swap_amt,
                slippage_bps=50,
                candidates=(V4PoolCandidate(fee=3000, tick_spacing=5),),
                deadline_sec=300,
            )
            await asyncio.sleep(3)
            bal_a = await self.client.wallet.balance(token_a.address)
            bal_b = await self.client.wallet.balance(token_b.address)

        if float(bal_b.Ether) <= 0.000001 and bal_a.Wei > 0:
            swap_amt = TokenAmount(
                amount=float(bal_a.Ether) * float(Decimal("0.2")),
                decimals=await self.client.transactions.get_decimals(contract=token_a.address),
            )

            await self.swap_exact_in_v4_single(
                token_in=token_a,
                token_out=token_b,
                amount_in=swap_amt,
                slippage_bps=50,
                candidates=(V4PoolCandidate(fee=3000, tick_spacing=5),),
                deadline_sec=300,
            )
            await asyncio.sleep(3)
            bal_a = await self.client.wallet.balance(token_a.address)
            bal_b = await self.client.wallet.balance(token_b.address)

        if bal_a.Wei <= 0 or bal_b.Wei <= 0:
            return f"{self.wallet} | {self.__module_name__} | Failed to prepare two-token balances"

        amt_a = TokenAmount(
            amount=float(bal_a.Ether) * percent, decimals=await self.client.transactions.get_decimals(contract=token_a.address)
        )
        amt_b = TokenAmount(
            amount=float(bal_b.Ether) * percent, decimals=await self.client.transactions.get_decimals(contract=token_b.address)
        )

        res = await self.add_liquidity_v4_mint_full_range(
            token_a=token_a,
            token_b=token_b,
            amount_a=amt_a,
            amount_b=amt_b,
            slippage_bps=500,
            deadline_sec=300,
        )

        if res.token_id is not None:
            return f"Success | Added liquidity {amt_a} {token_a.title}/{amt_b} {token_b.title} | tokenId={res.token_id}"

        raise Exception(f"Failed | Added liquidity {token_a.title}/{token_b.title}")
