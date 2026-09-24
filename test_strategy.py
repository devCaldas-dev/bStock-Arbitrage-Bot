"""
Suite de Pruebas para strategy.py con lógica de arbitraje asimétrico.

Verifica:
1. Cálculo exacto de costos (Gas BSC, Comisión DEX, Slippage).
2. Cálculo de ganancia neta (Mint & Sell):
   - Retorna beneficio positivo para spreads altos positivos.
   - Retorna None para spreads negativos (descuento).
   - Retorna beneficio negativo si el spread no cubre costos.
3. Evaluación de oportunidades:
   - BUY para prima positiva (+2%) con ganancia neta > 0.
   - HOLD (no SELL) para descuento (-2%) debido a la imposibilidad de redimir off-chain en el MVP.
   - HOLD para spreads dentro del rango normal (< 1.5%).
   - HOLD si falta precio del subyacente.
   - Cooldown impidiendo señales duplicadas consecutivas.
4. Prueba en vivo evaluando la oportunidad actual para TSLA.
"""

import logging
import sys
import unittest
from decimal import Decimal

from config import (
    GAS_COST_USD,
    MIN_SPREAD_PCT,
    PANCAKE_FEE_PCT,
    SIGNAL_COOLDOWN_SECONDS,
    SLIPPAGE_PCT,
    TRADE_SIZE_USD,
)
from strategy import (
    calculate_costs,
    calculate_net_profit,
    evaluate_opportunity,
)

# Configuración de logging para pruebas
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("test_strategy")


class TestStrategy(unittest.TestCase):
    """Pruebas unitarias de la lógica del motor de estrategia asimétrica."""

    def test_calculate_costs(self):
        """Verifica cálculo de costos con valores conocidos."""
        trade_size = Decimal("1000")
        fee_pct = Decimal("0.25")  # 0.25%
        costs = calculate_costs(trade_size, fee_pct)

        expected_gas = GAS_COST_USD  # 0.20
        expected_dex_fee = Decimal("1000") * (Decimal("0.25") / Decimal("100"))  # 2.50
        expected_slippage = Decimal("1000") * (Decimal("0.10") / Decimal("100"))  # 1.00
        expected_total = expected_gas + expected_dex_fee + expected_slippage  # 3.70

        self.assertEqual(costs["gas"], expected_gas)
        self.assertEqual(costs["dex_fee"], expected_dex_fee)
        self.assertEqual(costs["slippage"], expected_slippage)
        self.assertEqual(costs["total"], expected_total)
        self.assertEqual(costs["total"], Decimal("3.70"))

    def test_calculate_net_profit_positive(self):
        """Verifica que un spread positivo alto resulte en ganancia neta positiva para mint & sell."""
        spread_usd = Decimal("10.00")
        trade_size = Decimal("1000")
        costs = {"total": Decimal("3.70")}
        underlying_price = Decimal("100.00")

        # gross_profit = 10.00 * (1000 / 100) = 100.00
        # net_profit = 100.00 - 3.70 = 96.30
        net_profit = calculate_net_profit(spread_usd, trade_size, costs, underlying_price)
        self.assertIsNotNone(net_profit)
        self.assertGreater(net_profit, Decimal("0"))
        self.assertEqual(net_profit, Decimal("96.30"))

    def test_calculate_net_profit_negative_returns_none(self):
        """Verifica que un spread negativo (descuento) retorne None al no ser automatizable en MVP."""
        spread_usd = Decimal("-2.50")
        trade_size = Decimal("1000")
        costs = {"total": Decimal("3.70")}
        underlying_price = Decimal("100.00")

        net_profit = calculate_net_profit(spread_usd, trade_size, costs, underlying_price)
        self.assertIsNone(net_profit)

    def test_calculate_net_profit_low_spread_negative(self):
        """Verifica que un spread positivo bajo no cubra costos y resulte en ganancia neta negativa."""
        spread_usd = Decimal("0.10")
        trade_size = Decimal("1000")
        costs = {"total": Decimal("3.70")}
        underlying_price = Decimal("100.00")

        # gross_profit = 0.10 * (1000 / 100) = 1.00
        # net_profit = 1.00 - 3.70 = -2.70
        net_profit = calculate_net_profit(spread_usd, trade_size, costs, underlying_price)
        self.assertIsNotNone(net_profit)
        self.assertLess(net_profit, Decimal("0"))
        self.assertEqual(net_profit, Decimal("-2.70"))

    def test_evaluate_opportunity_buy_still_works(self):
        """Verifica que un spread positivo de +2% (> 1.5%) rentable active señal BUY."""
        market_data = {
            "ticker": "TSLA",
            "underlying_price": Decimal("100.00"),
            "onchain_price": Decimal("102.00"),
            "spread_usd": Decimal("2.00"),
            "spread_pct": Decimal("2.00"),
        }
        state = {}

        decision = evaluate_opportunity(market_data, state)
        self.assertEqual(decision["action"], "BUY")
        self.assertEqual(decision["ticker"], "TSLA")
        self.assertIsNotNone(decision["net_profit_estimate"])
        self.assertGreater(decision["net_profit_estimate"], Decimal("0"))
        self.assertEqual(state.get("last_signal_type"), "BUY")

    def test_evaluate_opportunity_sell_now_holds(self):
        """Verifica que un descuento de -2% (< -1.5%) retorne HOLD con explicación de no ejecutabilidad."""
        market_data = {
            "ticker": "TSLA",
            "underlying_price": Decimal("100.00"),
            "onchain_price": Decimal("98.00"),
            "spread_usd": Decimal("-2.00"),
            "spread_pct": Decimal("-2.00"),
        }
        state = {}

        decision = evaluate_opportunity(market_data, state)
        self.assertEqual(decision["action"], "HOLD")
        self.assertIsNone(decision["net_profit_estimate"])
        self.assertIn("redención del emisor", decision["reason"].lower())

    def test_evaluate_opportunity_hold_small_spread(self):
        """Verifica que un spread de 0.5% (< 1.5%) resulte en HOLD por estar en rango normal."""
        market_data = {
            "ticker": "TSLA",
            "underlying_price": Decimal("100.00"),
            "onchain_price": Decimal("100.50"),
            "spread_usd": Decimal("0.50"),
            "spread_pct": Decimal("0.50"),
        }
        state = {}

        decision = evaluate_opportunity(market_data, state)
        self.assertEqual(decision["action"], "HOLD")
        self.assertIn("rango normal", decision["reason"].lower())

    def test_evaluate_opportunity_hold_no_underlying(self):
        """Verifica que si underlying_price es None, se retorne HOLD con razón clara."""
        market_data = {
            "ticker": "TSLA",
            "underlying_price": None,
            "onchain_price": Decimal("102.00"),
            "spread_usd": None,
            "spread_pct": None,
        }
        state = {}

        decision = evaluate_opportunity(market_data, state)
        self.assertEqual(decision["action"], "HOLD")
        self.assertEqual(decision["reason"], "Sin precio subyacente")

    def test_cooldown_prevents_duplicate_signal(self):
        """Verifica que dos llamadas consecutivas respeten el cooldown (la 2da es HOLD)."""
        market_data = {
            "ticker": "TSLA",
            "underlying_price": Decimal("100.00"),
            "onchain_price": Decimal("105.00"),
            "spread_usd": Decimal("5.00"),
            "spread_pct": Decimal("5.00"),
        }
        state = {}

        # Primera llamada: debe generar señal BUY
        first_decision = evaluate_opportunity(market_data, state)
        self.assertEqual(first_decision["action"], "BUY")

        # Segunda llamada inmediata: debe retenerse por cooldown -> HOLD
        second_decision = evaluate_opportunity(market_data, state)
        self.assertEqual(second_decision["action"], "HOLD")
        self.assertIn("cooldown activo", second_decision["reason"].lower())


def run_live_test():
    """Ejecuta la evaluación en vivo combinando data_fetcher y strategy."""
    from data_fetcher import fetch_prices

    print("\n" + "=" * 80)
    print(">> EJECUCIÓN EN VIVO: fetch_prices('TSLA') + evaluate_opportunity (ASIMÉTRICA)")
    print("=" * 80)

    market_data = fetch_prices("TSLA")

    if not market_data:
        print("[ERROR] fetch_prices retornó None.")
        return

    state = {}
    decision = evaluate_opportunity(market_data, state)

    print("\n------------------------------------------------------------")
    print("           REPORTE DE EVALUACIÓN EN VIVO (TSLA)")
    print("------------------------------------------------------------")
    print(f"  Ticker Subyacente       : {decision['ticker']}")
    print(f"  Acción Emitida          : [{decision['action']}]")
    print(f"  Razón                   : {decision['reason']}")
    print(f"  Precio Subyacente (USD) : ${market_data.get('underlying_price')}")
    print(f"  Precio On-Chain (USDT)  : ${market_data.get('onchain_price')}")
    print(f"  DEX / Protocolo         : {market_data.get('dex')}")
    print(f"  Spread USD              : ${decision['spread_usd']}")
    print(f"  Spread Porcentual       : {decision['spread_pct']:.4f}%")

    if decision['net_profit_estimate'] is not None:
        print(f"  Net Profit Estimate     : ${decision['net_profit_estimate']:.4f} USD")
    else:
        print(f"  Net Profit Estimate     : None (No aplicable / no ejecutable)")

    if decision['costs'] is not None:
        print(f"  Costos Totales          : ${decision['costs']['total']:.2f} USD")
    else:
        costs = calculate_costs(TRADE_SIZE_USD, PANCAKE_FEE_PCT)
        print(f"  Costos Base Estimados   : ${costs['total']:.2f} USD (Gas: ${costs['gas']}, Fee: ${costs['dex_fee']}, Slip: ${costs['slippage']})")

    print(f"  Timestamp               : {decision['timestamp']}")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    print("==============================================================================")
    print(" 1. EJECUCIÓN DE PRUEBAS UNITARIAS DE ESTRATEGIA (test_strategy.py)          ")
    print("==============================================================================")
    suite = unittest.TestLoader().loadTestsFromTestCase(TestStrategy)
    runner = unittest.TextTestRunner(verbosity=2)
    test_result = runner.run(suite)

    if not test_result.wasSuccessful():
        print("Las pruebas unitarias de estrategia fallaron.")
        sys.exit(1)

    print("\n==============================================================================")
    print(" 2. EJECUCIÓN DE EVALUACIÓN EN VIVO (TSLA)                                   ")
    print("==============================================================================")
    run_live_test()
