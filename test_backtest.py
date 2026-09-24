"""Pruebas unitarias del backtest con datos historicos simulados en memoria."""

import json
import tempfile
import unittest
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

import backtest


class TestBacktest(unittest.TestCase):
    def test_backtest_imports(self):
        """Verifica que el modulo exponga la interfaz publica del backtest."""
        self.assertTrue(callable(backtest.run_backtest))
        self.assertTrue(callable(backtest.print_summary))
        self.assertTrue(callable(backtest.fetch_underlying_history))

    @patch("backtest.fetch_current_onchain_price")
    @patch("backtest.fetch_underlying_history")
    def test_backtest_generates_json_with_structure(self, mock_history, mock_onchain):
        """Genera JSON con periodo, senales y resumen sin usar red."""
        today = date.today()
        mock_history.return_value = [
            (today - timedelta(days=index), Decimal("100"))
            for index in range(6, -1, -1)
        ]
        mock_onchain.return_value = (
            Decimal("105"),
            "current_onchain_plus_synthetic_variation",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = f"{temp_dir}/backtest.json"
            result = backtest.run_backtest(
                days=7,
                tickers=["TSLA"],
                output_path=output_path,
            )
            with open(output_path, "r", encoding="utf-8") as handle:
                saved = json.load(handle)

        self.assertEqual(result["tickers"], ["TSLA"])
        self.assertEqual(result["summary"]["total_days"], 7)
        self.assertEqual(len(result["signals_by_day"]), 7)
        self.assertEqual(saved["summary"], result["summary"])
        self.assertIn("spread_pct", saved["signals_by_day"][0])
        self.assertIn("action", saved["signals_by_day"][0])
        self.assertIn("simulation_note", saved["signals_by_day"][0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
