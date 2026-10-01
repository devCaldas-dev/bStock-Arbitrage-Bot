"""
test_live_flow.py — Tests unitarios (mockeados) para las funciones de flujo LIVE
añadidas en los Commits 1-2:

  executor.py:
    - build_api_swap_transaction  (orquestación quote → swap vía Binance API)
    - build_approve_transaction   (calldata ERC-20 approve vía Binance API)
    - sign_transaction            (firma local con clave privada de entorno)
    - broadcast_signed_transaction (broadcast vía eth_sendRawTransaction)
    - verify_transaction          (consulta de recibo on-chain)

  binance_web3_api.BinanceWeb3API:
    - get_aggregated_quote
    - build_swap_transaction      (método de la clase, no el del executor)
    - quote_and_build_swap
    - get_erc20_approve_transaction
    - get_gas_price
    - get_transaction_detail
    - get_token_balances

Todos los tests son unitarios (no hacen llamadas de red ni requieren fondos).
"""

import os
import unittest
from decimal import Decimal
from unittest.mock import MagicMock, patch

from binance_web3_api import BinanceWeb3API
from executor import (
    build_api_swap_transaction,
    build_approve_transaction,
    broadcast_signed_transaction,
    sign_transaction,
    verify_transaction,
)

TSLAB = "0x5b1910eaad6450e50f816082aa078c41f10c292f"
USDT = "0x55d398326f99059fF775485246999027B3197955"
WALLET = "0x0000000000000000000000000000000000000001"

# ---------------------------------------------------------------------------
# Tests para BinanceWeb3API — endpoints de Trading API (Commit 2)
# ---------------------------------------------------------------------------


class TestBinanceWeb3APITradingEndpoints(unittest.TestCase):
    """Verifica que los nuevos endpoints de la Trading API armen la URL correcta
    y devuelvan el campo `data` del payload."""

    def _mock_response(self, data_value):
        """Construye un mock de requests.Response con payload estándar de Binance."""
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {
            "code": 0,
            "msg": "success",
            "data": data_value,
            "success": True,
        }
        return resp

    @patch("binance_web3_api.requests.request")
    def test_get_aggregated_quote_returns_data(self, mock_req):
        """get_aggregated_quote devuelve el campo data cuando la API responde OK."""
        expected = [{"quoteId": "q-001", "toTokenAmount": "367500000"}]
        mock_req.return_value = self._mock_response(expected)

        api = BinanceWeb3API(api_key="k", api_secret="s")
        result = api.get_aggregated_quote(
            chain_id="56",
            amount=10**18,
            from_token=TSLAB,
            to_token=USDT,
            slippage="0.5",
            wallet_address=WALLET,
        )

        self.assertEqual(result, expected)
        call_url = mock_req.call_args.args[1]
        self.assertIn("aggregator/quote", call_url)
        self.assertIn("binanceChainId=56", call_url)

    @patch("binance_web3_api.requests.request")
    def test_build_swap_transaction_api_returns_data(self, mock_req):
        """BinanceWeb3API.build_swap_transaction devuelve el campo data del swap."""
        expected = {"to": "0xRouter", "data": "0xcalldata", "gas": "300000"}
        mock_req.return_value = self._mock_response(expected)

        api = BinanceWeb3API(api_key="k", api_secret="s")
        result = api.build_swap_transaction(
            chain_id="56",
            amount=10**18,
            from_token=TSLAB,
            to_token=USDT,
            wallet_address=WALLET,
            quote_id="q-001",
        )

        self.assertEqual(result, expected)
        call_url = mock_req.call_args.args[1]
        self.assertIn("aggregator/swap", call_url)

    @patch("binance_web3_api.requests.request")
    def test_quote_and_build_swap_returns_data(self, mock_req):
        """quote_and_build_swap devuelve el campo data sin paso intermedio de quoteId."""
        expected = {"to": "0xRouter", "data": "0xcalldata2", "gas": "250000"}
        mock_req.return_value = self._mock_response(expected)

        api = BinanceWeb3API(api_key="k", api_secret="s")
        result = api.quote_and_build_swap(
            chain_id="56",
            amount=10**18,
            from_token=TSLAB,
            to_token=USDT,
            wallet_address=WALLET,
        )

        self.assertEqual(result, expected)
        call_url = mock_req.call_args.args[1]
        self.assertIn("quote-and-swap", call_url)

    @patch("binance_web3_api.requests.request")
    def test_get_erc20_approve_transaction_returns_data(self, mock_req):
        """get_erc20_approve_transaction devuelve calldata de approve ERC-20."""
        expected = {"to": TSLAB, "data": "0xapprovedata", "value": "0"}
        mock_req.return_value = self._mock_response(expected)

        api = BinanceWeb3API(api_key="k", api_secret="s")
        result = api.get_erc20_approve_transaction(
            chain_id="56",
            token_contract=TSLAB,
            approve_amount=10**18,
        )

        self.assertEqual(result, expected)
        call_url = mock_req.call_args.args[1]
        self.assertIn("approve-transaction", call_url)

    @patch("binance_web3_api.requests.request")
    def test_get_gas_price_returns_data(self, mock_req):
        """get_gas_price devuelve el campo data con el gasPrice actual."""
        expected = {"gasPrice": "3000000000", "chainId": "56"}
        mock_req.return_value = self._mock_response(expected)

        api = BinanceWeb3API(api_key="k", api_secret="s")
        result = api.get_gas_price(chain_id="56")

        self.assertEqual(result, expected)
        call_url = mock_req.call_args.args[1]
        self.assertIn("gas-price", call_url)

    @patch("binance_web3_api.requests.request")
    def test_get_transaction_detail_returns_data(self, mock_req):
        """get_transaction_detail devuelve el campo data del recibo on-chain."""
        tx_hash = "0x" + "a" * 64
        expected = {"txHash": tx_hash, "status": "1", "gasUsed": "150000"}
        mock_req.return_value = self._mock_response(expected)

        api = BinanceWeb3API(api_key="k", api_secret="s")
        result = api.get_transaction_detail(tx_hash=tx_hash, chain_id="56")

        self.assertEqual(result, expected)

    @patch("binance_web3_api.requests.request")
    def test_get_token_balances_returns_data(self, mock_req):
        """get_token_balances devuelve la lista de balances de la wallet."""
        expected = [{"tokenAddress": TSLAB, "balance": "5000000000000000000"}]
        mock_req.return_value = self._mock_response(expected)

        api = BinanceWeb3API(api_key="k", api_secret="s")
        # La firma real usa `address` como primer arg posicional
        result = api.get_token_balances(
            address=WALLET,
            chain_id="56",
            token_addresses=[TSLAB],
        )

        self.assertEqual(result, expected)

    @patch("binance_web3_api.requests.request")
    def test_api_returns_none_on_error_code(self, mock_req):
        """_data devuelve None cuando la API responde con code != 0."""
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"code": 400, "msg": "Bad Request", "success": False}
        mock_req.return_value = resp

        api = BinanceWeb3API(api_key="k", api_secret="s")
        result = api.get_gas_price()

        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# Tests para executor.py — funciones de flujo LIVE (Commit 1)
# ---------------------------------------------------------------------------


class TestExecutorLiveFunctions(unittest.TestCase):
    """Verifica las funciones de orquestación LIVE del executor."""

    # --- build_api_swap_transaction ---

    @patch("binance_web3_api.BinanceWeb3API")
    def test_build_api_swap_transaction_two_step_success(self, MockAPI):
        """build_api_swap_transaction orquesta quote → swap y devuelve el dict esperado."""
        mock_api = MockAPI.return_value
        mock_api.get_aggregated_quote.return_value = [
            {"quoteId": "q-001", "vendorName": "LiquidMesh"}
        ]
        # Dirección válida de 40 hex chars (EIP-55 checksum compatible)
        router_addr = "0x10ED43C718714eb63d5aA57B78B54704E256024E"
        mock_api.build_swap_transaction.return_value = {
            "to": router_addr,
            "data": "0xcalldata",
            "gas": "300000",
            "value": "0",
        }

        result = build_api_swap_transaction(
            bstock_contract=TSLAB,
            usdt_contract=USDT,
            amount_bstock=Decimal("1.0"),
            wallet_address=WALLET,
        )

        self.assertIsNotNone(result)
        self.assertIn("to", result)
        self.assertIn("data", result)
        self.assertEqual(result["source"], "binance_api_two_step")
        self.assertEqual(result["quote_id"], "q-001")
        self.assertEqual(result["amount_in"], int(Decimal("1.0") * Decimal(10**18)))

    @patch("binance_web3_api.BinanceWeb3API")
    def test_build_api_swap_transaction_returns_none_when_quote_empty(self, MockAPI):
        """build_api_swap_transaction retorna None si la cotización está vacía."""
        mock_api = MockAPI.return_value
        mock_api.get_aggregated_quote.return_value = None

        result = build_api_swap_transaction(
            bstock_contract=TSLAB,
            amount_bstock=Decimal("1.0"),
            wallet_address=WALLET,
        )

        self.assertIsNone(result)

    @patch("binance_web3_api.BinanceWeb3API")
    def test_build_api_swap_transaction_returns_none_when_no_quote_id(self, MockAPI):
        """build_api_swap_transaction retorna None si el quote no contiene quoteId."""
        mock_api = MockAPI.return_value
        mock_api.get_aggregated_quote.return_value = [{"vendorName": "X"}]  # sin quoteId

        result = build_api_swap_transaction(
            bstock_contract=TSLAB,
            amount_bstock=Decimal("1.0"),
            wallet_address=WALLET,
        )

        self.assertIsNone(result)

    # --- build_approve_transaction ---

    @patch("binance_web3_api.BinanceWeb3API")
    def test_build_approve_transaction_success(self, MockAPI):
        """build_approve_transaction retorna dict con to, data y source cuando la API responde OK."""
        mock_api = MockAPI.return_value
        mock_api.get_erc20_approve_transaction.return_value = {
            "to": TSLAB,
            "data": "0xapprovedata",
        }

        result = build_approve_transaction(
            token_contract=TSLAB,
            amount_wei=10**18,
            chain_id="56",
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["value"], 0)
        self.assertEqual(result["source"], "binance_api_approve")
        self.assertIn("data", result)

    @patch("binance_web3_api.BinanceWeb3API")
    def test_build_approve_transaction_returns_none_when_no_calldata(self, MockAPI):
        """build_approve_transaction retorna None si la respuesta no incluye calldata."""
        mock_api = MockAPI.return_value
        mock_api.get_erc20_approve_transaction.return_value = {"to": TSLAB}  # sin data

        result = build_approve_transaction(
            token_contract=TSLAB,
            amount_wei=10**18,
        )

        self.assertIsNone(result)

    # --- sign_transaction ---

    @patch("executor.w3")
    def test_sign_transaction_returns_hex_string(self, mock_w3):
        """sign_transaction devuelve una cadena hex cuando la clave privada está en entorno."""
        # Clave privada de prueba (32 bytes, sin fondos reales)
        test_pk = "0x" + "aa" * 32
        mock_w3.eth.get_transaction_count.return_value = 5
        mock_w3.eth.gas_price = 3_000_000_000

        signed_mock = MagicMock()
        signed_mock.rawTransaction.hex.return_value = "0x" + "ff" * 32
        mock_w3.eth.account.sign_transaction.return_value = signed_mock

        tx = {
            "to": "0x" + "bb" * 20,
            "data": "0xcalldata",
            "value": 0,
            "gas": 200000,
        }

        with patch.dict(os.environ, {"WALLET_PRIVATE_KEY": test_pk}):
            result = sign_transaction(tx, nonce=5)

        self.assertIsNotNone(result)
        self.assertTrue(result.startswith("0x"))

    def test_sign_transaction_returns_none_without_private_key(self):
        """sign_transaction retorna None si WALLET_PRIVATE_KEY no está en entorno."""
        tx = {"to": WALLET, "data": "0x", "value": 0, "gas": 21000}
        env_without_pk = {k: v for k, v in os.environ.items() if k != "WALLET_PRIVATE_KEY"}

        with patch.dict(os.environ, env_without_pk, clear=True):
            result = sign_transaction(tx)

        self.assertIsNone(result)

    # --- broadcast_signed_transaction ---

    @patch("executor.w3")
    def test_broadcast_signed_transaction_returns_hash(self, mock_w3):
        """broadcast_signed_transaction retorna el tx_hash si eth_sendRawTransaction tiene éxito."""
        tx_hash_bytes = bytes.fromhex("ab" * 32)
        mock_w3.eth.send_raw_transaction.return_value = tx_hash_bytes

        result = broadcast_signed_transaction("0x" + "ff" * 64)

        self.assertIsNotNone(result)
        self.assertTrue(result.startswith("0x"))

    @patch("executor.w3")
    def test_broadcast_signed_transaction_returns_none_on_exception(self, mock_w3):
        """broadcast_signed_transaction retorna None si eth_sendRawTransaction lanza excepción."""
        mock_w3.eth.send_raw_transaction.side_effect = Exception("insufficient funds")

        result = broadcast_signed_transaction("0x" + "ff" * 64)

        self.assertIsNone(result)

    # --- verify_transaction ---

    @patch("executor.w3")
    def test_verify_transaction_confirmed(self, mock_w3):
        """verify_transaction retorna status=1 si el recibo reporta éxito."""
        receipt_mock = MagicMock()
        receipt_mock.__getitem__ = lambda self, key: {"status": 1, "gasUsed": 150000}[key]
        receipt_mock.get = lambda key, default=None: {"status": 1, "gasUsed": 150000}.get(key, default)
        mock_w3.eth.get_transaction_receipt.return_value = receipt_mock

        tx_hash = "0x" + "aa" * 32
        result = verify_transaction(tx_hash)

        self.assertIsNotNone(result)

    @patch("executor.w3")
    def test_verify_transaction_returns_none_when_not_found(self, mock_w3):
        """verify_transaction retorna confirmed=False cuando el recibo aún no está disponible."""
        mock_w3.eth.get_transaction_receipt.return_value = None

        # verify_transaction hace polling; con max_polls=1 y receipt=None retorna confirmed=False
        result = verify_transaction("0x" + "bb" * 32, max_polls=1, poll_interval_s=0)

        self.assertIsNotNone(result)
        self.assertFalse(result["confirmed"])
        self.assertFalse(result["success"])


if __name__ == "__main__":
    unittest.main()
