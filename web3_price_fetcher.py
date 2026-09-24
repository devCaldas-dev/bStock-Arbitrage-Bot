"""
Módulo de Consulta On-Chain Web3 para PancakeSwap V2 y V3 en BNB Smart Chain (BSC).

Permite consultar precios spot de bStocks en tiempo real contra USDT mediante:
1. PancakeSwap V3 (prioritario): Lectura de slot0() y liquidez en pools concentrados.
2. PancakeSwap V2 (fallback): Lectura de reservas con validación de liquidez mínima ($50K USD).

Fórmula Matemática PancakeSwap V3:
En V3, el estado del pool almacena sqrtPriceX96 = sqrt(token1 / token0) * 2^96.
El precio se deriva elevando al cuadrado:
    ratio = (sqrtPriceX96 / 2^96)^2 = (sqrtPriceX96^2) / (2^192)
Donde 'ratio' representa la relación token1 / token0.
Si token0 es USDT y token1 es bStock:
    precio_bstock_usdt = 1 / ratio
Si token0 es bStock y token1 es USDT:
    precio_bstock_usdt = ratio
"""

import logging
import os
from decimal import Decimal, getcontext
from typing import Any, Dict, Optional
from web3 import Web3

# Ajustar precisión suficiente para manejar aritmética con 2^192
getcontext().prec = 50

logger = logging.getLogger(__name__)

# --- Configuración y Constantes ---
BSC_RPC_URL = os.getenv("BSC_RPC_URL", "https://bsc-dataseed.binance.org/")
w3 = Web3(Web3.HTTPProvider(BSC_RPC_URL, request_kwargs={"timeout": 10}))

# Direcciones oficiales de contratos en BSC Mainnet
PANCAKE_V2_FACTORY = "0xcA143Ce32Fe78f1f7019d7d551a6402fC5350c73"
PANCAKE_V3_FACTORY = "0x0BFbCF9fa4f9C56B0F40a671Ad40E0805A091865"
PANCAKE_V3_QUOTER = "0xB048Bbc1Ee6b733FFfCFb9e9CeF7375518e25997"
USDT_ADDRESS = "0x55d398326f99059fF775485246999027B3197955"  # USDT en BSC (18 decimales)

# Umbral de liquidez mínima requerida para considerar válido un pool V2 (en USD)
MIN_LIQUIDITY_USD = Decimal("50000")

# --- ABIs Mínimas ---

FACTORY_V2_ABI = [
    {
        "constant": True,
        "inputs": [
            {"name": "tokenA", "type": "address"},
            {"name": "tokenB", "type": "address"},
        ],
        "name": "getPair",
        "outputs": [{"name": "", "type": "address"}],
        "type": "function",
    }
]

PAIR_V2_ABI = [
    {
        "constant": True,
        "inputs": [],
        "name": "getReserves",
        "outputs": [
            {"name": "_reserve0", "type": "uint112"},
            {"name": "_reserve1", "type": "uint112"},
            {"name": "_blockTimestampLast", "type": "uint32"},
        ],
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [],
        "name": "token0",
        "outputs": [{"name": "", "type": "address"}],
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [],
        "name": "token1",
        "outputs": [{"name": "", "type": "address"}],
        "type": "function",
    },
]

FACTORY_V3_ABI = [
    {
        "inputs": [
            {"internalType": "address", "name": "tokenA", "type": "address"},
            {"internalType": "address", "name": "tokenB", "type": "address"},
            {"internalType": "uint24", "name": "fee", "type": "uint24"},
        ],
        "name": "getPool",
        "outputs": [{"internalType": "address", "name": "pool", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    }
]

POOL_V3_ABI = [
    {
        "inputs": [],
        "name": "slot0",
        "outputs": [
            {"internalType": "uint160", "name": "sqrtPriceX96", "type": "uint160"},
            {"internalType": "int24", "name": "tick", "type": "int24"},
            {"internalType": "uint16", "name": "observationIndex", "type": "uint16"},
            {"internalType": "uint16", "name": "observationCardinality", "type": "uint16"},
            {"internalType": "uint16", "name": "observationCardinalityNext", "type": "uint16"},
            {"internalType": "uint32", "name": "feeProtocol", "type": "uint32"},
            {"internalType": "bool", "name": "unlocked", "type": "bool"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "liquidity",
        "outputs": [{"internalType": "uint128", "name": "", "type": "uint128"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "token0",
        "outputs": [{"internalType": "address", "name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "token1",
        "outputs": [{"internalType": "address", "name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    },
]


# ==============================================================================
# Funciones PancakeSwap V3
# ==============================================================================

def get_v3_pool_address(token_a: str, token_b: str, fee: int) -> Optional[str]:
    """Obtiene la dirección del pool PancakeSwap V3 para un par de tokens y un fee tier.

    Args:
        token_a: Dirección del token A.
        token_b: Dirección del token B.
        fee: Nivel de comisión del pool (ej. 500 = 0.05%, 2500 = 0.25%, 10000 = 1%).

    Returns:
        Dirección checksum del pool o None si no existe.
    """
    try:
        factory = w3.eth.contract(
            address=w3.to_checksum_address(PANCAKE_V3_FACTORY),
            abi=FACTORY_V3_ABI,
        )
        pool = factory.functions.getPool(
            w3.to_checksum_address(token_a),
            w3.to_checksum_address(token_b),
            fee,
        ).call()
        if pool and pool != "0x0000000000000000000000000000000000000000":
            return pool
        return None
    except Exception as e:
        logger.error("get_v3_pool_address falló para %s / %s (fee %s): %s", token_a, token_b, fee, e)
        return None


def fetch_onchain_price_v3(bstock_contract: str, fee_tier: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """Consulta el precio on-chain de un bStock contra USDT en PancakeSwap V3.

    Si no se especifica fee_tier, evalúa los tiers en orden de menor fee: [500, 2500, 10000].
    Valida que el pool tenga liquidez activa y que el precio esté en un rango razonable.

    Args:
        bstock_contract: Dirección del contrato del bStock.
        fee_tier: Nivel de comisión opcional a evaluar directamente.

    Returns:
        Dict con:
        {
            "price_usdt": Decimal,
            "pool_address": str,
            "fee_tier": int,
            "source": "pancakeswap_v3",
            "dex": "pancakeswap_v3",
            "liquidity": int
        }
        O None si no hay pool válido con liquidez.
    """
    tiers_to_try = [fee_tier] if fee_tier is not None else [500, 2500, 10000]
    bstock_cs = w3.to_checksum_address(bstock_contract)
    usdt_cs = w3.to_checksum_address(USDT_ADDRESS)

    two_96 = Decimal(2**96)

    for fee in tiers_to_try:
        pool_addr = get_v3_pool_address(bstock_cs, usdt_cs, fee)
        if not pool_addr:
            continue

        try:
            pool_contract = w3.eth.contract(address=w3.to_checksum_address(pool_addr), abi=POOL_V3_ABI)
            slot0_data = pool_contract.functions.slot0().call()
            liquidity = pool_contract.functions.liquidity().call()
            token0 = pool_contract.functions.token0().call()
            token1 = pool_contract.functions.token1().call()

            # Si la liquidez concentrada en el tick actual es 0, ignorar pool inactivo
            if liquidity == 0:
                logger.debug("Pool V3 %s (fee %s) tiene liquidez = 0. Saltando...", pool_addr, fee)
                continue

            sqrt_price_x96 = Decimal(slot0_data[0])
            if sqrt_price_x96 <= Decimal("0"):
                continue

            # Derivación matemática del precio V3:
            # ratio = (sqrtPriceX96 / 2^96)^2 = token1 / token0
            ratio = (sqrt_price_x96 / two_96) ** 2

            # Ambos tokens (USDT y bStocks en BSC) tienen 18 decimales
            if token0.lower() == bstock_cs.lower() and token1.lower() == usdt_cs.lower():
                price_usdt = ratio  # USDT por cada bStock
            elif token1.lower() == bstock_cs.lower() and token0.lower() == usdt_cs.lower():
                price_usdt = Decimal(1) / ratio  # Invertir relación para obtener USDT por bStock
            else:
                logger.warning("El pool V3 %s no coincide con bStock/USDT.", pool_addr)
                continue

            # Sanity check: rango de precio razonable para bStocks ($10 a $10000 USD)
            if price_usdt < Decimal("10") or price_usdt > Decimal("10000"):
                logger.warning(
                    "Precio V3 fuera de rango de cordura ($%s USDT) en pool %s. Saltando...",
                    price_usdt, pool_addr,
                )
                continue

            logger.info(
                "PancakeSwap V3 pool encontrado (%s, fee %s): %s USDT (Liquidez: %s)",
                pool_addr, fee, price_usdt, liquidity,
            )

            return {
                "price_usdt": price_usdt,
                "pool_address": pool_addr,
                "fee_tier": fee,
                "source": "pancakeswap_v3",
                "dex": "pancakeswap_v3",
                "liquidity": liquidity,
            }

        except Exception as e:
            logger.error("Error al leer slot0 del pool V3 %s (fee %s): %s", pool_addr, fee, e)
            continue

    return None


# ==============================================================================
# Funciones PancakeSwap V2
# ==============================================================================

def get_v2_pair_address(token_a: str, token_b: str) -> Optional[str]:
    """Obtiene la dirección del pool V2 para un par de tokens."""
    try:
        factory = w3.eth.contract(address=w3.to_checksum_address(PANCAKE_V2_FACTORY), abi=FACTORY_V2_ABI)
        pair = factory.functions.getPair(
            w3.to_checksum_address(token_a),
            w3.to_checksum_address(token_b),
        ).call()
        return pair if pair and pair != "0x0000000000000000000000000000000000000000" else None
    except Exception as e:
        logger.error("getPair V2 falló para %s / %s: %s", token_a, token_b, e)
        return None


def get_v2_price(pair_address: str, bstock_address: str) -> Optional[Decimal]:
    """Calcula el precio de un bStock en USDT usando reservas del pool V2 con validación de liquidez."""
    try:
        pair = w3.eth.contract(address=w3.to_checksum_address(pair_address), abi=PAIR_V2_ABI)
        token0 = pair.functions.token0().call()
        token1 = pair.functions.token1().call()
        reserves = pair.functions.getReserves().call()
        reserve0, reserve1 = Decimal(reserves[0]), Decimal(reserves[1])

        bstock = w3.to_checksum_address(bstock_address)
        usdt = w3.to_checksum_address(USDT_ADDRESS)

        if token0 == bstock and token1 == usdt:
            price = reserve1 / reserve0  # USDT por bStock
            reserve_usdt = reserve1
        elif token1 == bstock and token0 == usdt:
            price = reserve0 / reserve1
            reserve_usdt = reserve0
        else:
            logger.warning("El pool V2 %s no contiene bStock/USDT.", pair_address)
            return None

        # Validación de liquidez mínima:
        # reserve_usdt / 10^18 da los USDT totales. liquidity_usd ≈ reserve_usdt * 2
        usdt_normalized = reserve_usdt / Decimal(10**18)
        liquidity_usd = usdt_normalized * Decimal("2")

        if liquidity_usd < MIN_LIQUIDITY_USD:
            logger.warning(
                "Pool V2 %s rechazado por baja liquidez: ~$%.2f USD < mínimo $%.2f USD.",
                pair_address,
                liquidity_usd,
                MIN_LIQUIDITY_USD,
            )
            return None

        return price

    except Exception as e:
        logger.error("getReserves falló para pool V2 %s: %s", pair_address, e)
        return None


def fetch_onchain_price_v2(bstock_contract: str) -> Optional[Dict[str, Any]]:
    """Consulta el precio on-chain desde PancakeSwap V2 validando liquidez mínima."""
    pair_addr = get_v2_pair_address(bstock_contract, USDT_ADDRESS)
    if not pair_addr:
        logger.warning("No se encontró pool V2 para %s/USDT.", bstock_contract)
        return None

    price = get_v2_price(pair_addr, bstock_contract)
    if price is None:
        return None

    return {
        "price_usdt": price,
        "pool_address": pair_addr,
        "source": "pancakeswap_v2",
        "dex": "pancakeswap_v2",
    }


# ==============================================================================
# Cascada de Consulta Unificada On-Chain (V3 -> V2)
# ==============================================================================

def fetch_onchain_price_web3(bstock_contract: str) -> Optional[Dict[str, Any]]:
    """Obtiene el precio on-chain ejecutando la cascada: V3 (500, 2500, 10000) -> V2 (fallback con liquidez).

    Args:
        bstock_contract: Dirección del contrato del bStock.

    Returns:
        Dict con 'price_usdt', 'pool_address', 'source' y 'dex' ("pancakeswap_v3" o "pancakeswap_v2").
        O None si ninguna opción es válida o no cumplen con liquidez mínima.
    """
    # 1. Intentar PancakeSwap V3 (prioritario por liquidez y precisión)
    v3_result = fetch_onchain_price_v3(bstock_contract)
    if v3_result:
        return v3_result

    logger.info("V3 no retornó pool con liquidez para %s. Intentando PancakeSwap V2 como fallback...", bstock_contract)

    # 2. Fallback a PancakeSwap V2 con filtro de MIN_LIQUIDITY_USD
    v2_result = fetch_onchain_price_v2(bstock_contract)
    if v2_result:
        return v2_result

    logger.warning("No se pudo obtener precio on-chain válido ni en V3 ni en V2 para %s.", bstock_contract)
    return None