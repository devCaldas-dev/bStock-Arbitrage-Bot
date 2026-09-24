# web3_price_fetcher.py
import os
from decimal import Decimal
from web3 import Web3
from typing import Optional, Dict, Any

# --- Configuración ---
# Usar un RPC público de BSC (o uno propio para mayor estabilidad)
BSC_RPC_URL = os.getenv("BSC_RPC_URL", "https://bsc-dataseed.binance.org/")
w3 = Web3(Web3.HTTPProvider(BSC_RPC_URL))

# Direcciones en BSC
PANCAKE_V2_FACTORY = "0xcA143Ce32Fe78f1f7019d7d551a6402fC5350c73"
PANCAKE_V3_FACTORY = "0x0BFbCF9fa4f9C56B0F40a671Ad40E0805A091865"
USDT_ADDRESS = "0x55d398326f99059fF775485246999027B3197955"  # USDT en BSC

# ABI mínima para interactuar con la Factory V2
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

# ABI mínima para el Pair V2 (getReserves + token0/token1)
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


def get_v2_pair_address(token_a: str, token_b: str) -> Optional[str]:
    """Obtiene la dirección del pool V2 para un par de tokens."""
    factory = w3.eth.contract(address=w3.to_checksum_address(PANCAKE_V2_FACTORY), abi=FACTORY_V2_ABI)
    try:
        pair = factory.functions.getPair(
            w3.to_checksum_address(token_a),
            w3.to_checksum_address(token_b)
        ).call()
        return pair if pair != "0x0000000000000000000000000000000000000000" else None
    except Exception as e:
        print(f"[ERROR] getPair falló: {e}")
        return None


def get_v2_price(pair_address: str, bstock_address: str) -> Optional[Decimal]:
    """
    Calcula el precio de un bStock en USDT usando las reservas del pool V2.
    """
    pair = w3.eth.contract(address=w3.to_checksum_address(pair_address), abi=PAIR_V2_ABI)

    try:
        token0 = pair.functions.token0().call()
        token1 = pair.functions.token1().call()
        reserves = pair.functions.getReserves().call()
        reserve0, reserve1 = Decimal(reserves[0]), Decimal(reserves[1])

        bstock = w3.to_checksum_address(bstock_address)
        usdt = w3.to_checksum_address(USDT_ADDRESS)

        # Determinar qué reserva corresponde a qué token
        if token0 == bstock and token1 == usdt:
            price = reserve1 / reserve0  # Precio en USDT por bStock
        elif token1 == bstock and token0 == usdt:
            price = reserve0 / reserve1
        else:
            print(f"[WARN] El pool {pair_address} no contiene bStock/USDT")
            return None

        # Ajustar por decimales. USDT tiene 18 decimales en BSC, bStock también (d=18)
        # La fórmula con Decimal ya maneja la relación, pero si los decimales difieren:
        # price = (reserve_usdt / 10**usdt_decimals) / (reserve_bstock / 10**bstock_decimals)
        # Para el catálogo de Binance, d=18 para ambos.
        return price

    except Exception as e:
        print(f"[ERROR] getReserves falló para {pair_address}: {e}")
        return None


def fetch_onchain_price_web3(bstock_contract: str) -> Optional[Dict[str, Any]]:
    """
    Obtiene el precio on-chain de un bStock desde PancakeSwap V2.

    Args:
        bstock_contract: Dirección del contrato del bStock (desde catálogo de Binance).

    Returns:
        Dict con: price_usdt (Decimal), pair_address, source. O None si falla.
    """
    # 1. Buscar el pool V2 contra USDT
    pair_addr = get_v2_pair_address(bstock_contract, USDT_ADDRESS)
    if not pair_addr:
        print(f"[WARN] No se encontró pool V2 para {bstock_contract}/USDT")
        return None

    # 2. Leer el precio desde las reservas
    price = get_v2_price(pair_addr, bstock_contract)
    if price is None:
        return None

    return {
        "price_usdt": price,
        "pair_address": pair_addr,
        "source": "pancakeswap_v2",
    }