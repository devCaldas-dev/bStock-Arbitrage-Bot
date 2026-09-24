"""
Módulo del Motor de Decisión y Estrategia de Arbitraje (Strategy Engine).

Evalúa las ineficiencias de precio detectadas entre el mercado on-chain de BSC
y las acciones tradicionales de EE.UU. considerando:
- Costos de transacción completos (gas en BSC, comisión DEX de PancakeSwap, slippage).
- Umbral mínimo de spread (MIN_SPREAD_PCT).
- Cálculo de ganancia neta estimada (net_profit_estimate).
- Periodo de enfriamiento (cooldown) para evitar señales duplicadas consecutivas.
"""

import logging
import time
from decimal import Decimal
from typing import Any, Dict, Optional

from config import (
    GAS_COST_USD,
    MIN_SPREAD_PCT,
    PANCAKE_FEE_PCT,
    SIGNAL_COOLDOWN_SECONDS,
    SLIPPAGE_PCT,
    TRADE_SIZE_USD,
)

logger = logging.getLogger(__name__)


def calculate_costs(
    trade_size_usd: Decimal = TRADE_SIZE_USD,
    fee_pct: Decimal = PANCAKE_FEE_PCT,
) -> Dict[str, Decimal]:
    """Calcula el desglose de costos totales asociados a una ejecución de arbitraje.

    Componentes:
    - Gas: Costo de red estimado en BSC.
    - DEX Fee: Comisión cobrada por el pool de PancakeSwap (ej. 0.25%).
    - Slippage: Costo estimado por deslizamiento de precio / impacto en liquidez.

    Args:
        trade_size_usd: Monto nocional de la operación en USD.
        fee_pct: Porcentaje de comisión del pool DEX.

    Returns:
        Dict con los componentes de costo en USD:
        {
            "gas": Decimal,
            "dex_fee": Decimal,
            "slippage": Decimal,
            "total": Decimal
        }
    """
    gas = GAS_COST_USD
    dex_fee = trade_size_usd * (fee_pct / Decimal("100"))
    slippage = trade_size_usd * (SLIPPAGE_PCT / Decimal("100"))
    total = gas + dex_fee + slippage

    logger.debug(
        "Costos calculados para trade de $%s USD: Gas=$%s, Fee=$%s, Slippage=$%s, Total=$%s",
        trade_size_usd,
        gas,
        dex_fee,
        slippage,
        total,
    )

    return {
        "gas": gas,
        "dex_fee": dex_fee,
        "slippage": slippage,
        "total": total,
    }


def calculate_net_profit(
    spread_usd: Decimal,
    trade_size_usd: Decimal,
    costs: Dict[str, Decimal],
    underlying_price: Optional[Decimal] = None,
) -> Optional[Decimal]:
    """Calcula la ganancia neta esperada para arbitraje de prima positiva (Mint & Sell).

    Mecanismo de Arbitraje:
    Acuñar (mint) el bStock al precio de la acción real subyacente (Wall Street)
    y venderlo en el DEX al precio on-chain más alto.

    Fórmula:
        gross_profit = spread_usd * (trade_size_usd / underlying_price)
        net_profit = gross_profit - costs["total"]

    NOTA: Solo aplica para spreads positivos (bStock cotizando con prima).
    Para spreads negativos (descuento), retorna None ya que la redención off-chain
    no está automatizada en el MVP.

    Args:
        spread_usd: Diferencia de precio (onchain_price - underlying_price).
        trade_size_usd: Tamaño del trade en USD.
        costs: Diccionario de costos obtenido de calculate_costs.
        underlying_price: Precio de la acción subyacente en Wall Street. Si es None,
                          se toma un valor por defecto de $100 para evitar división por cero.

    Returns:
        Decimal con el beneficio neto estimado o None si el spread es negativo o nulo.
    """
    if spread_usd <= Decimal("0"):
        logger.debug("Spread negativo o nulo (%s USD). No aplica cálculo de net_profit de emisión.", spread_usd)
        return None

    price = (
        underlying_price
        if (underlying_price is not None and underlying_price > Decimal("0"))
        else Decimal("100")
    )

    # Cantidad de bStocks que se pueden acuñar con trade_size_usd al precio del subyacente
    shares_count = trade_size_usd / price
    gross_profit = spread_usd * shares_count
    total_costs = costs.get("total", Decimal("0"))
    net_profit = gross_profit - total_costs

    logger.debug(
        "Prima positiva: Gross profit=$%s, Costos=$%s -> Net profit=$%s",
        gross_profit,
        total_costs,
        net_profit,
    )

    return net_profit


def evaluate_opportunity(
    data: Optional[Dict[str, Any]],
    state: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Evalúa los datos de mercado y decide la acción comercial óptima (BUY o HOLD).

    Asimetría en el Arbitraje de bStocks:
    1. PRIMA POSITIVA (bStock > acción real):
       - Mecanismo: Acuñar bStock con USDC al precio del emisor (subyacente) y vender en DEX.
       - Automatizable: SÍ.
       - Decisión: Emite señal BUY si net_profit > 0 tras costos.
    2. DESCUENTO (bStock < acción real):
       - Mecanismo: Comprar bStock en DEX a descuento y redimir por USDC vía emisor.
       - Automatizable: NO (requiere proceso KYC y liquidación off-chain con el emisor).
       - Decisión: Emite señal HOLD explicando la limitación de redención.

    Reglas de Decisión:
    1. Si underlying_price o onchain_price es None -> HOLD ("Sin precio subyacente").
    2. Si spread_pct >= MIN_SPREAD_PCT -> Evaluar COMPRA de bStock (BUY).
       - Si net_profit > 0 -> BUY.
       - Si no -> HOLD ("Spread positivo pero no cubre costos").
    3. Si spread_pct <= -MIN_SPREAD_PCT -> HOLD con razón:
       "Descuento detectado pero no ejecutable sin acceso al mecanismo de redención del emisor".
    4. Si abs(spread_pct) < MIN_SPREAD_PCT -> HOLD ("Spread dentro de rango normal").
    5. Cooldown: Si la última señal del mismo tipo fue hace < SIGNAL_COOLDOWN_SECONDS -> HOLD.

    Args:
        data: Diccionario retornado por fetch_prices().
        state: Diccionario mutable con el estado de señales previas
               (e.g., {"last_signal_type": str, "last_signal_timestamp": int}).

    Returns:
        Dict con la estructura requerida:
        {
            "action": "BUY" | "HOLD",
            "ticker": str,
            "spread_pct": Optional[Decimal],
            "spread_usd": Optional[Decimal],
            "net_profit_estimate": Optional[Decimal],
            "costs": Optional[Dict[str, Decimal]],
            "reason": str,
            "timestamp": int
        }
    """
    now = int(time.time())
    if state is None:
        state = {}

    ticker = (
        data.get("ticker") or data.get("symbol") or "UNKNOWN"
        if isinstance(data, dict)
        else "UNKNOWN"
    )

    # 1. Validación de datos mínimos requeridos
    if not data or data.get("underlying_price") is None:
        return {
            "action": "HOLD",
            "ticker": ticker,
            "spread_pct": None,
            "spread_usd": None,
            "net_profit_estimate": None,
            "costs": None,
            "reason": "Sin precio subyacente",
            "timestamp": now,
        }

    if data.get("onchain_price") is None and data.get("onchain_price_per_share") is None:
        return {
            "action": "HOLD",
            "ticker": ticker,
            "spread_pct": None,
            "spread_usd": None,
            "net_profit_estimate": None,
            "costs": None,
            "reason": "Sin precio on-chain",
            "timestamp": now,
        }

    spread_pct: Decimal = data.get("spread_pct")
    spread_usd: Decimal = data.get("spread_usd")

    # Si por alguna razón no vinieran calculados, recalcular
    underlying_price: Decimal = data["underlying_price"]
    onchain_price: Decimal = data.get("onchain_price_per_share") or data.get("onchain_price")
    if spread_usd is None:
        spread_usd = onchain_price - underlying_price
    if spread_pct is None and underlying_price > Decimal("0"):
        spread_pct = (spread_usd / underlying_price) * Decimal("100")

    # 2. Comprobar si el spread supera el umbral mínimo (asimetría prima vs descuento)
    if spread_pct >= MIN_SPREAD_PCT:
        potential_action = "BUY"
    elif spread_pct <= -MIN_SPREAD_PCT:
        # Arbitraje de descuento: no ejecutable en el MVP
        reason = "Descuento detectado pero no ejecutable sin acceso al mecanismo de redención del emisor"
        logger.info("Descuento detectado para %s (Spread: %.2f%%). Emite HOLD.", ticker, spread_pct)
        return {
            "action": "HOLD",
            "ticker": ticker,
            "spread_pct": spread_pct,
            "spread_usd": spread_usd,
            "net_profit_estimate": None,
            "costs": None,
            "reason": reason,
            "timestamp": now,
        }
    else:
        return {
            "action": "HOLD",
            "ticker": ticker,
            "spread_pct": spread_pct,
            "spread_usd": spread_usd,
            "net_profit_estimate": None,
            "costs": None,
            "reason": "Spread dentro de rango normal",
            "timestamp": now,
        }

    # 3. Comprobar periodo de enfriamiento (cooldown) para BUY
    last_signal_type = state.get("last_signal_type")
    last_signal_timestamp = state.get("last_signal_timestamp", 0)

    if last_signal_type == potential_action and (now - last_signal_timestamp) < SIGNAL_COOLDOWN_SECONDS:
        remaining = SIGNAL_COOLDOWN_SECONDS - (now - last_signal_timestamp)
        logger.info(
            "Cooldown activo para señal %s de %s (%ss restantes).",
            potential_action,
            ticker,
            remaining,
        )
        return {
            "action": "HOLD",
            "ticker": ticker,
            "spread_pct": spread_pct,
            "spread_usd": spread_usd,
            "net_profit_estimate": None,
            "costs": None,
            "reason": f"Cooldown activo para {potential_action} ({remaining}s restantes)",
            "timestamp": now,
        }

    # 4. Calcular costos y rentabilidad neta (basado en precio del subyacente para mint)
    costs = calculate_costs(TRADE_SIZE_USD, PANCAKE_FEE_PCT)
    net_profit = calculate_net_profit(spread_usd, TRADE_SIZE_USD, costs, underlying_price)

    if net_profit is not None and net_profit > Decimal("0"):
        # Registrar señal en el estado para control de cooldown
        state["last_signal_type"] = potential_action
        state["last_signal_timestamp"] = now

        reason = (
            f"Oportunidad de {potential_action} rentable detectada "
            f"(Spread: {spread_pct:.2f}%, Ganancia neta est.: ${net_profit:.2f} USD)"
        )
        logger.info("SEÑAL EMITIDA [%s]: %s", potential_action, reason)

        return {
            "action": potential_action,
            "ticker": ticker,
            "spread_pct": spread_pct,
            "spread_usd": spread_usd,
            "net_profit_estimate": net_profit,
            "costs": costs,
            "reason": reason,
            "timestamp": now,
        }
    else:
        reason = "Spread positivo pero no cubre costos"
        logger.info("Señal retenida para %s: %s", ticker, reason)
        return {
            "action": "HOLD",
            "ticker": ticker,
            "spread_pct": spread_pct,
            "spread_usd": spread_usd,
            "net_profit_estimate": net_profit,
            "costs": costs,
            "reason": reason,
            "timestamp": now,
        }


if __name__ == "__main__":
    from data_fetcher import fetch_prices

    print("==============================================================================")
    print(">> EJECUTANDO EVALUACIÓN DE ESTRATEGIA EN VIVO PARA TSLA")
    print("==============================================================================")

    # 1. Obtener datos de mercado
    market_data = fetch_prices("TSLA")

    # 2. Evaluar oportunidad
    bot_state: Dict[str, Any] = {}
    decision = evaluate_opportunity(market_data, bot_state)

    # 3. Imprimir resultado formateado
    print("\n" + "=" * 60)
    print("        REPORTE DEL MOTOR DE DECISIÓN (STRATEGY)")
    print("=" * 60)
    print(f"  Ticker                  : {decision['ticker']}")
    print(f"  Acción Recomendada      : [{decision['action']}]")
    print(f"  Motivo / Razón          : {decision['reason']}")
    if decision['spread_pct'] is not None:
        print(f"  Spread Porcentual       : {decision['spread_pct']:.4f}%")
        print(f"  Spread en USD           : ${decision['spread_usd']:.4f}")
    if decision['net_profit_estimate'] is not None:
        print(f"  Beneficio Neto Estimado : ${decision['net_profit_estimate']:.4f} USD")
    if decision['costs'] is not None:
        print(f"  Costos Estimados (Trade ${TRADE_SIZE_USD} USD):")
        print(f"    - Gas BSC             : ${decision['costs']['gas']:.2f}")
        print(f"    - DEX Fee             : ${decision['costs']['dex_fee']:.2f}")
        print(f"    - Slippage            : ${decision['costs']['slippage']:.2f}")
        print(f"    - Total Costos        : ${decision['costs']['total']:.2f}")
    print(f"  Timestamp Evaluación    : {decision['timestamp']}")
    print("=" * 60 + "\n")
