"""
Módulo de Construcción, Simulación y Registro de Transacciones (Executor).

Se encarga de:
1. Construir transacciones de swap exactInputSingle en PancakeSwap V3 (bStock -> USDT).
2. Simular transacciones de forma segura mediante eth_call antes de cualquier envío.
3. Registrar señales y metadatos de ejecución en un archivo JSON persistente (signals_log.json).
"""

import json
import logging
import os
import time
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, Optional

from web3 import Web3

from config import (
    PANCAKE_V3_SWAP_ROUTER,
    SIGNALS_LOG_PATH,
    USDT_ADDRESS,
)
from web3_price_fetcher import fetch_onchain_price_v3, w3

logger = logging.getLogger(__name__)

# ABI mínima oficial para PancakeSwap V3 SwapRouter (exactInputSingle)
SWAP_ROUTER_V3_ABI = [
    {
        "inputs": [
            {
                "components": [
                    {"internalType": "address", "name": "tokenIn", "type": "address"},
                    {"internalType": "address", "name": "tokenOut", "type": "address"},
                    {"internalType": "uint24", "name": "fee", "type": "uint24"},
                    {"internalType": "address", "name": "recipient", "type": "address"},
                    {"internalType": "uint256", "name": "deadline", "type": "uint256"},
                    {"internalType": "uint256", "name": "amountIn", "type": "uint256"},
                    {"internalType": "uint256", "name": "amountOutMinimum", "type": "uint256"},
                    {"internalType": "uint160", "name": "sqrtPriceLimitX96", "type": "uint160"},
                ],
                "internalType": "struct ISwapRouter.ExactInputSingleParams",
                "name": "params",
                "type": "tuple",
            }
        ],
        "name": "exactInputSingle",
        "outputs": [{"internalType": "uint256", "name": "amountOut", "type": "uint256"}],
        "stateMutability": "payable",
        "type": "function",
    }
]


def build_swap_transaction(
    bstock_contract: str,
    usdt_contract: str = USDT_ADDRESS,
    amount_bstock: Decimal = Decimal("1.0"),
    recipient: str = "0x0000000000000000000000000000000000000001",
    fee_tier: int = 2500,
    slippage_pct: Decimal = Decimal("0.5"),
    current_price_usdt: Optional[Decimal] = None,
) -> Optional[Dict[str, Any]]:
    """Construye la transacción de swap bStock -> USDT en PancakeSwap V3.

    Usa el SwapRouter V3 oficial (exactInputSingle):
    1. Convierte amount_bstock a uint256 (multiplicando por 10^18).
    2. Calcula amountOutMinimum aplicando slippage_pct sobre el precio actual.
    3. Codifica el calldata y estructura la transacción.

    Args:
        bstock_contract: Dirección del contrato del bStock a vender (tokenIn).
        usdt_contract: Dirección del contrato de USDT (tokenOut).
        amount_bstock: Cantidad de bStocks a vender.
        recipient: Dirección receptora de los USDT resultantes.
        fee_tier: Comisión del pool V3 (ej. 2500 para 0.25%).
        slippage_pct: Porcentaje de tolerancia al deslizamiento (ej. 0.5%).
        current_price_usdt: Precio de referencia opcional. Si no se suministra,
                            se consulta dinámicamente en PancakeSwap V3.

    Returns:
        Diccionario con to, data, value, gas, amount_in, amount_out_min y description,
        o None si no se puede determinar el precio para calcular amountOutMinimum.
    """
    try:
        if amount_bstock <= Decimal("0"):
            raise ValueError("amount_bstock debe ser mayor que cero")
        if slippage_pct < Decimal("0") or slippage_pct >= Decimal("100"):
            raise ValueError("slippage_pct debe estar entre 0 y 100")

        # Validación de direcciones
        token_in = w3.to_checksum_address(bstock_contract)
        token_out = w3.to_checksum_address(usdt_contract)
        recipient_cs = w3.to_checksum_address(recipient)
        router_addr = w3.to_checksum_address(PANCAKE_V3_SWAP_ROUTER)

        # 1. Convertir amount_bstock a uint256 (ambos tokens tienen 18 decimales)
        amount_in_int = int(amount_bstock * Decimal(10**18))

        # 2. Obtener precio actual si no fue suministrado
        price_ref = current_price_usdt
        if price_ref is None:
            v3_res = fetch_onchain_price_v3(bstock_contract, fee_tier=fee_tier)
            if v3_res and v3_res.get("price_usdt"):
                price_ref = v3_res["price_usdt"]
            else:
                logger.warning("No se pudo obtener precio actual para calcular amountOutMinimum.")
                return None
        if price_ref <= Decimal("0"):
            raise ValueError("current_price_usdt debe ser mayor que cero")

        # 3. Calcular amountOutMinimum con tolerancia de slippage
        # expected_out = amount_bstock * price_ref
        expected_out_usdt = amount_bstock * price_ref
        slippage_multiplier = Decimal("1.0") - (slippage_pct / Decimal("100"))
        min_out_usdt = expected_out_usdt * slippage_multiplier
        amount_out_min_int = int(min_out_usdt * Decimal(10**18))

        deadline = int(time.time()) + 1200  # 20 minutos de vigencia

        # 4. Estructurar parámetros de ExactInputSingleParams
        params = (
            token_in,
            token_out,
            fee_tier,
            recipient_cs,
            deadline,
            amount_in_int,
            amount_out_min_int,
            0,  # sqrtPriceLimitX96: 0 desactiva límite
        )

        # 5. Codificar calldata con Web3 contract
        router_contract = w3.eth.contract(address=router_addr, abi=SWAP_ROUTER_V3_ABI)
        calldata = router_contract.encode_abi("exactInputSingle", [params])

        description = (
            f"Swap {amount_bstock} bStock -> min {min_out_usdt:.4f} USDT "
            f"en PancakeSwap V3 (fee: {fee_tier}, slippage: {slippage_pct}%)"
        )

        logger.info("Transacción de swap construida exitosamente: %s", description)

        return {
            "to": router_addr,
            "data": calldata,
            "value": 0,
            "gas": 250000,
            "amount_in": amount_in_int,
            "amount_out_min": amount_out_min_int,
            "description": description,
        }

    except Exception as e:
        logger.error("Error al construir la transacción de swap: %s", e)
        return None


def simulate_transaction(tx: Dict[str, Any], from_address: str) -> Dict[str, Any]:
    """Simula la transacción mediante eth_call para verificar si revertiría.

    Args:
        tx: Diccionario de transacción generado por build_swap_transaction.
        from_address: Dirección de la cuenta simulada.

    Returns:
        Dict con:
        {
            "success": bool,
            "revert_reason": str | None,
            "gas_estimate": int | None
        }
    """
    call_tx = {
        "to": w3.to_checksum_address(tx["to"]),
        "from": w3.to_checksum_address(from_address),
        "data": tx["data"],
        "value": tx.get("value", 0),
    }

    try:
        # Ejecutar llamada de sólo lectura (simulación)
        w3.eth.call(call_tx, block_identifier="latest")

        # Intentar estimar gas si la llamada no revierte
        gas_estimate = None
        try:
            gas_estimate = w3.eth.estimate_gas(call_tx)
        except Exception:
            pass

        logger.info("Simulación de transacción EXITOSA (Gas estimado: %s).", gas_estimate)
        return {
            "success": True,
            "revert_reason": None,
            "gas_estimate": gas_estimate,
        }

    except Exception as e:
        revert_msg = str(e)
        logger.warning("Simulación de transacción REVERTIDA: %s", revert_msg)
        return {
            "success": False,
            "revert_reason": revert_msg,
            "gas_estimate": None,
        }


def log_signal_to_json(
    signal: Dict[str, Any],
    tx_data: Optional[Dict[str, Any]] = None,
    simulation: Optional[Dict[str, Any]] = None,
    filepath: str = SIGNALS_LOG_PATH,
) -> None:
    """Registra una señal comercial y sus datos de ejecución/simulación en un archivo JSON.

    Si el archivo no existe, crea una lista vacía. Agrega la nueva entrada preservando
    el histórico completo con tipos serializables.

    Args:
        signal: Diccionario de decisión de strategy.py (evaluate_opportunity).
        tx_data: Diccionario de transacción de build_swap_transaction.
        simulation: Diccionario de resultado de simulate_transaction.
        filepath: Ruta del archivo JSON de registro.
    """
    try:
        path = Path(filepath)
        history = []
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                    if content:
                        history = json.loads(content)
                        if not isinstance(history, list):
                            history = []
            except Exception as e:
                logger.warning("No se pudo leer archivo de señales existente: %s. Creando nuevo.", e)
                history = []

        entry = {
            "timestamp": signal.get("timestamp", int(time.time())),
            "ticker": signal.get("ticker"),
            "action": signal.get("action"),
            "spread_pct": str(signal.get("spread_pct")) if signal.get("spread_pct") is not None else None,
            "spread_usd": str(signal.get("spread_usd")) if signal.get("spread_usd") is not None else None,
            "net_profit_estimate": (
                str(signal.get("net_profit_estimate"))
                if signal.get("net_profit_estimate") is not None
                else None
            ),
            "reason": signal.get("reason"),
            "tx_data": tx_data,
            "simulation": simulation,
        }

        history.append(entry)

        with open(path, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2, default=str)

        logger.info("Señal para %s [%s] registrada exitosamente en %s.", signal.get("ticker"), signal.get("action"), filepath)

    except Exception as e:
        logger.error("Error al registrar señal en JSON: %s", e)
