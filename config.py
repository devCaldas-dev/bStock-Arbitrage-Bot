"""
Módulo de Configuración - Bot de Arbitraje de Acciones Tokenizadas (bStocks).

Define constantes globales, endpoints de APIs externas, parámetros de red y
carga de variables de entorno seguras.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Cargar variables de entorno desde el archivo .env si existe
env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=env_path)

# --- Endpoints de APIs Externas ---

# Ondo Finance API (requiere header x-api-key)
ONDO_API_BASE_URL: str = "https://api.gm.ondo.finance/v1/assets"

# Binance Web3 API (endpoint público RWA stocks)
BINANCE_API_BASE_URL: str = (
    "https://www.binance.com/bapi/defi/v1/public/wallet-direct/buw/wallet/market/token/rwa/stock/detail/list/ai"
)

# --- Parámetros de Red y Conectividad ---

# Chain ID predeterminado (56 = BNB Smart Chain Mainnet)
DEFAULT_CHAIN_ID: str = "56"

# Timeout global para peticiones HTTP en segundos
REQUEST_TIMEOUT: int = 10

# Tiempo de vida de la caché del catálogo de Binance en segundos (1 hora)
BINANCE_CATALOG_TTL: int = 3600

# --- Credenciales y Autenticación ---

# Clave de API para Ondo Finance
ONDO_API_KEY: str = os.getenv("ONDO_API_KEY", "").strip()
