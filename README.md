# Arbitrage Bot - BNB Chain Tokenized Stocks (bStocks)

Proyecto desarrollado para el hackathon **"BNB Hack: Edición de Acciones Tokenizadas"** organizado por BNB Chain. 

El objetivo es detectar oportunidades e ineficiencias de arbitraje de precios entre el precio on-chain de acciones tokenizadas en BNB Smart Chain (BSC DEX) y la cotización real de la acción en la bolsa de EE.UU. en tiempo de ejecución.

---

## Módulo 1: `data_fetcher.py` y `web3_price_fetcher.py`

Este módulo se encarga de extraer cotizaciones de Ondo Finance, metadatos del catálogo de Binance Web3 y precios en tiempo real on-chain directamente desde los pools de liquidez en BNB Smart Chain (PancakeSwap V2).

### Fuentes de Datos

1. **Web3 Directo - PancakeSwap V2 DEX** (`web3_price_fetcher.py`):
   - Conexión vía RPC a BNB Smart Chain (`https://bsc-dataseed.binance.org/`).
   - Consulta el contrato Factory V2 (`0xcA143Ce32Fe78f1f7019d7d551a6402fC5350c73`) para localizar el pool del bStock contra USDT (`0x55d398326f99059fF775485246999027B3197955`).
   - Lee `getReserves()` on-chain y calcula el precio spot real del bStock en USDT con precisión `Decimal`.

2. **Binance Web3 API - Catálogo RWA** (GET `.../stock/detail/list/ai`):
   - Catálogo de ~1925 activos tokenizados en BNB Smart Chain (`chainId=56`).
   - Provee direcciones de contrato (`contractAddress`) y factores multiplicadores (`multiplier`).
   - Implementa **caché en memoria con TTL de 1 hora** (`BINANCE_CATALOG_TTL = 3600`).

3. **Ondo Finance API** (GET `https://api.gm.ondo.finance/v1/assets/{symbol}/prices/latest`):
   - Provee la cotización oficial de la acción real subyacente en Wall Street (`underlyingMarket.price`).
   - Requiere autenticación mediante el header `x-api-key`.
   - Si no está disponible (ej. sin API Key o fuera de horario bursátil), el bot puede operar obteniendo el precio on-chain directamente vía Web3.

---

## Estructura del Proyecto

```text
arbitrage-bot/
├── .env.example          # Plantilla de variables de entorno
├── .gitignore            # Exclusiones de Git (.env, cache, venv)
├── config.py             # Constantes, URLs de endpoints y configuración
├── data_fetcher.py       # Módulo principal extractor y unificador de precios
├── requirements.txt      # Dependencias del proyecto
├── test_data_fetcher.py  # Pruebas unitarias y de integración en vivo
└── README.md             # Documentación del proyecto
```

---

## Instalación y Configuración

### 1. Prerrequisitos
- Python 3.9 o superior.

### 2. Crear entorno virtual e instalar dependencias

En PowerShell o Terminal:

```bash
# Crear entorno virtual
python -m venv venv

# Activar entorno virtual
# En Windows (PowerShell):
.\venv\Scripts\Activate.ps1
# En Linux/macOS:
# source venv/bin/activate

# Instalar dependencias
pip install -r requirements.txt
```

### 3. Configurar variables de entorno

Copia la plantilla `.env.example` a `.env`:

```bash
cp .env.example .env
```

Edita `.env` con tu clave de API de Ondo Finance:

```env
ONDO_API_KEY=tu_api_key_de_ondo_aqui
```

> **Nota:** Si no dispones de una clave de Ondo de inmediato, el sistema utilizará Binance como respaldo y ejecutará las pruebas unitarias completas simuladas (mocks).

---

## Ejecución de Pruebas

Ejecuta el script de prueba:

```bash
python test_data_fetcher.py
```

### Lo que ejecuta el test:
1. **Pruebas Unitarias (Mocks)**:
   - Valida el uso estricto de `Decimal` en todos los cálculos financieros.
   - Valida la extracción de `contract_address` y `multiplier` en `fetch_binance_catalog`.
   - Valida el comportamiento de la caché en memoria (TTL de 1 hora sin peticiones HTTP redundantes).
   - Valida el cálculo de `onchain_price = ondo.primary_price / binance.multiplier`.
   - Valida el manejo de tickers inexistentes (`"XXXX"` -> `None`).
   - Valida el retorno con `onchain_price=None` si Ondo no está disponible.
2. **Pruebas de Integración en Vivo**:
   - Consulta el catálogo de Binance para `"TSLA"` extrayendo la dirección real del contrato y multiplicador.
   - Ejecuta `fetch_prices("TSLA", "TSLAon")`.

---

## Formato del Diccionario Unificado

La función `fetch_prices(ticker, ondo_symbol)` retorna un diccionario estandarizado:

```python
{
    "symbol": "TSLA",
    "underlying_price": Decimal("380.00"),                              # Precio en Wall Street (Ondo) o None si mercado cerrado
    "onchain_price": Decimal("382.0279455457876201125346158"),         # Precio en PancakeSwap V2 ajustado por multiplicador
    "contract_address": "0x5b1910eaad6450e50f816082aa078c41f10c292f", # Contrato TSLAB en BSC
    "pair_address": "0xAc5cb50d90A7a2Bc5DEF56194bE8D93C905bCD5F",     # Pool TSLAB/USDT en PancakeSwap V2
    "multiplier": Decimal("1.000000000000000000"),                     # Factor de conversión (Binance)
    "ondo_timestamp": 1755888858907,                                    # Timestamp de Ondo (o None)
    "sources": {
        "ondo": False,
        "binance": True,
        "web3": True
    }
}
```
