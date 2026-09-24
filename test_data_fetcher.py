"""
Script de pruebas unitarias y de integración para data_fetcher.py y web3_price_fetcher.py.

Verifica:
1. Pruebas Unitarias (con Mocks):
   - Consulta y validaciones de Ondo Finance API.
   - Consulta al catálogo de Binance Web3 con caché en memoria (TTL).
   - Consulta de precio on-chain mediante Web3 (PancakeSwap V2).
   - Unificación de precios: Web3 directo, fallback a Ondo y desacoplamiento de Ondo.
2. Pruebas en Vivo (Live Integration):
   - Prueba directa de fetch_onchain_price_web3 con el contrato conocido de TSLAB en BSC.
   - Flujo completo de fetch_prices("TSLA", "TSLAon") sin depender de Ondo.
"""

import logging
import sys
import unittest
from decimal import Decimal
from unittest.mock import patch, MagicMock

from data_fetcher import (
    fetch_binance_catalog,
    fetch_ondo_price,
    fetch_prices,
    _catalog_cache,
)
from web3_price_fetcher import fetch_onchain_price_web3

# Configuración de logging para visualización clara durante las pruebas
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("test_data_fetcher")

# Contrato conocido de TSLAB en BSC Mainnet
KNOWN_TSLAB_CONTRACT = "0x5b1910eaad6450e50f816082aa078c41f10c292f"


class TestDataFetcherUnit(unittest.TestCase):
    """Pruebas unitarias con mocks para validar lógica interna sin depender de la red."""

    def setUp(self):
        # Limpiar caché de catálogo antes de cada prueba
        _catalog_cache["data"] = None
        _catalog_cache["timestamp"] = 0.0

    @patch("data_fetcher.requests.get")
    def test_fetch_ondo_price_success(self, mock_get):
        """Verifica que fetch_ondo_price procese correctamente la respuesta y use Decimal."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "primaryMarket": {"symbol": "TSLAon", "price": "48.516937826065743784"},
            "underlyingMarket": {"ticker": "TSLA", "price": "338.88"},
            "timestamp": 1755888858907,
        }
        mock_get.return_value = mock_response

        with patch("data_fetcher.ONDO_API_KEY", "test_key_123"):
            result = fetch_ondo_price("TSLAon")

        self.assertIsNotNone(result)
        self.assertEqual(result["symbol"], "TSLAon")
        self.assertEqual(result["underlying_ticker"], "TSLA")
        self.assertIsInstance(result["primary_price"], Decimal)
        self.assertIsInstance(result["underlying_price"], Decimal)
        self.assertEqual(result["primary_price"], Decimal("48.516937826065743784"))
        self.assertEqual(result["underlying_price"], Decimal("338.88"))

    @patch("data_fetcher.requests.get")
    def test_fetch_ondo_price_null_underlying(self, mock_get):
        """Verifica que si underlyingMarket.price es null, retorna None (mercado cerrado)."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "primaryMarket": {"symbol": "TSLAon", "price": "48.50"},
            "underlyingMarket": {"ticker": "TSLA", "price": None},
            "timestamp": 1755888858907,
        }
        mock_get.return_value = mock_response

        with patch("data_fetcher.ONDO_API_KEY", "test_key_123"):
            result = fetch_ondo_price("TSLAon")

        self.assertIsNone(result)

    def test_fetch_ondo_missing_api_key(self):
        """Verifica que sin API Key configurada retorne None de inmediato con log de error."""
        with patch("data_fetcher.ONDO_API_KEY", ""):
            result = fetch_ondo_price("TSLAon")
            self.assertIsNone(result)

    def test_fetch_ondo_invalid_symbol(self):
        """Verifica que símbolos que no terminen en 'on' sean rechazados."""
        with patch("data_fetcher.ONDO_API_KEY", "test_key_123"):
            result = fetch_ondo_price("TSLA")
            self.assertIsNone(result)

    @patch("data_fetcher.requests.get")
    def test_fetch_binance_catalog_success(self, mock_get):
        """Verifica que fetch_binance_catalog extraiga contract_address y multiplier válidos."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [
                {
                    "chainId": "56",
                    "contractAddress": KNOWN_TSLAB_CONTRACT,
                    "symbol": "TSLAB",
                    "ticker": "TSLA",
                    "multiplier": "1.000000000000000000",
                    "cs": "TSLABUSDT",
                },
            ],
            "success": True,
        }
        mock_get.return_value = mock_response

        result = fetch_binance_catalog("TSLA")
        self.assertIsNotNone(result)
        self.assertEqual(result["ticker"], "TSLA")
        self.assertEqual(result["contract_address"], KNOWN_TSLAB_CONTRACT)
        self.assertIsInstance(result["multiplier"], Decimal)
        self.assertEqual(result["multiplier"], Decimal("1.000000000000000000"))

    @patch("data_fetcher.requests.get")
    def test_fetch_binance_catalog_nonexistent_ticker(self, mock_get):
        """Verifica que un ticker inexistente ('XXXX') retorne None."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [
                {"chainId": "56", "contractAddress": "0x123", "symbol": "AAPL", "ticker": "AAPL", "multiplier": "1"},
            ],
            "success": True,
        }
        mock_get.return_value = mock_response

        result = fetch_binance_catalog("XXXX")
        self.assertIsNone(result)

    @patch("data_fetcher.requests.get")
    def test_binance_catalog_cache_ttl(self, mock_get):
        """Verifica que llamadas subsecuentes usen la caché en memoria y no repitan la petición HTTP."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [
                {"chainId": "56", "contractAddress": "0x123", "symbol": "TSLAB", "ticker": "TSLA", "multiplier": "1"},
            ],
            "success": True,
        }
        mock_get.return_value = mock_response

        res1 = fetch_binance_catalog("TSLA")
        self.assertIsNotNone(res1)
        self.assertEqual(mock_get.call_count, 1)

        res2 = fetch_binance_catalog("TSLA")
        self.assertIsNotNone(res2)
        self.assertEqual(mock_get.call_count, 1)

    @patch("web3_price_fetcher.get_v2_price")
    @patch("web3_price_fetcher.get_v2_pair_address")
    def test_fetch_onchain_price_web3_mock(self, mock_pair, mock_price):
        """Verifica la función fetch_onchain_price_web3 con respuestas simuladas."""
        mock_pair.return_value = "0xAc5cb50d90A7a2Bc5DEF56194bE8D93C905bCD5F"
        mock_price.return_value = Decimal("382.50")

        result = fetch_onchain_price_web3(KNOWN_TSLAB_CONTRACT)
        self.assertIsNotNone(result)
        self.assertEqual(result["price_usdt"], Decimal("382.50"))
        self.assertEqual(result["pair_address"], "0xAc5cb50d90A7a2Bc5DEF56194bE8D93C905bCD5F")
        self.assertEqual(result["source"], "pancakeswap_v2")

    @patch("data_fetcher.fetch_onchain_price_web3")
    @patch("data_fetcher.fetch_binance_catalog")
    @patch("data_fetcher.fetch_ondo_price")
    def test_fetch_prices_full_success(self, mock_ondo, mock_binance, mock_web3):
        """Verifica unificación cuando todas las fuentes (Ondo, Binance, Web3) están activas."""
        mock_ondo.return_value = {
            "symbol": "TSLAon",
            "primary_price": Decimal("38.00"),
            "underlying_price": Decimal("380.00"),
            "underlying_ticker": "TSLA",
            "timestamp": 1755888858907,
        }
        mock_binance.return_value = {
            "symbol": "TSLAB",
            "ticker": "TSLA",
            "contract_address": KNOWN_TSLAB_CONTRACT,
            "multiplier": Decimal("0.1"),
            "chain_id": "56",
        }
        mock_web3.return_value = {
            "price_usdt": Decimal("38.20"),
            "pair_address": "0xAc5cb50d90A7a2Bc5DEF56194bE8D93C905bCD5F",
            "source": "pancakeswap_v2",
        }

        unified = fetch_prices("TSLA", "TSLAon")
        self.assertIsNotNone(unified)
        self.assertEqual(unified["symbol"], "TSLA")
        self.assertEqual(unified["underlying_price"], Decimal("380.00"))
        # 38.20 / 0.1 = 382.00
        self.assertEqual(unified["onchain_price"], Decimal("382.00"))
        self.assertEqual(unified["contract_address"], KNOWN_TSLAB_CONTRACT)
        self.assertEqual(unified["multiplier"], Decimal("0.1"))
        self.assertTrue(unified["sources"]["ondo"])
        self.assertTrue(unified["sources"]["binance"])
        self.assertTrue(unified["sources"]["web3"])

    @patch("data_fetcher.fetch_onchain_price_web3")
    @patch("data_fetcher.fetch_binance_catalog")
    @patch("data_fetcher.fetch_ondo_price")
    def test_fetch_prices_without_ondo(self, mock_ondo, mock_binance, mock_web3):
        """Verifica que el bot funcione sin depender de Ondo, obteniendo el precio directo de Web3."""
        mock_ondo.return_value = None  # Simula falta de ONDO_API_KEY o mercado bursátil cerrado
        mock_binance.return_value = {
            "symbol": "TSLAB",
            "ticker": "TSLA",
            "contract_address": KNOWN_TSLAB_CONTRACT,
            "multiplier": Decimal("1.0"),
            "chain_id": "56",
        }
        mock_web3.return_value = {
            "price_usdt": Decimal("382.02"),
            "pair_address": "0xAc5cb50d90A7a2Bc5DEF56194bE8D93C905bCD5F",
            "source": "pancakeswap_v2",
        }

        unified = fetch_prices("TSLA", "TSLAon")
        self.assertIsNotNone(unified)
        self.assertEqual(unified["symbol"], "TSLA")
        self.assertIsNone(unified["underlying_price"])  # Sin Ondo
        self.assertEqual(unified["onchain_price"], Decimal("382.02"))  # De Web3 PancakeSwap
        self.assertEqual(unified["contract_address"], KNOWN_TSLAB_CONTRACT)
        self.assertFalse(unified["sources"]["ondo"])
        self.assertTrue(unified["sources"]["binance"])
        self.assertTrue(unified["sources"]["web3"])


def run_live_tests():
    """Ejecuta pruebas en vivo contra BSC Mainnet y Binance Web3."""
    print("\n" + "=" * 78)
    print(">> FASE 2: EJECUCIÓN DE PRUEBAS EN VIVO (INTEGRACIÓN WEB3 EN BSC)")
    print("=" * 78)

    # 1. Probar fetch_onchain_price_web3 con un contrato conocido (TSLAB)
    print(f"\n1. Consultando PancakeSwap V2 para TSLAB ({KNOWN_TSLAB_CONTRACT})...")
    tslab_web3 = fetch_onchain_price_web3(KNOWN_TSLAB_CONTRACT)
    if tslab_web3:
        print(f"  [OK] Precio On-Chain obtenido con éxito!")
        print(f"       Precio USDT    : {tslab_web3['price_usdt']} (Tipo: {type(tslab_web3['price_usdt']).__name__})")
        print(f"       Pool Address   : {tslab_web3['pair_address']}")
        print(f"       Fuente DEX     : {tslab_web3['source']}")
    else:
        print("  [ERROR] No se pudo obtener precio Web3 para TSLAB.")

    # 2. Probar el flujo completo fetch_prices("TSLA", "TSLAon") sin depender de Ondo
    print("\n2. Ejecutando flujo completo fetch_prices('TSLA', 'TSLAon') sin depender de Ondo...")
    result = fetch_prices("TSLA", "TSLAon")
    print("\n--- RESULTADO CONSOLIDADO ---")
    if result:
        print(f"  Símbolo          : {result['symbol']}")
        print(f"  Precio Subyacente: {result['underlying_price']}")
        print(f"  Precio On-Chain  : {result['onchain_price']} USDT")
        print(f"  Contrato BSC     : {result['contract_address']}")
        print(f"  Pool PancakeSwap : {result.get('pair_address')}")
        print(f"  Multiplicador    : {result['multiplier']}")
        print(f"  Timestamp Ondo   : {result['ondo_timestamp']}")
        print(f"  Fuentes Activas  : Ondo={result['sources']['ondo']}, Binance={result['sources']['binance']}, Web3={result['sources']['web3']}")
    else:
        print("  [ERROR] fetch_prices retornó None.")
    print("=" * 78 + "\n")


if __name__ == "__main__":
    print("==============================================================================")
    print(" 1. EJECUCIÓN DE PRUEBAS UNITARIAS (Lógica, Mocks, Precisión, Caché y Web3) ")
    print("==============================================================================")
    suite = unittest.TestLoader().loadTestsFromTestCase(TestDataFetcherUnit)
    runner = unittest.TextTestRunner(verbosity=2)
    test_result = runner.run(suite)

    if not test_result.wasSuccessful():
        print("Las pruebas unitarias fallaron.")
        sys.exit(1)

    print("\n==============================================================================")
    print(" 2. EJECUCIÓN DE PRUEBAS EN VIVO DE INTEGRACIÓN (BSC MAINNET + PANCAKESWAP)   ")
    print("==============================================================================")
    run_live_tests()
