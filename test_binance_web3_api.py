import hashlib
import hmac
import base64
import re
import unittest
from decimal import Decimal
from unittest.mock import MagicMock, patch

from binance_web3_api import BinanceWeb3API


class TestBinanceWeb3API(unittest.TestCase):
    def test_binance_web3_api_signature(self):
        api = BinanceWeb3API(api_key="key", api_secret="secret")
        api._request_timestamp = "2026-05-11T10:08:57.715Z"
        signature = api._sign("GET", "/build/api/v1/dex/market/rwa/price?binanceChainId=56", "")
        expected = base64.b64encode(hmac.new(
            b"secret",
            b"2026-05-11T10:08:57.715ZGET/build/api/v1/dex/market/rwa/price?binanceChainId=56",
            hashlib.sha256,
        ).digest()).decode("utf-8")
        self.assertEqual(signature, expected)
        self.assertRegex(api._build_timestamp(), r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")

    @patch("binance_web3_api.requests.request")
    def test_binance_web3_api_mock(self, mock_get):
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {
            "code": 0,
            "msg": "success",
            "data": {"onChainPrice": "367.50", "underlyingPrice": "350.00"},
            "timestamp": 1778494137715,
            "success": True,
        }
        mock_get.return_value = response

        result = BinanceWeb3API(api_key="key", api_secret="secret").get_rwa_price(
            "56", "0x5b1910eaad6450e50f816082aa078c41f10c292f"
        )

        self.assertEqual(result["onChainPrice"], "367.50")
        request_args = mock_get.call_args.args
        request_kwargs = mock_get.call_args.kwargs
        request_url = request_args[1]
        self.assertIn("binanceChainId=56", request_url)
        self.assertNotIn("chainId=56", request_url)
        self.assertEqual(request_url, "https://web3.binance.com/build/api/v1/dex/market/rwa/price?binanceChainId=56&tokenContractAddresses=0x5b1910eaad6450e50f816082aa078c41f10c292f")
        self.assertEqual(set(request_kwargs["headers"]), {"X-OC-APIKEY", "X-OC-TIMESTAMP", "X-OC-SIGN", "Accept"})
        self.assertNotIn("X-MBX-APIKEY", request_kwargs["headers"])
        self.assertEqual(request_kwargs["headers"]["X-OC-TIMESTAMP"][-1], "Z")
        expected_signature = base64.b64encode(hmac.new(
            b"secret",
            (
                request_kwargs["headers"]["X-OC-TIMESTAMP"]
                + "GET/build/api/v1/dex/market/rwa/price?binanceChainId=56&tokenContractAddresses=0x5b1910eaad6450e50f816082aa078c41f10c292f"
            ).encode("utf-8"),
            hashlib.sha256,
        ).digest()).decode("utf-8")
        self.assertEqual(request_kwargs["headers"]["X-OC-SIGN"], expected_signature)
        mock_get.assert_called_once()


class TestRWADataFetcher(unittest.TestCase):
    @patch("data_fetcher.fetch_binance_catalog")
    @patch("data_fetcher.fetch_onchain_price_web3")
    @patch("data_fetcher.fetch_underlying_price")
    @patch("data_fetcher.binance_web3_api")
    def test_fetch_prices_uses_rwa_api(self, mock_api, mock_underlying, mock_web3, mock_catalog):
        mock_api.search_rwa_tokens.return_value = [{"symbol": "TSLA", "contractAddress": "0xabc"}]
        mock_api.get_rwa_price.return_value = {"onChainPrice": "367.50"}
        mock_api.get_rwa_underlying_market.return_value = {
            "statusInfo": {"openState": True, "nextOpenTime": None},
            "marketData": {"referencePrice": "350.00"},
        }

        from data_fetcher import fetch_prices

        result = fetch_prices("TSLA")

        self.assertEqual(result["onchain_price"], Decimal("367.50"))
        self.assertEqual(result["underlying_price"], Decimal("350.00"))
        self.assertEqual(result["market_status"], "OPEN")
        self.assertTrue(result["sources"]["rwa_api"])
        self.assertFalse(result["sources"]["yfinance_fallback"])
        mock_catalog.assert_not_called()
        mock_web3.assert_not_called()
        mock_underlying.assert_not_called()

    @patch("data_fetcher.fetch_binance_catalog")
    @patch("data_fetcher.fetch_onchain_price_web3")
    @patch("data_fetcher.fetch_underlying_price")
    @patch("data_fetcher.binance_web3_api")
    def test_fetch_prices_fallback_when_api_fails(self, mock_api, mock_underlying, mock_web3, mock_catalog):
        mock_api.search_rwa_tokens.return_value = None
        mock_underlying.return_value = Decimal("350")
        mock_catalog.return_value = {
            "symbol": "TSLAB",
            "contract_address": "0xabc",
            "multiplier": 1,
        }
        mock_web3.return_value = {"price_usdt": Decimal("367.5"), "dex": "pancakeswap_v3"}

        from data_fetcher import fetch_prices

        result = fetch_prices("TSLA")

        self.assertEqual(result["dex"], "pancakeswap_v3")
        self.assertFalse(result["sources"]["rwa_api"])
        self.assertTrue(result["sources"]["yfinance_fallback"])
        self.assertTrue(result["sources"]["web3"])

    @patch("data_fetcher.fetch_binance_catalog")
    @patch("data_fetcher.fetch_onchain_price_web3")
    @patch("data_fetcher.fetch_underlying_price", return_value=None)
    @patch("data_fetcher.binance_web3_api")
    def test_fetch_prices_web3_only_when_yfinance_fails(self, mock_api, mock_underlying, mock_web3, mock_catalog):
        mock_api.search_rwa_tokens.return_value = None
        mock_catalog.return_value = {
            "symbol": "TSLAB",
            "contract_address": "0xabc",
            "multiplier": Decimal("1"),
        }
        mock_web3.return_value = {"price_usdt": Decimal("367.5"), "dex": "pancakeswap_v3"}

        from data_fetcher import fetch_prices

        result = fetch_prices("TSLA")

        self.assertIsNone(result["underlying_price"])
        self.assertEqual(result["onchain_price"], Decimal("367.5"))
        self.assertFalse(result["sources"]["rwa_api"])
        self.assertTrue(result["sources"]["web3"])
        self.assertFalse(result["sources"]["yfinance_fallback"])


if __name__ == "__main__":
    unittest.main()