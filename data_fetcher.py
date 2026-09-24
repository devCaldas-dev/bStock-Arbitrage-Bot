"""
Módulo de Extracción y Unificación de Precios (Data Fetcher).

Obtiene y consolida cotizaciones y metadatos de acciones tokenizadas (bStocks):
1. Ondo Finance API: Precios oficiales de la acción real subyacente en Wall Street.
2. Binance Web3 API: Catálogo RWA en BNB Smart Chain (BSC) con direcciones de contrato y multiplicadores.
3. Web3 Directo (PancakeSwap V2): Lectura de reservas on-chain en BSC para obtener el precio real en USDT.

Flujo de Precios On-Chain:
1. Se obtiene el contrato y multiplicador del bStock desde el catálogo de Binance.
2. Se consulta el precio en DEX (PancakeSwap V2 / USDT) usando Web3.
3. Si Web3 falla o no hay pool, se usa el precio primario de Ondo como respaldo.
4. El precio por acción on-chain se calcula como: price_usdt / multiplier.

Todos los precios y factores se procesan utilizando `Decimal` para evitar errores de precisión financiera.
"""

import logging
import time
from decimal import Decimal, InvalidOperation, DivisionByZero
from typing import Any, Dict, List, Optional
import requests
from requests.exceptions import RequestException, Timeout, HTTPError

from config import (
    BINANCE_API_BASE_URL,
    BINANCE_CATALOG_TTL,
    DEFAULT_CHAIN_ID,
    ONDO_API_BASE_URL,
    ONDO_API_KEY,
    REQUEST_TIMEOUT,
)
from web3_price_fetcher import fetch_onchain_price_web3

# Configuración del logger para este módulo
logger = logging.getLogger(__name__)

# Caché en memoria a nivel de módulo para el catálogo de Binance Web3
# El endpoint retorna ~1925 elementos (~500KB); la caché previene llamadas innecesarias por iteración.
_catalog_cache: Dict[str, Any] = {"data": None, "timestamp": 0.0}


def fetch_ondo_price(symbol: str) -> Optional[Dict[str, Any]]:
    """Obtiene el precio del bStock y de la acción subyacente desde la API de Ondo Finance.

    Args:
        symbol: Símbolo del token en Ondo (debe terminar en 'on', ej. 'TSLAon', 'AAPLon').

    Returns:
        Un diccionario con la información del activo si la consulta es exitosa:
        {
            "symbol": str,
            "primary_price": Decimal,
            "underlying_price": Decimal,
            "underlying_ticker": str,
            "timestamp": int
        }
        Retorna None si la consulta falla, si la API key no está configurada,
        o si el precio subyacente es nulo (ej. fuera de horario bursátil).
    """
    if not ONDO_API_KEY:
        logger.error(
            "Falta la clave ONDO_API_KEY en las variables de entorno. "
            "No se puede consultar la API de Ondo Finance."
        )
        return None

    # Validación de formato de símbolo Ondo
    if not symbol or not symbol.endswith("on"):
        logger.warning(
            "Símbolo Ondo '%s' no parece tener el formato esperado (debe terminar en 'on').",
            symbol,
        )
        return None

    url = f"{ONDO_API_BASE_URL}/{symbol}/prices/latest"
    headers = {
        "x-api-key": ONDO_API_KEY,
        "Accept": "application/json",
    }

    try:
        response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)

        # Manejo de códigos de estado HTTP comunes
        if response.status_code in (401, 403):
            logger.error("Error de autenticación con Ondo Finance: API Key inválida o no autorizada.")
            return None
        if response.status_code == 429:
            logger.warning("Límite de peticiones alcanzado en Ondo Finance API (Rate Limited).")
            return None
        if response.status_code in (400, 404):
            logger.warning("Símbolo '%s' no encontrado o inválido en Ondo Finance.", symbol)
            return None

        response.raise_for_status()
        payload = response.json()

        primary_market = payload.get("primaryMarket") or {}
        underlying_market = payload.get("underlyingMarket") or {}
        timestamp = payload.get("timestamp")

        # El precio de primaryMarket viene como string
        primary_price_raw = primary_market.get("price")
        if primary_price_raw is None:
            logger.warning("Ondo: El campo 'primaryMarket.price' es nulo para '%s'.", symbol)
            return None

        primary_price = Decimal(str(primary_price_raw))

        # El precio de la acción subyacente puede ser null fuera de horario de mercado
        underlying_price_raw = underlying_market.get("price")
        if underlying_price_raw is None:
            logger.warning(
                "Ondo: 'underlyingMarket.price' es null para '%s' (posiblemente fuera de horario de mercado).",
                symbol,
            )
            return None

        underlying_price = Decimal(str(underlying_price_raw))
        underlying_ticker = underlying_market.get("ticker", "")

        return {
            "symbol": symbol,
            "primary_price": primary_price,
            "underlying_price": underlying_price,
            "underlying_ticker": underlying_ticker,
            "timestamp": timestamp,
        }

    except Timeout:
        logger.error("Timeout de red (%ss) al consultar Ondo Finance para '%s'.", REQUEST_TIMEOUT, symbol)
        return None
    except HTTPError as e:
        logger.error("Error HTTP al consultar Ondo Finance: %s", e)
        return None
    except RequestException as e:
        logger.error("Error de conexión al consultar Ondo Finance: %s", e)
        return None
    except (ValueError, KeyError, InvalidOperation) as e:
        logger.error("Error al procesar la respuesta de Ondo Finance: %s", e)
        return None


def fetch_binance_catalog(ticker: str, chain_id: str = DEFAULT_CHAIN_ID) -> Optional[Dict[str, Any]]:
    """Busca un bStock en el catálogo de Binance Web3 por su ticker.

    NOTA: El endpoint de Binance Web3 NO es un feed de precios. Devuelve un CATÁLOGO
    exhaustivo de tokens RWA con sus direcciones de contrato y multiplicadores en BSC.
    Implementa caché en memoria con TTL de 1 hora para optimizar el rendimiento.

    Args:
        ticker: Ticker de la acción SIN sufijo (ej. 'TSLA', 'EEM', 'AAPL').
        chain_id: ID de la cadena blockchain (por defecto '56' para BSC).

    Returns:
        Dict con:
        {
            "symbol": str,
            "ticker": str,
            "contract_address": str,
            "multiplier": Decimal,
            "chain_id": str
        }
        O None si no se encuentra en el catálogo o falla la consulta.
    """
    global _catalog_cache

    if not ticker:
        logger.warning("Ticker vacío proporcionado a fetch_binance_catalog.")
        return None

    target_ticker = ticker.strip().upper()
    now = time.time()

    # 1. Verificar si la caché en memoria sigue vigente
    catalog_items: Optional[List[Dict[str, Any]]] = None
    if _catalog_cache["data"] is not None and (now - _catalog_cache["timestamp"]) < BINANCE_CATALOG_TTL:
        catalog_items = _catalog_cache["data"]
    else:
        # Petición HTTP al endpoint de catálogo
        params = {"chainId": chain_id}
        try:
            response = requests.get(BINANCE_API_BASE_URL, params=params, timeout=REQUEST_TIMEOUT)

            if response.status_code == 429:
                logger.warning("Límite de peticiones alcanzado en Binance Web3 API (Rate Limited).")
                return None

            response.raise_for_status()
            payload = response.json()

            is_success = payload.get("success") is True or payload.get("code") == "000000"
            if not is_success:
                logger.warning("Binance API respondió sin éxito al consultar catálogo: %s", payload.get("message"))
                return None

            raw_data = payload.get("data")
            if not isinstance(raw_data, list):
                logger.warning("La respuesta de Binance API no contiene una lista de datos válida.")
                return None

            # Actualizar caché
            _catalog_cache["data"] = raw_data
            _catalog_cache["timestamp"] = now
            catalog_items = raw_data
            logger.info("Catálogo de Binance Web3 actualizado en caché (%d activos cargados).", len(raw_data))

        except Timeout:
            logger.error("Timeout de red (%ss) al consultar catálogo de Binance Web3.", REQUEST_TIMEOUT)
            return None
        except HTTPError as e:
            logger.error("Error HTTP al consultar catálogo de Binance Web3: %s", e)
            return None
        except RequestException as e:
            logger.error("Error de conexión al consultar catálogo de Binance Web3: %s", e)
            return None
        except (ValueError, KeyError) as e:
            logger.error("Error al procesar el JSON del catálogo de Binance Web3: %s", e)
            return None

    # 2. Filtrar la lista por item['ticker'] == ticker.upper() y chainId
    matching_items = [
        item
        for item in catalog_items
        if isinstance(item, dict)
        and str(item.get("chainId")) == str(chain_id)
        and str(item.get("ticker", "")).strip().upper() == target_ticker
    ]

    if not matching_items:
        logger.warning(
            "Ticker '%s' no encontrado en el catálogo de Binance para chainId=%s.",
            target_ticker,
            chain_id,
        )
        return None

    # Priorizar tokens con par de trading en DEX (campo 'cs') o terminados en 'B' (ej. TSLAB en PancakeSwap)
    selected_item = next(
        (item for item in matching_items if item.get("cs") or str(item.get("symbol", "")).endswith("B")),
        None,
    )
    if not selected_item:
        # Alternativamente priorizar tokens terminados en 'on' o el primero de la lista
        selected_item = next(
            (item for item in matching_items if str(item.get("symbol", "")).endswith("on")),
            matching_items[0],
        )

    # 3. Extraer contractAddress, symbol, multiplier y convertir a Decimal
    try:
        raw_multiplier = selected_item.get("multiplier", "1")
        multiplier = Decimal(str(raw_multiplier))
        if multiplier <= Decimal("0"):
            logger.error("Multiplicador inválido (<=0) para '%s': %s", target_ticker, multiplier)
            return None
    except (InvalidOperation, TypeError, ValueError) as e:
        logger.error("Error al convertir multiplier a Decimal para '%s': %s", target_ticker, e)
        return None

    return {
        "symbol": selected_item.get("symbol", f"{target_ticker}B"),
        "ticker": target_ticker,
        "contract_address": selected_item.get("contractAddress", ""),
        "multiplier": multiplier,
        "chain_id": str(chain_id),
    }


def fetch_prices(ticker: str, ondo_symbol: str) -> Optional[Dict[str, Any]]:
    """Obtiene y unifica los datos de Ondo Finance (precios subyacentes) y Web3 / PancakeSwap V2 (on-chain).

    Flujo de integración:
    1. Consulta el precio subyacente oficial en Wall Street desde Ondo Finance.
    2. Consulta el catálogo de Binance Web3 para obtener la dirección del contrato en BSC y el multiplier.
    3. Consulta el precio on-chain real directamente en PancakeSwap V2 mediante Web3 (fetch_onchain_price_web3).
       - Si Web3 tiene éxito: onchain_price = price_usdt / multiplier.
       - Si Web3 no encuentra pool pero Ondo está activo: onchain_price = ondo.primary_price / multiplier.
    4. Permite operar de forma desacoplada: si Ondo no está disponible (ej. sin API Key),
       el precio on-chain se obtiene íntegramente desde Web3.

    Args:
        ticker: Ticker de la acción SIN sufijo (ej. 'TSLA').
        ondo_symbol: Símbolo del activo en Ondo (con sufijo 'on', ej. 'TSLAon').

    Returns:
        Diccionario consolidado para el módulo de estrategia:
        {
            "symbol": str,
            "underlying_price": Optional[Decimal],
            "onchain_price": Optional[Decimal],
            "contract_address": Optional[str],
            "pair_address": Optional[str],
            "multiplier": Decimal,
            "ondo_timestamp": Optional[int],
            "sources": {"ondo": bool, "binance": bool, "web3": bool}
        }
        Retorna None si no se puede obtener información de ninguna fuente.
    """
    clean_ticker = ticker.strip().upper()
    logger.info("Consultando datos unificados para ticker:'%s' y Ondo:'%s'...", clean_ticker, ondo_symbol)

    ondo_data = fetch_ondo_price(ondo_symbol)
    binance_data = fetch_binance_catalog(clean_ticker)

    ondo_ok = ondo_data is not None
    binance_ok = binance_data is not None

    if not ondo_ok and not binance_ok:
        logger.error(
            "Fallo total: Ambas fuentes (Ondo y Binance) fallaron para '%s' / '%s'.",
            clean_ticker,
            ondo_symbol,
        )
        return None

    # 1. Obtener precio on-chain desde Web3 si disponemos del contrato
    web3_data: Optional[Dict[str, Any]] = None
    web3_ok = False
    contract_address: Optional[str] = None
    multiplier = Decimal("1.0")

    if binance_ok and binance_data:
        contract_address = binance_data.get("contract_address")
        multiplier = binance_data.get("multiplier", Decimal("1.0"))
        if contract_address:
            web3_data = fetch_onchain_price_web3(contract_address)
            if web3_data and web3_data.get("price_usdt") is not None:
                web3_ok = True
                logger.info(
                    "Precio Web3 PancakeSwap obtenido para %s (%s): %s USDT",
                    clean_ticker,
                    contract_address,
                    web3_data["price_usdt"],
                )

    # 2. Calcular onchain_price
    onchain_price: Optional[Decimal] = None
    pair_address: Optional[str] = None

    if web3_ok and web3_data:
        try:
            onchain_price = web3_data["price_usdt"] / multiplier
            pair_address = web3_data.get("pair_address")
        except (DivisionByZero, InvalidOperation) as e:
            logger.error("Error al calcular onchain_price desde Web3: %s", e)
            onchain_price = web3_data["price_usdt"]
    elif ondo_ok and ondo_data and ondo_data.get("primary_price") is not None:
        # Fallback a precio primario de Ondo ajustado por multiplicador
        logger.info("Usando precio primario de Ondo como fallback on-chain.")
        try:
            onchain_price = ondo_data["primary_price"] / multiplier
        except (DivisionByZero, InvalidOperation) as e:
            logger.error("Error al calcular onchain_price desde Ondo: %s", e)
            onchain_price = ondo_data["primary_price"]
    else:
        logger.warning("No se pudo obtener precio on-chain para '%s' ni por Web3 ni por Ondo.", clean_ticker)

    # 3. Precio subyacente
    underlying_price: Optional[Decimal] = None
    ondo_timestamp: Optional[int] = None
    if ondo_ok and ondo_data:
        underlying_price = ondo_data.get("underlying_price")
        ondo_timestamp = ondo_data.get("timestamp")
    else:
        logger.warning(
            "Ondo no retornó datos para '%s' (verifique ONDO_API_KEY o horario bursátil).",
            ondo_symbol,
        )

    # Si ni Web3 ni Ondo retornaron precio alguno y tampoco hay datos básicos, retornar None
    if onchain_price is None and underlying_price is None and not binance_ok:
        return None

    unified_data: Dict[str, Any] = {
        "symbol": clean_ticker,
        "underlying_price": underlying_price,
        "onchain_price": onchain_price,
        "contract_address": contract_address,
        "pair_address": pair_address,
        "multiplier": multiplier,
        "ondo_timestamp": ondo_timestamp,
        "sources": {
            "ondo": ondo_ok,
            "binance": binance_ok,
            "web3": web3_ok,
        },
    }

    logger.info("Datos consolidados con éxito para '%s': %s", clean_ticker, unified_data)
    return unified_data
