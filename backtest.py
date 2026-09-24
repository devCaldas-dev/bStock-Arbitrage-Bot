"""Backtest de señales de arbitraje usando cierres historicos y on-chain simulado.

El proyecto no integra un indexador historico de PancakeSwap. Por eso el precio
on-chain del backtest se deriva del precio on-chain actual, cuando esta
 disponible, y se le aplica una variacion determinista de hasta +/-3%. Esa parte
se etiqueta como simulada en el resultado y no representa una cotizacion
historica real.
"""

import json
import logging
import random
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from config import MONITORED_TICKERS
from data_fetcher import fetch_prices
from strategy import evaluate_opportunity

logger = logging.getLogger(__name__)
DEFAULT_OUTPUT_PATH = "backtest_results.json"
DEFAULT_DAYS = 7
MAX_SYNTHETIC_VARIATION_PCT = Decimal("3")


def fetch_underlying_history(ticker: str, days: int = DEFAULT_DAYS) -> List[Tuple[date, Decimal]]:
    """Descarga las ultimas observaciones diarias de cierre desde Yahoo Finance."""
    try:
        import yfinance as yf

        history = yf.Ticker(ticker).history(
            period=f"{days + 10}d",
            interval="1d",
            auto_adjust=False,
        )
        if history.empty or "Close" not in history.columns:
            return []

        observations: List[Tuple[date, Decimal]] = []
        for index, value in history["Close"].dropna().tail(days).items():
            observations.append((index.date(), Decimal(str(value))))
        return observations
    except (InvalidOperation, TypeError, ValueError) as error:
        logger.warning("Historial invalido para %s: %s", ticker, error)
        return []
    except Exception as error:
        logger.warning("No se pudo descargar historial para %s: %s", ticker, error)
        return []


def fetch_current_onchain_price(ticker: str) -> Tuple[Optional[Decimal], str]:
    """Obtiene el precio on-chain actual que sirve como base del escenario simulado."""
    try:
        market_data = fetch_prices(ticker)
        if market_data:
            price = market_data.get("onchain_price_per_share") or market_data.get("onchain_price")
            if price is not None:
                return Decimal(str(price)), "current_onchain_plus_synthetic_variation"
            underlying = market_data.get("underlying_price")
            if underlying is not None:
                return Decimal(str(underlying)), "underlying_proxy_plus_synthetic_variation"
    except Exception as error:
        logger.warning("No se pudo obtener referencia on-chain para %s: %s", ticker, error)
    return None, "unavailable"


def _synthetic_variation_pct(ticker: str, observation_index: int) -> Decimal:
    """Genera una variacion reproducible, acotada a +/-3%, para la demo."""
    seed = sum(ord(character) for character in ticker) + observation_index * 7919
    generator = random.Random(seed)
    maximum_variation = float(MAX_SYNTHETIC_VARIATION_PCT)
    variation = generator.uniform(-maximum_variation, maximum_variation)
    return Decimal(str(round(variation, 6)))


def _as_float(value: Optional[Decimal]) -> Optional[float]:
    return float(value) if value is not None else None


def run_backtest(
    days: int = DEFAULT_DAYS,
    output_path: str = DEFAULT_OUTPUT_PATH,
    tickers: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Ejecuta el backtest y guarda sus resultados en JSON.

    Las senales usan los cierres diarios reales de Yahoo Finance. El spread
    on-chain es una simulacion documentada, no un dato historico de blockchain.
    """
    selected_tickers = tickers or list(MONITORED_TICKERS)
    signals: List[Dict[str, Any]] = []
    all_dates = set()
    all_spreads: List[Decimal] = []
    theoretical_profit = Decimal("0")

    for ticker in selected_tickers:
        history = fetch_underlying_history(ticker, days)
        if not history:
            logger.warning("Sin datos historicos para %s; se omite.", ticker)
            continue

        reference_price, onchain_source = fetch_current_onchain_price(ticker)
        if reference_price is None or reference_price <= Decimal("0"):
            logger.warning("Sin referencia on-chain para %s; se omite.", ticker)
            continue

        for index, (observation_date, underlying_price) in enumerate(history):
            if underlying_price <= Decimal("0"):
                continue

            variation_pct = _synthetic_variation_pct(ticker, index)
            onchain_price = reference_price * (
                Decimal("1") + variation_pct / Decimal("100")
            )
            spread_usd = onchain_price - underlying_price
            spread_pct = (spread_usd / underlying_price) * Decimal("100")
            decision = evaluate_opportunity(
                {
                    "ticker": ticker,
                    "underlying_price": underlying_price,
                    "onchain_price": onchain_price,
                    "spread_usd": spread_usd,
                    "spread_pct": spread_pct,
                },
                {},
            )
            historical_timestamp = int(
                datetime.combine(
                    observation_date,
                    datetime.min.time(),
                    tzinfo=timezone.utc,
                ).timestamp()
            )
            net_profit = decision.get("net_profit_estimate")
            if decision.get("action") == "BUY" and net_profit is not None:
                theoretical_profit += net_profit

            all_dates.add(observation_date)
            all_spreads.append(spread_pct)
            signals.append(
                {
                    "date": observation_date.isoformat(),
                    "ticker": ticker,
                    "spread_pct": _as_float(spread_pct),
                    "action": decision.get("action"),
                    "net_profit": _as_float(net_profit),
                    "underlying_price": _as_float(underlying_price),
                    "onchain_price": _as_float(onchain_price),
                    "onchain_source": onchain_source,
                    "simulation_note": "On-chain price approximated with deterministic variation +/-3%; not historical blockchain data.",
                    "timestamp": historical_timestamp,
                }
            )

    signals.sort(key=lambda item: (item["date"], item["ticker"]))
    period_start = min(all_dates).isoformat() if all_dates else None
    period_end = max(all_dates).isoformat() if all_dates else None
    buy_signals = [signal for signal in signals if signal["action"] == "BUY"]
    result = {
        "periodo": f"{period_start} a {period_end}" if period_start and period_end else None,
        "tickers": selected_tickers,
        "signals_by_day": signals,
        "summary": {
            "total_days": len(all_dates),
            "buy_days": len({signal["date"] for signal in buy_signals}),
            "total_signals": len(signals),
            "buy_signals": len(buy_signals),
            "max_spread_pct": _as_float(max(all_spreads)) if all_spreads else None,
            "theoretical_profit_usd": _as_float(theoretical_profit),
            "onchain_data_mode": "simulated_current_price_plus_variation_up_to_3pct",
        },
    }

    Path(output_path).write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def print_summary(result: Dict[str, Any]) -> None:
    """Imprime un resumen corto para la demo del hackathon."""
    summary = result["summary"]
    print("=" * 62)
    print("BACKTEST - TOKENIZED STOCKS ON BNB CHAIN")
    print("=" * 62)
    print(f"Periodo               : {result['periodo']}")
    print(f"Tickers               : {', '.join(result['tickers'])}")
    print(f"Dias analizados       : {summary['total_days']}")
    print(f"Senales totales       : {summary['total_signals']}")
    print(f"Senales BUY           : {summary['buy_signals']}")
    print(f"Dias con BUY          : {summary['buy_days']}")
    print(f"Spread maximo         : {summary['max_spread_pct']}%")
    print(f"Ganancia teorica      : ${summary['theoretical_profit_usd']} USD")
    print("Precio on-chain       : Simulado desde referencia actual (+/-3%)")
    print(f"Resultados guardados  : {DEFAULT_OUTPUT_PATH}")
    print("=" * 62)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    print_summary(run_backtest())
