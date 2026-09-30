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
from typing import Any, Dict, Optional, Union

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

ERC20_READ_ABI = [
    {
        "constant": True,
        "inputs": [{"name": "account", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "", "type": "uint256"}],
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [
            {"name": "owner", "type": "address"},
            {"name": "spender", "type": "address"},
        ],
        "name": "allowance",
        "outputs": [{"name": "", "type": "uint256"}],
        "type": "function",
    },
]

STF_HINT = (
    "El destinatario no tiene saldo de bStock o no ha aprobado el router. "
    "En producción, requiere: (1) balance del bStock, (2) approve() al router."
)


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
            "token_in": token_in,
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
        result = {
            "success": False,
            "revert_reason": revert_msg,
            "gas_estimate": None,
        }

        if "STF" in revert_msg.upper():
            result["hint"] = STF_HINT
            token_in = tx.get("token_in")
            amount_required = int(tx.get("amount_in", 0))
            try:
                if not token_in:
                    raise ValueError("No se encontró token_in en la transacción")

                token_contract = w3.eth.contract(
                    address=w3.to_checksum_address(token_in),
                    abi=ERC20_READ_ABI,
                )
                router_address = w3.to_checksum_address(PANCAKE_V3_SWAP_ROUTER)
                balance = token_contract.functions.balanceOf(
                    w3.to_checksum_address(from_address)
                ).call()
                allowance = token_contract.functions.allowance(
                    w3.to_checksum_address(from_address), router_address
                ).call()
                balance_display = Decimal(balance) / Decimal(10**18)
                required_display = Decimal(amount_required) / Decimal(10**18)
                allowance_display = Decimal(allowance) / Decimal(10**18)
                logger.warning(
                    "STF diagnóstico - Balance actual: %s TSLAB, Requerido: %s TSLAB",
                    balance_display,
                    required_display,
                )
                logger.warning("STF diagnóstico - Allowance actual: %s TSLAB", allowance_display)
                result.update(
                    {
                        "balance_bstock": balance,
                        "required_bstock": amount_required,
                        "allowance_bstock": allowance,
                    }
                )
            except Exception as diagnostic_error:
                logger.warning("No se pudo obtener el diagnóstico ERC-20 de STF: %s", diagnostic_error)
                result["diagnostic_error"] = str(diagnostic_error)

        logger.warning("Simulación de transacción REVERTIDA: %s", revert_msg)
        return result


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


def build_api_swap_transaction(
    bstock_contract: str,
    usdt_contract: str = USDT_ADDRESS,
    amount_bstock: Union[Decimal, str, float] = Decimal("1.0"),
    wallet_address: str = "0x0000000000000000000000000000000000000001",
    chain_id: str = "56",
    slippage_pct: str = "0.5",
    current_price_usdt: Optional[Decimal] = None,
) -> Optional[Dict[str, Any]]:
    """Construye transacción de swap vía Binance Web3 API (flujo de dos pasos RWA: quote -> swap).

    Args:
        bstock_contract: Dirección del contrato del token bStock (tokenIn).
        usdt_contract: Dirección del contrato de USDT (tokenOut).
        amount_bstock: Cantidad de bStocks a intercambiar (Decimal o convertible).
        wallet_address: Dirección pública de la wallet del usuario.
        chain_id: Identificador de la cadena Binance (por defecto "56" para BSC).
        slippage_pct: Tolerancia de deslizamiento en porcentaje (ej. "0.5").
        current_price_usdt: Precio de referencia opcional para logging.

    Returns:
        Dict con to, data, value, gas, token_in, amount_in, quote_id, vendor, source,
        o None ante cualquier fallo.
    """
    try:
        from binance_web3_api import BinanceWeb3API

        api = BinanceWeb3API()
        if not hasattr(api, "get_aggregated_quote") or not hasattr(api, "build_swap_transaction"):
            logger.warning("BinanceWeb3API no dispone de get_aggregated_quote o build_swap_transaction.")
            return None

        if not isinstance(amount_bstock, Decimal):
            amount_bstock = Decimal(str(amount_bstock))
        if amount_bstock <= Decimal("0"):
            logger.warning("amount_bstock debe ser mayor que cero.")
            return None

        amount_wei = int(amount_bstock * Decimal(10**18))
        token_in = w3.to_checksum_address(bstock_contract)
        token_out = w3.to_checksum_address(usdt_contract)
        wallet_cs = w3.to_checksum_address(wallet_address)

        # Paso 1: Obtener cotización agregada
        quote_raw = api.get_aggregated_quote(
            chain_id=str(chain_id),
            amount=amount_wei,
            from_token=token_in,
            to_token=token_out,
            slippage=str(slippage_pct),
            wallet_address=wallet_cs,
        )
        quote = quote_raw[0] if isinstance(quote_raw, list) and quote_raw else quote_raw
        if not isinstance(quote, dict):
            logger.warning("Respuesta de cotización agregada vacía o inválida.")
            return None

        quote_id = quote.get("quoteId") or quote.get("orderId") or quote.get("id")
        if not quote_id:
            logger.warning("Cotización agregada no contiene quoteId.")
            return None

        vendor = quote.get("vendorName") or quote.get("vendor") or ""

        # Paso 2: Construir transacción de swap
        swap_raw = api.build_swap_transaction(
            chain_id=str(chain_id),
            amount=amount_wei,
            from_token=token_in,
            to_token=token_out,
            wallet_address=wallet_cs,
            quote_id=str(quote_id),
            slippage=str(slippage_pct),
        )
        swap = swap_raw[0] if isinstance(swap_raw, list) and swap_raw else swap_raw
        if not isinstance(swap, dict):
            logger.warning("Respuesta de swap vacía o inválida.")
            return None

        to_addr = swap.get("to") or swap.get("routerAddress") or ""
        data = swap.get("data") or swap.get("callData") or ""
        if not to_addr or not data:
            logger.warning("Datos de transacción incompletos en respuesta de swap.")
            return None

        gas_val = int(swap.get("gas") or swap.get("estimatedGas") or 300000)
        value_val = int(swap.get("value") or 0)
        vendor_final = vendor or swap.get("vendorName") or swap.get("vendor") or ""

        return {
            "to": w3.to_checksum_address(to_addr),
            "data": data,
            "value": value_val,
            "gas": gas_val,
            "token_in": token_in,
            "amount_in": amount_wei,
            "quote_id": str(quote_id),
            "vendor": vendor_final,
            "source": "binance_api_two_step",
        }
    except Exception as e:
        logger.warning("Error al orquestar build_api_swap_transaction: %s", e)
        return None


def build_approve_transaction(
    token_contract: str,
    amount_wei: int,
    chain_id: str = "56",
    vendor: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Construye calldata de aprobación ERC-20 mediante Binance Web3 Trading API.

    Args:
        token_contract: Dirección del token ERC-20 a aprobar.
        amount_wei: Monto en wei a aprobar.
        chain_id: Identificador de la cadena (por defecto "56").
        vendor: Nombre opcional del vendor/proveedor (ej. LiquidMesh, InchFusion).

    Returns:
        Dict con to, data, value=0, source="binance_api_approve" y vendor,
        o None si no está disponible o falla.
    """
    try:
        from binance_web3_api import BinanceWeb3API

        api = BinanceWeb3API()
        approve_fn = getattr(api, "get_erc20_approve_transaction", None) or getattr(
            api, "build_approve_transaction", None
        )
        if not approve_fn:
            logger.warning("BinanceWeb3API no dispone de método para approve de ERC-20.")
            return None

        kwargs: Dict[str, Any] = {
            "chain_id": str(chain_id),
            "token_contract": str(token_contract),
            "approve_amount": str(amount_wei),
        }
        if vendor:
            kwargs["vendor"] = str(vendor)

        try:
            raw = approve_fn(**kwargs)
        except TypeError:
            kwargs.pop("vendor", None)
            raw = approve_fn(**kwargs)

        if not raw and vendor:
            try:
                kwargs.pop("vendor", None)
                raw = approve_fn(**kwargs)
            except Exception:
                pass

        if not isinstance(raw, dict):
            logger.warning("Respuesta de approve no contiene datos válidos.")
            return None

        to_addr = raw.get("to") or raw.get("tokenContractAddress") or token_contract
        data = raw.get("data") or raw.get("callData") or ""
        if not data:
            logger.warning("Respuesta de approve sin calldata.")
            return None

        vendor_out = vendor or raw.get("vendor") or raw.get("vendorName")
        return {
            "to": w3.to_checksum_address(to_addr),
            "data": data,
            "value": 0,
            "vendor": vendor_out,
            "source": "binance_api_approve",
        }
    except Exception as e:
        logger.warning("Error en build_approve_transaction: %s", e)
        return None


def sign_transaction(tx: Dict[str, Any], nonce: Optional[int] = None) -> Optional[str]:
    """Firma localmente una transacción legacy con gasPrice para BSC (chainId=56).

    Lee la clave privada exclusivamente de la variable de entorno correspondiente.
    NUNCA imprime ni registra la clave en logs ni mensajes.

    Args:
        tx: Diccionario con parámetros to, data, value, gas, etc.
        nonce: Nonce opcional. Si es None, consulta el nonce pendiente on-chain.

    Returns:
        Cadena hexadecimal prefijada por 0x de la transacción firmada, o None.
    """
    try:
        pk = os.environ.get("WALLET_PRIVATE_KEY")
        if not pk:
            logger.warning("Clave privada ausente en variables de entorno.")
            return None

        account = w3.eth.account.from_key(pk)
        env_wallet = os.environ.get("WALLET_ADDRESS")
        if env_wallet and account.address.lower() != env_wallet.strip().lower():
            logger.warning("wallet mismatch")
            return None

        to_addr = w3.to_checksum_address(tx["to"])
        data = tx.get("data") or "0x"
        value = int(tx.get("value", 0))
        gas = int(tx.get("gas") or tx.get("gasLimit") or 250000)

        # Determinar gasPrice (legacy con +10% de margen)
        gas_price = tx.get("gasPrice")
        if not gas_price:
            try:
                from binance_web3_api import BinanceWeb3API

                api = BinanceWeb3API()
                if hasattr(api, "get_gas_price"):
                    gdata = api.get_gas_price("56")
                    if isinstance(gdata, dict):
                        evm_legacy = gdata.get("evmLegacyGasPrice") or {}
                        high = (
                            evm_legacy.get("highGasPrice")
                            or gdata.get("highGasPrice")
                            or gdata.get("gasPrice")
                        )
                        if high:
                            gas_price = int(int(high) * 11 // 10)
            except Exception:
                pass

        if not gas_price:
            try:
                network_gp = w3.eth.gas_price
                gas_price = int(int(network_gp) * 11 // 10)
            except Exception:
                gas_price = 3_000_000_000  # 3 gwei por defecto en BSC

        if nonce is None:
            nonce = w3.eth.get_transaction_count(account.address, "pending")

        tx_to_sign = {
            "to": to_addr,
            "value": value,
            "data": data,
            "gas": gas,
            "gasPrice": int(gas_price),
            "nonce": int(nonce),
            "chainId": 56,
        }

        signed = account.sign_transaction(tx_to_sign)
        raw_bytes = getattr(signed, "raw_transaction", None) or getattr(
            signed, "rawTransaction", None
        )
        if hasattr(raw_bytes, "hex"):
            signed_hex = raw_bytes.hex()
        elif isinstance(raw_bytes, (bytes, bytearray)):
            signed_hex = raw_bytes.hex()
        else:
            signed_hex = str(raw_bytes)

        if not signed_hex.startswith("0x"):
            signed_hex = f"0x{signed_hex}"

        logger.info("Transacción firmada exitosamente.")
        return signed_hex
    except Exception as e:
        logger.warning("Error al firmar transacción: %s", e)
        return None


def broadcast_signed_transaction(
    signed_hex: str,
    wallet_address: Optional[str] = None,
) -> Optional[str]:
    """Transmite una transacción previamente firmada mediante w3.eth.send_raw_transaction.

    Args:
        signed_hex: Transacción firmada en hexadecimal (con o sin prefijo 0x).
        wallet_address: Dirección opcional de la wallet.

    Returns:
        Hash hexadecimal de la transacción (0x...) o None en caso de error.
    """
    try:
        if not signed_hex:
            logger.warning("signed_hex no proporcionado para broadcast.")
            return None

        hex_clean = signed_hex[2:] if signed_hex.startswith("0x") else signed_hex
        raw_bytes = bytes.fromhex(hex_clean)
        tx_hash_bytes = w3.eth.send_raw_transaction(raw_bytes)
        tx_hash = tx_hash_bytes.hex()
        if not tx_hash.startswith("0x"):
            tx_hash = f"0x{tx_hash}"

        logger.info("Transacción transmitida: %s", tx_hash)
        return tx_hash
    except Exception as e:
        logger.warning("Error al transmitir transacción: %s", e)
        return None


def verify_transaction(
    tx_hash: str,
    chain_id: str = "56",
    max_polls: int = 10,
    poll_interval_s: float = 4.0,
) -> Dict[str, Any]:
    """Verifica el estado y confirmación de una transacción mediante polling acotado.

    Consulta transaction-detail-by-txhash en Binance Web3 API o el recibo on-chain.

    Args:
        tx_hash: Hash de la transacción a consultar.
        chain_id: Cadena donde reside la transacción (por defecto "56").
        max_polls: Número máximo de intentos de sondeo.
        poll_interval_s: Segundos de espera entre intentos.

    Returns:
        Dict con confirmed, success, block, gas_used y revert_reason.
    """
    for poll_idx in range(max_polls):
        # 1. Intentar consulta vía Binance Web3 API
        try:
            from binance_web3_api import BinanceWeb3API

            api = BinanceWeb3API()
            if hasattr(api, "get_transaction_detail"):
                detail = api.get_transaction_detail(tx_hash, str(chain_id))
                if isinstance(detail, dict) and detail.get("status"):
                    status_str = str(detail.get("status", "")).lower()
                    if status_str in ("success", "confirmed", "1"):
                        return {
                            "confirmed": True,
                            "success": True,
                            "block": detail.get("blockNumber") or detail.get("block"),
                            "gas_used": detail.get("gasUsed") or detail.get("gas_used"),
                            "revert_reason": None,
                        }
                    elif status_str in ("failed", "reverted", "0"):
                        return {
                            "confirmed": True,
                            "success": False,
                            "block": detail.get("blockNumber") or detail.get("block"),
                            "gas_used": detail.get("gasUsed") or detail.get("gas_used"),
                            "revert_reason": (
                                detail.get("revertReason")
                                or detail.get("errorMessage")
                                or "transaction failed"
                            ),
                        }
        except Exception:
            pass

        # 2. Intentar consulta on-chain vía RPC web3
        try:
            receipt = w3.eth.get_transaction_receipt(tx_hash)
            if receipt is not None:
                status = receipt.get("status")
                success = (status == 1)
                return {
                    "confirmed": True,
                    "success": success,
                    "block": receipt.get("blockNumber"),
                    "gas_used": receipt.get("gasUsed"),
                    "revert_reason": None if success else "Transaction reverted on-chain",
                }
        except Exception:
            pass

        if poll_idx < max_polls - 1 and poll_interval_s > 0:
            time.sleep(poll_interval_s)

    return {
        "confirmed": False,
        "success": False,
        "block": None,
        "gas_used": None,
        "revert_reason": "Polling timeout: transacción no confirmada en los intentos asignados.",
    }
