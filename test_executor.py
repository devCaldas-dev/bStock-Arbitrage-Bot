"""
Suite de Pruebas para executor.py.

Verifica:
1. test_build_swap_transaction_structure: Dict con to, data, value, gas, etc.
2. test_amount_conversion_to_uint256: Conversión matemática de Decimal a uint256 (18 decimales).
3. test_simulate_transaction_mock: Simulación mediante mock de eth_call.
4. test_log_signal_creates_file: Creación y persistencia estructurada en JSON.
5. Test en vivo: Construcción de transacción con datos reales de TSLAB mostrando calldata.
"""

import json
import logging
import os
import re
import sys
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch, MagicMock

from config import (
    PANCAKE_V3_SWAP_ROUTER,
    USDT_ADDRESS,
)
from executor import (
    build_swap_transaction,
    log_signal_to_json,
    simulate_transaction,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("test_executor")

KNOWN_TSLAB_CONTRACT = "0x5b1910eaad6450e50f816082aa078c41f10c292f"
TEST_SIGNALS_JSON = "test_signals_temp.json"


class TestExecutor(unittest.TestCase):
    """Pruebas unitarias para el módulo executor."""

    def test_main_imports_and_address_constants(self):
        """Verifica que main importe Decimal y exponga direcciones válidas."""
        import main

        address_pattern = re.compile(r"^0x[0-9a-fA-F]{40}$")
        self.assertIsInstance(main.USDT_ADDRESS, str)
        self.assertIsInstance(main.DEFAULT_RECIPIENT, str)
        self.assertRegex(main.USDT_ADDRESS, address_pattern)
        self.assertRegex(main.DEFAULT_RECIPIENT, address_pattern)
        self.assertTrue(callable(main.build_swap_transaction))
        self.assertTrue(callable(main.simulate_transaction))
        self.assertTrue(callable(main.log_signal_to_json))
        self.assertTrue(callable(main.evaluate_opportunity))
        self.assertTrue(callable(main.fetch_prices))

    def tearDown(self):
        # Limpiar archivo temporal de pruebas
        temp_file = Path(TEST_SIGNALS_JSON)
        if temp_file.exists():
            try:
                temp_file.unlink()
            except Exception:
                pass

    def test_build_swap_transaction_structure(self):
        """Verifica que build_swap_transaction retorne los campos to, data, value, gas, amount_in, etc."""
        tx = build_swap_transaction(
            bstock_contract=KNOWN_TSLAB_CONTRACT,
            usdt_contract=USDT_ADDRESS,
            amount_bstock=Decimal("1.0"),
            recipient="0x0000000000000000000000000000000000000001",
            fee_tier=2500,
            slippage_pct=Decimal("0.5"),
            current_price_usdt=Decimal("380.00"),
        )

        self.assertIsNotNone(tx)
        self.assertIn("to", tx)
        self.assertIn("data", tx)
        self.assertIn("value", tx)
        self.assertIn("gas", tx)
        self.assertIn("amount_in", tx)
        self.assertIn("amount_out_min", tx)
        self.assertIn("description", tx)

        self.assertEqual(tx["to"].lower(), PANCAKE_V3_SWAP_ROUTER.lower())
        self.assertEqual(tx["value"], 0)
        self.assertTrue(tx["data"].startswith("0x414bf389"))  # exactInputSingle selector

    def test_amount_conversion_to_uint256(self):
        """Verifica la conversión exacta de Decimal a entero uint256 de 18 decimales."""
        amount_bstock = Decimal("2.5")
        current_price = Decimal("300.00")
        slippage_pct = Decimal("1.0")  # 1% slippage -> factor 0.99

        tx = build_swap_transaction(
            bstock_contract=KNOWN_TSLAB_CONTRACT,
            amount_bstock=amount_bstock,
            current_price_usdt=current_price,
            slippage_pct=slippage_pct,
        )

        self.assertIsNotNone(tx)
        # amount_in = 2.5 * 10^18 = 2500000000000000000
        expected_amount_in = int(Decimal("2.5") * Decimal(10**18))
        self.assertEqual(tx["amount_in"], expected_amount_in)

        # expected_out = 2.5 * 300 = 750 USDT. Con 1% slippage: 750 * 0.99 = 742.5 USDT
        expected_min_out = int(Decimal("742.5") * Decimal(10**18))
        self.assertEqual(tx["amount_out_min"], expected_min_out)

    @patch("executor.w3.eth.call")
    @patch("executor.w3.eth.estimate_gas")
    def test_simulate_transaction_mock(self, mock_estimate, mock_call):
        """Verifica que simulate_transaction procese exitosamente una llamada simulada."""
        mock_call.return_value = b"\x00" * 32
        mock_estimate.return_value = 185000

        tx_dummy = {
            "to": PANCAKE_V3_SWAP_ROUTER,
            "data": "0x414bf389",
            "value": 0,
        }
        res = simulate_transaction(tx_dummy, from_address="0x0000000000000000000000000000000000000001")

        self.assertTrue(res["success"])
        self.assertIsNone(res["revert_reason"])
        self.assertEqual(res["gas_estimate"], 185000)

    def test_log_signal_creates_file(self):
        """Verifica que log_signal_to_json cree el archivo JSON y almacene los campos requeridos."""
        signal_dummy = {
            "timestamp": 1790000000,
            "ticker": "TSLA",
            "action": "BUY",
            "spread_pct": Decimal("2.15"),
            "spread_usd": Decimal("8.10"),
            "net_profit_estimate": Decimal("18.50"),
            "reason": "Test de emisión",
        }
        tx_dummy = {
            "to": PANCAKE_V3_SWAP_ROUTER,
            "amount_in": 10**18,
            "amount_out_min": 375 * 10**18,
        }
        sim_dummy = {"success": True, "revert_reason": None}

        # Guardar en archivo temporal
        log_signal_to_json(signal_dummy, tx_dummy, sim_dummy, filepath=TEST_SIGNALS_JSON)

        path = Path(TEST_SIGNALS_JSON)
        self.assertTrue(path.exists())

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["ticker"], "TSLA")
        self.assertEqual(data[0]["action"], "BUY")
        self.assertEqual(data[0]["tx_data"]["to"], PANCAKE_V3_SWAP_ROUTER)


def run_live_test():
    """Ejecuta la construcción de una transacción real con TSLAB y muestra el calldata."""
    print("\n" + "=" * 80)
    print(">> EJECUCIÓN EN VIVO: build_swap_transaction con datos reales de TSLAB")
    print("=" * 80)

    from data_fetcher import fetch_prices

    prices = fetch_prices("TSLA")
    if not prices or not prices.get("contract_address"):
        print("[ERROR] No se pudo obtener contrato de TSLAB.")
        return

    bstock_contract = prices["contract_address"]
    current_price = prices.get("onchain_price_usdt") or prices.get("onchain_price")

    print(f"  Contrato bStock : {bstock_contract}")
    print(f"  Precio Spot USDT: {current_price}")

    tx = build_swap_transaction(
        bstock_contract=bstock_contract,
        usdt_contract=USDT_ADDRESS,
        amount_bstock=Decimal("1.0"),
        current_price_usdt=current_price,
    )

    if tx:
        print("\n  [OK] Transacción Construida:")
        print(f"       Router Destination (to) : {tx['to']}")
        print(f"       AmountIn (wei)          : {tx['amount_in']}")
        print(f"       AmountOutMinimum (wei)  : {tx['amount_out_min']}")
        print(f"       Gas Limit               : {tx['gas']}")
        print(f"       Descripción             : {tx['description']}")
        print(f"       Calldata Selector       : {tx['data'][:10]}")
        print(f"       Calldata Completo (hex) : {tx['data'][:66]}... (Longitud: {len(tx['data'])} caracteres)")
    else:
        print("  [ERROR] build_swap_transaction retornó None.")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    print("==============================================================================")
    print(" 1. EJECUCIÓN DE PRUEBAS UNITARIAS DE EXECUTOR (test_executor.py)            ")
    print("==============================================================================")
    suite = unittest.TestLoader().loadTestsFromTestCase(TestExecutor)
    runner = unittest.TextTestRunner(verbosity=2)
    test_result = runner.run(suite)

    if not test_result.wasSuccessful():
        print("Las pruebas unitarias de executor fallaron.")
        sys.exit(1)

    print("\n==============================================================================")
    print(" 2. EJECUCIÓN DE PRUEBA EN VIVO: CONSTRUCCIÓN DE SWAP CON TSLAB              ")
    print("==============================================================================")
    run_live_test()
