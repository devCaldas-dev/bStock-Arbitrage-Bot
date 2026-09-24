"""
Módulo para obtener cotizaciones oficiales de acciones del mercado tradicional (subyacentes)
en Wall Street a través de Yahoo Finance (yfinance).
"""

import logging
from decimal import Decimal, InvalidOperation
from typing import Optional

logger = logging.getLogger(__name__)


def fetch_underlying_price(ticker: str) -> Optional[Decimal]:
    """Obtiene el precio más reciente de una acción desde Yahoo Finance.

    Utiliza `fast_info['last_price']` para una recuperación ultrarrápida,
    con fallback a `history(period='1d')['Close']`.
    Convierte el resultado a `Decimal` para mantener precisión financiera.

    Args:
        ticker: Símbolo bursátil de la acción (ej. "TSLA", "AAPL", "NVDA").

    Returns:
        Decimal con el precio actual/cierre en USD o None si ocurre un error.
    """
    if not ticker:
        logger.warning("Ticker vacío proporcionado a fetch_underlying_price.")
        return None

    clean_ticker = ticker.strip().upper()

    try:
        import yfinance as yf

        ticker_obj = yf.Ticker(clean_ticker)

        price_val = None

        # 1. Intentar fast_info (más rápido y sin descargar histórico completo)
        try:
            fast_info = getattr(ticker_obj, "fast_info", None)
            if fast_info:
                # Intentar last_price o last_volume/previous_close
                price_val = fast_info.get("last_price")
                if price_val is None:
                    price_val = fast_info.get("regular_market_previous_close")
        except Exception as e:
            logger.debug("fast_info no disponible para %s: %s", clean_ticker, e)

        # 2. Fallback a historial de 1 día
        if price_val is None:
            try:
                hist = ticker_obj.history(period="1d")
                if not hist.empty and "Close" in hist.columns:
                    price_val = hist["Close"].iloc[-1]
            except Exception as e:
                logger.debug("Historial 1d falló para %s: %s", clean_ticker, e)

        if price_val is None:
            logger.warning("No se obtuvo precio válido de Yahoo Finance para '%s'.", clean_ticker)
            return None

        # 3. Conversión a Decimal usando str() para evitar imprecisiones de coma flotante
        price_dec = Decimal(str(price_val))
        logger.info("Precio subyacente Yahoo Finance para %s: %s USD", clean_ticker, price_dec)
        return price_dec

    except Exception as e:
        logger.error("Error al consultar Yahoo Finance para '%s': %s", clean_ticker, e)
        return None
