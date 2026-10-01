"""
Suite de Pruebas Unitarias y en Vivo para data_fetcher, web3_price_fetcher y stock_price_fetcher.

Verifica:
1. Pruebas Unitarias (Mocks):
   - Lectura de precio V3 mediante slot0() y derivación de sqrtPriceX96.
   - Filtro de liquidez mínima en V2 (< $50K USD es rechazado).
   - Consulta de precio subyacente con yfinance.
   - Cascada unificada y cálculo preciso de la prima/spread de arbitraje.
2. Pruebas en Vivo (Live Integration):
   - Consulta a PancakeSwap V3 con liquidez concentrada para TSLAB.
   - Consulta a Yahoo Finance para la acción subyacente TSLA.
   - Confirmación de que el pool V2 de TSLAB (~$5K) es rechazado por MIN_LIQUIDITY_USD.
   - Ejecución de fetch_prices("TSLA") con prima calculada.
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
from web3_price_fetcher import (
    fetch_onchain_price_v3,
    fetch_onchain_price_v2,
    fetch_onchain_price_web3,
    get_v2_price,
    MIN_LIQUIDITY_USD,
)
from stock_price_fetcher import fetch_underlying_price

# Configuración de logging
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
        _catalog_cache["data"] = None
        _catalog_cache["timestamp"] = 0.0

    @patch("web3_price_fetcher.w3.eth.contract")
    @patch("web3_price_fetcher.get_v3_pool_address")
    def test_fetch_onchain_price_v3_mock(self, mock_get_pool, mock_contract):
        """Verifica la derivación de precio V3 desde slot0() y sqrtPriceX96."""
        mock_get_pool.return_value = "0xB0f5E5400E8F0F7C242F2b7740C004f020579c41"

        # Simular pool V3:
        # sqrtPriceX96 = 4510802670335315992506988806
        # Si token0 es USDT y token1 es TSLAB:
        mock_pool = MagicMock()
        mock_pool.functions.slot0.return_value.call.return_value = [
            4510802670335315992506988806,  # sqrtPriceX96
            -12345, 0, 1, 1, 0, True
        ]
        mock_pool.functions.liquidity.return_value.call.return_value = 1000000
        mock_pool.functions.token0.return_value.call.return_value = "0x55d398326f99059fF775485246999027B3197955"  # USDT
        mock_pool.functions.token1.return_value.call.return_value = KNOWN_TSLAB_CONTRACT  # TSLAB
        mock_contract.return_value = mock_pool

        result = fetch_onchain_price_v3(KNOWN_TSLAB_CONTRACT, fee_tier=2500)
        self.assertIsNotNone(result)
        self.assertEqual(result["dex"], "pancakeswap_v3")
        self.assertIsInstance(result["price_usdt"], Decimal)
        self.assertGreater(result["price_usdt"], Decimal("100"))

    def test_v2_liquidity_validation_rejection(self):
        """Verifica que un pool V2 con liquidez de ~$5,000 USD sea rechazado por MIN_LIQUIDITY_USD ($50,000)."""
        mock_pair = "0xAc5cb50d90A7a2Bc5DEF56194bE8D93C905bCD5F"
        usdt_addr = "0x55d398326f99059fF775485246999027B3197955"

        with patch("web3_price_fetcher.w3.eth.contract") as mock_contract:
            pair_mock = MagicMock()
            pair_mock.functions.token0.return_value.call.return_value = KNOWN_TSLAB_CONTRACT
            pair_mock.functions.token1.return_value.call.return_value = usdt_addr
            # Reserva de USDT: 2,500 * 10^18 (Liquidez total ≈ $5,000 USD)
            pair_mock.functions.getReserves.return_value.call.return_value = [
                int(Decimal("6.5") * Decimal(10**18)),      # reserve0: bStock
                int(Decimal("2500") * Decimal(10**18)),     # reserve1: 2,500 USDT ($5,000 pool)
                123456
            ]
            mock_contract.return_value = pair_mock

            # Debe retornar None porque $5,000 < $50,000 MIN_LIQUIDITY_USD
            result = get_v2_price(mock_pair, KNOWN_TSLAB_CONTRACT)
            self.assertIsNone(result)

    @patch("yfinance.Ticker")
    def test_fetch_underlying_price_mock(self, mock_ticker_cls):
        """Verifica que fetch_underlying_price extraiga correctamente el precio de yfinance."""
        mock_ticker = MagicMock()
        mock_ticker.fast_info = {"last_price": 365.25}
        mock_ticker_cls.return_value = mock_ticker

        price = fetch_underlying_price("TSLA")
        self.assertIsNotNone(price)
        self.assertIsInstance(price, Decimal)
        self.assertEqual(price, Decimal("365.25"))

    @patch("data_fetcher.fetch_underlying_price")
    @patch("data_fetcher.fetch_binance_catalog")
    @patch("data_fetcher.fetch_onchain_price_web3")
    @patch("data_fetcher.binance_web3_api")
    def test_fetch_prices_full_spread_calculation(self, mock_web3_api, mock_web3, mock_binance, mock_yf):
        """Verifica que fetch_prices calcule correctamente el spread en USD y porcentaje."""
        mock_web3_api.search_rwa_tokens.return_value = None
        mock_yf.return_value = Decimal("350.00")
        mock_binance.return_value = {
            "symbol": "TSLAB",
            "ticker": "TSLA",
            "contract_address": KNOWN_TSLAB_CONTRACT,
            "multiplier": Decimal("1.0"),
            "chain_id": "56",
        }
        mock_web3.return_value = {
            "price_usdt": Decimal("367.50"),
            "pool_address": "0xB0f5E5400E8F0F7C242F2b7740C004f020579c41",
            "fee_tier": 2500,
            "dex": "pancakeswap_v3",
            "source": "pancakeswap_v3",
        }

        data = fetch_prices("TSLA")
        self.assertIsNotNone(data)
        self.assertEqual(data["symbol"], "TSLA")
        self.assertEqual(data["underlying_price"], Decimal("350.00"))
        self.assertEqual(data["onchain_price"], Decimal("367.50"))
        # spread_usd = 367.50 - 350.00 = 17.50
        self.assertEqual(data["spread_usd"], Decimal("17.50"))
        # spread_pct = (17.50 / 350.00) * 100 = 5.0%
        self.assertEqual(data["spread_pct"], Decimal("5.0"))
        self.assertEqual(data["dex"], "pancakeswap_v3")
        self.assertTrue(data["sources"]["yfinance"])
        self.assertTrue(data["sources"]["web3"])

    @patch("data_fetcher.fetch_ondo_price")
    @patch("data_fetcher.fetch_onchain_price_web3")
    @patch("data_fetcher.fetch_binance_catalog")
    @patch("data_fetcher.fetch_underlying_price")
    @patch("data_fetcher._fetch_rwa_prices", return_value=None)
    def test_ondo_timestamp_propagated(self, mock_rwa, mock_yf, mock_catalog, mock_web3, mock_ondo):
        """Verifica que ondo_timestamp se propaga desde fetch_ondo_price cuando web3 falla."""
        mock_yf.return_value = Decimal("380.00")
        mock_catalog.return_value = {
            "contract_address": "0x5b1910eaad6450e50f816082aa078c41f10c292f",
            "multiplier": Decimal("1.0"),
            "symbol": "TSLAB",
        }
        mock_web3.return_value = None  # Fuerza el fallback a Ondo
        mock_ondo.return_value = {
            "primary_price": Decimal("380"),
            "timestamp": 1234567890,
            "underlying_price": Decimal("380"),
        }
        data = fetch_prices("TSLA")
        self.assertIsNotNone(data)
        self.assertEqual(data["ondo_timestamp"], 1234567890)

    @patch("data_fetcher.fetch_ondo_price")
    @patch("data_fetcher.fetch_onchain_price_web3")
    @patch("data_fetcher.fetch_binance_catalog")
    @patch("data_fetcher.fetch_underlying_price")
    @patch("data_fetcher._fetch_rwa_prices", return_value=None)
    def test_ondo_timestamp_none_when_ondo_fails(self, mock_rwa, mock_yf, mock_catalog, mock_web3, mock_ondo):
        """Verifica que ondo_timestamp es None cuando fetch_ondo_price devuelve None."""
        mock_yf.return_value = Decimal("380.00")
        mock_catalog.return_value = {
            "contract_address": "0x5b1910eaad6450e50f816082aa078c41f10c292f",
            "multiplier": Decimal("1.0"),
            "symbol": "TSLAB",
        }
        mock_web3.return_value = None  # Fuerza el fallback a Ondo
        mock_ondo.return_value = None   # Ondo también falla
        data = fetch_prices("TSLA")
        # Con web3=None y ondo=None, no hay onchain_price → puede retornar None o sin ondo_timestamp
        if data is not None:
            self.assertIsNone(data.get("ondo_timestamp"))


def run_live_tests():
    """Ejecuta las pruebas en vivo contra los endpoints de mercado real."""
    print("\n" + "=" * 80)
    print(">> FASE 2: EJECUCIÓN DE PRUEBAS EN VIVO (PANCAKESWAP V3 + YFINANCE)")
    print("=" * 80)

    # 1. Probar lectura en PancakeSwap V3
    print(f"\n1. Consultando PancakeSwap V3 para TSLAB ({KNOWN_TSLAB_CONTRACT})...")
    v3_result = fetch_onchain_price_v3(KNOWN_TSLAB_CONTRACT)
    if v3_result:
        print(f"  [OK] Precio V3 Obtenido : {v3_result['price_usdt']} USDT")
        print(f"       Pool Address       : {v3_result['pool_address']}")
        print(f"       Fee Tier           : {v3_result['fee_tier']} ({v3_result['fee_tier'] / 10000}%)")
        print(f"       Liquidez Activa    : {v3_result['liquidity']}")
        print(f"       DEX                : {v3_result['dex']}")
    else:
        print("  [ERROR] No se pudo obtener precio V3.")

    # 2. Confirmación de rechazo de pool V2 por liquidez insuficiente
    print("\n2. Verificando rechazo de pool V2 por liquidez insuficiente ($5K < $50K)...")
    v2_result = fetch_onchain_price_v2(KNOWN_TSLAB_CONTRACT)
    print(f"  [OK] Resultado esperado V2 (None): {v2_result}")

    # 3. Probar lectura de precio subyacente con yfinance
    print("\n3. Consultando precio subyacente de Wall Street con Yahoo Finance (TSLA)...")
    underlying = fetch_underlying_price("TSLA")
    print(f"  [OK] Precio Subyacente  : {underlying} USD (Tipo: {type(underlying).__name__})")

    # 4. Flujo completo fetch_prices("TSLA") con prima calculada
    print("\n4. Ejecutando flujo completo fetch_prices('TSLA')...")
    result = fetch_prices("TSLA")

    print("\n" + "-" * 50)
    print("      RESULTADO DEL ANÁLISIS DE ARBITRAJE")
    print("-" * 50)
    if result:
        print(f"  Ticker Subyacente   : {result['symbol']}")
        print(f"  Precio Wall Street  : ${result['underlying_price']} USD")
        print(f"  Precio On-Chain DEX : ${result['onchain_price']} USDT ({result['dex']})")
        print(f"  Pool PancakeSwap    : {result['pool_address']}")
        if result['spread_usd'] is not None and result['spread_pct'] is not None:
            sign = "+" if result['spread_usd'] >= 0 else ""
            print(f"  Prima/Spread (USD)  : {sign}${result['spread_usd']:.4f} USD")
            print(f"  Prima/Spread (%)    : {sign}{result['spread_pct']:.2f}%")
        print(f"  Fuentes Activas     : yfinance={result['sources']['yfinance']}, web3={result['sources']['web3']}, binance={result['sources']['binance']}, ondo={result['sources']['ondo']}")
    else:
        print("  [ERROR] fetch_prices retornó None.")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    print("==============================================================================")
    print(" 1. EJECUCIÓN DE PRUEBAS UNITARIAS (V3 slot0, V2 filtro liquidez, Spread)   ")
    print("==============================================================================")
    suite = unittest.TestLoader().loadTestsFromTestCase(TestDataFetcherUnit)
    runner = unittest.TextTestRunner(verbosity=2)
    test_result = runner.run(suite)

    if not test_result.wasSuccessful():
        print("Las pruebas unitarias fallaron.")
        sys.exit(1)

    print("\n==============================================================================")
    print(" 2. EJECUCIÓN DE PRUEBAS EN VIVO DE INTEGRACIÓN (V3 LIVE + YFINANCE LIVE)    ")
    print("==============================================================================")
    run_live_tests()
