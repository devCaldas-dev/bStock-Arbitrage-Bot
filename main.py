"""
Módulo Principal de Ejecución y Monitoreo Autónomo (Main Bot Loop).

Ejecuta el ciclo continuo de detección y arbitraje:
1. Escanea periódicamente los tickers configurados en MONITORED_TICKERS.
2. Consulta cotizaciones unificadas (PancakeSwap V3 on-chain + Yahoo Finance).
3. Evalúa la rentabilidad y viabilidad de cada oportunidad con strategy.py.
4. Si se emite señal BUY:
   - Construye la transacción de swap en PancakeSwap V3.
   - Simula la ejecución de forma segura con eth_call.
   - Registra el evento en signals_log.json.
5. Gestiona cierre controlado (graceful shutdown) y reporta métricas de la sesión.
"""

import logging
import os
import sys
import time
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Dict, Optional

from config import (
    DEFAULT_RECIPIENT,
    MONITORED_TICKERS,
    POLL_INTERVAL_SECONDS,
    SIGNALS_LOG_PATH,
    USDT_ADDRESS,
)
from data_fetcher import fetch_prices
from executor import (
    build_swap_transaction,
    log_signal_to_json,
    simulate_transaction,
)
from strategy import evaluate_opportunity

# ==============================================================================
# Configuración Centralizada de Logging
# ==============================================================================

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
DATE_FORMAT = "%H:%M:%S"

root_logger = logging.getLogger()
root_logger.setLevel(logging.DEBUG)

# 1. Handler para archivo rotativo (guarda DEBUG, INFO, WARNING, ERROR)
file_handler = RotatingFileHandler(
    "bot.log",
    maxBytes=5 * 1024 * 1024,  # 5 MB
    backupCount=3,
    encoding="utf-8",
)
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT))
root_logger.addHandler(file_handler)

# 2. Handler para consola (muestra solo INFO y superiores para no saturar)
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT))
root_logger.addHandler(console_handler)

logger = logging.getLogger("arbitrage_bot")


def _ensure_signal_log_file() -> None:
    """Crea el historial de señales vacío para que cada sesión tenga un registro."""
    path = Path(SIGNALS_LOG_PATH)
    if not path.exists():
        path.write_text("[]\n", encoding="utf-8")


# ==============================================================================
# Bucle Autónomo del Bot
# ==============================================================================

def run_bot(
    max_iterations: Optional[int] = None,
    poll_interval: Optional[int] = None,
) -> None:
    """Ejecuta el bucle principal del bot de arbitraje.

    Args:
        max_iterations: Número máximo opcional de ciclos a ejecutar (útil para pruebas).
                        Si es None, se ejecuta indefinidamente hasta KeyboardInterrupt.
        poll_interval: Tiempo de espera en segundos entre ciclos (por defecto POLL_INTERVAL_SECONDS).
    """
    interval = poll_interval if poll_interval is not None else POLL_INTERVAL_SECONDS
    session_start_time = datetime.now()
    session_start_ts = int(time.time())
    _ensure_signal_log_file()

    logger.info("=" * 70)
    logger.info("INICIANDO BOT DE ARBITRAJE - BNB CHAIN TOKENIZED STOCKS")
    logger.info("Tickers a monitorear : %s", MONITORED_TICKERS)
    logger.info("Intervalo de escaneo : %ss", interval)
    logger.info("Modo de ejecución    : %s", f"Limitado a {max_iterations} iteraciones" if max_iterations else "Continuo 24/7")
    logger.info("Archivo de log       : bot.log | Registro de señales: %s", SIGNALS_LOG_PATH)
    logger.info("=" * 70)

    # Estado compartido para control de enfriamiento (cooldown) por cada ticker
    state: Dict[str, Dict[str, Any]] = {ticker: {} for ticker in MONITORED_TICKERS}

    iteration_count = 0
    buy_signals_count = 0

    try:
        while True:
            iteration_count += 1
            logger.info(">>> Iniciando ciclo de escaneo #%d [%s]...", iteration_count, datetime.now().strftime("%H:%M:%S"))

            for ticker in MONITORED_TICKERS:
                try:
                    logger.debug("Consultando precios para %s...", ticker)
                    market_data = fetch_prices(ticker)

                    if not market_data:
                        logger.debug("No se obtuvieron datos para %s en este ciclo.", ticker)
                        continue

                    # Evaluar oportunidad con el motor de estrategia asimétrica
                    ticker_state = state.setdefault(ticker, {})
                    decision = evaluate_opportunity(market_data, ticker_state)

                    action = decision.get("action", "HOLD")

                    if action == "BUY":
                        buy_signals_count += 1
                        logger.info(
                            "*** OPORTUNIDAD DETECTADA [%s] *** Spread: %s%% | Razón: %s",
                            ticker,
                            decision.get("spread_pct"),
                            decision.get("reason"),
                        )

                        contract_addr = market_data.get("contract_address")
                        tx_data = None
                        simulation_res = None

                        if contract_addr:
                            # 1. Construir transacción de swap (PancakeSwap V3)
                            tx_data = build_swap_transaction(
                                bstock_contract=contract_addr,
                                usdt_contract=USDT_ADDRESS,
                                amount_bstock=Decimal("1.0"),
                                recipient=DEFAULT_RECIPIENT,
                                current_price_usdt=market_data.get("onchain_price_usdt"),
                            )

                            # 2. Simular con eth_call
                            if tx_data:
                                simulation_res = simulate_transaction(
                                    tx=tx_data,
                                    from_address=DEFAULT_RECIPIENT,
                                )

                        # 3. Registrar señal en signals_log.json
                        log_signal_to_json(
                            signal=decision,
                            tx_data=tx_data,
                            simulation=simulation_res,
                            filepath=SIGNALS_LOG_PATH,
                        )

                    else:
                        # Si es HOLD, registramos con nivel DEBUG para evitar spam en consola
                        logger.debug(
                            "Ticker %s: [%s] - %s (Spread: %s%%)",
                            ticker,
                            action,
                            decision.get("reason"),
                            decision.get("spread_pct"),
                        )

                except Exception as e:
                    logger.error("Error al procesar ticker %s en ciclo #%d: %s", ticker, iteration_count, e)

            logger.info("Ciclo #%d finalizado. Próximo escaneo en %ss.", iteration_count, interval)

            # Verificar si se alcanzó el límite de ciclos programado
            if max_iterations is not None and iteration_count >= max_iterations:
                logger.info("Se alcanzó el límite establecido de %d iteraciones. Deteniendo bucle.", max_iterations)
                break

            time.sleep(interval)

    except KeyboardInterrupt:
        logger.info("\nInterrupción manual (Ctrl+C) recibida. Realizando apagado limpio...")

    finally:
        session_end_time = datetime.now()
        duration = session_end_time - session_start_time

        print("\n" + "=" * 65)
        print("          RESUMEN DE SESIÓN DEL BOT DE ARBITRAJE")
        print("=" * 65)
        print(f"  Inicio de Sesión    : {session_start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"  Fin de Sesión       : {session_end_time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"  Duración Total      : {duration}")
        print(f"  Ciclos Completados  : {iteration_count}")
        print(f"  Señales BUY Emitidas: {buy_signals_count}")
        print(f"  Registro Guardado   : {SIGNALS_LOG_PATH}")
        print("=" * 65 + "\n")


if __name__ == "__main__":
    # Si se pasa un argumento numérico, usarlo como límite de iteraciones (ej. python main.py 2)
    max_iter = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else None
    run_bot(max_iterations=max_iter)
