# Arbitrage Bot - BNB Chain Tokenized Stocks (bStocks)

Proyecto desarrollado para el hackathon **"BNB Hack: Edición de Acciones Tokenizadas"** organizado por BNB Chain. 

El objetivo es detectar oportunidades e ineficiencias de arbitraje de precios entre el precio on-chain de acciones tokenizadas en BNB Smart Chain (BSC DEX) y la cotización real de la acción en la bolsa de EE.UU. en tiempo de ejecución.

---

## Módulo 1: `data_fetcher.py`, `web3_price_fetcher.py` y `stock_price_fetcher.py`

Consolida la información necesaria para detectar ineficiencias de arbitraje entre el mercado bursátil tradicional y BNB Smart Chain (BSC DEX).

### Fuentes de Datos y Cascada de Precios

1. **Precio Subyacente (Bolsa de EE.UU. / Wall Street)**:
   - **Yahoo Finance (`stock_price_fetcher.py`)**: Fuente primaria en tiempo real con `fast_info['last_price']`.
   - **Ondo Finance API (`fetch_ondo_price`)**: Respaldo secundario institucional si se dispone de `ONDO_API_KEY`.

2. **Precio On-Chain Real (BSC DEX)**:
   - **PancakeSwap V3 (`fetch_onchain_price_v3`)**: Fuente primaria prioritaria por profundidad de liquidez ($215K-$564K USD). Evalúa tiers [500, 2500, 10000] y deriva el precio desde `slot0().sqrtPriceX96` con la fórmula:
     $$\text{ratio} = \left(\frac{\text{sqrtPriceX96}}{2^{96}}\right)^2$$
   - **PancakeSwap V2 (`fetch_onchain_price_v2`)**: Fallback secundario con **filtro de liquidez mínima ($50,000 USD)** para evitar precios distorsionados de pools ilíquidos.
   - **Ondo Finance Primary (`primary_price`)**: Fallback terciario ajustado por multiplicador.

3. **Metadatos y Factores Multiplicadores**:
   - **Binance Web3 API (`fetch_binance_catalog`)**: Catálogo RWA en BSC con caché TTL de 1 hora. Identifica la dirección del contrato inteligente y el multiplicador de conversión.

---

## Módulo 2: Motor de Estrategia (`strategy.py`)

Implementa un **mecanismo de arbitraje asimétrico** adaptado a la arquitectura real de los bStocks:

1. **Arbitraje de Prima Positiva (`bStock > Acción Real`)**:
   - **Mecanismo**: Se acuñan (mint) nuevos bStocks pagando USDC al precio oficial del subyacente y se venden en PancakeSwap V3 a un precio mayor.
   - **Automatización**: Sí, ejecutable on-chain.
   - **Decisión**: Emite señal **`BUY`** si $\text{spread\_pct} \ge 1.5\%$ y la ganancia neta estimada supera los costos totales:
     $$\text{gross\_profit} = \text{spread\_usd} \times \left(\frac{\text{trade\_size\_usd}}{\text{underlying\_price}}\right)$$
     $$\text{net\_profit} = \text{gross\_profit} - \text{costs["total"]}$$

2. **Arbitraje de Descuento (`bStock < Acción Real`)**:
   - **Mecanismo**: Comprar bStock barato en el DEX y redimirlo por USDC ante el emisor.
   - **Limitación del MVP**: Requiere interacción manual off-chain, verificación KYC y cuenta de corretaje tradicional con el emisor/agente de transferencia.
   - **Decisión**: El bot emite señal informativa **`HOLD`** indicando que el arbitraje de descuento no es automatizable en el alcance del MVP.

---

## Estructura del Proyecto

```text
arbitrage-bot/
├── .env.example          # Plantilla de variables de entorno
├── .gitignore            # Exclusiones de Git (.env, cache, venv)
├── config.py             # Constantes, URLs, umbrales y costos
├── data_fetcher.py       # Módulo extractor y unificador de precios
├── stock_price_fetcher.py# Cotizaciones bursátiles desde Yahoo Finance
├── web3_price_fetcher.py # Lectura on-chain en PancakeSwap V2 y V3
├── strategy.py           # Motor de decisión y cálculo de rentabilidad
├── executor.py           # Construcción, simulación y registro de swaps
├── main.py               # Loop autónomo de monitoreo
├── test_executor.py      # Pruebas del executor y calldata V3
├── requirements.txt      # Dependencias del proyecto
├── test_data_fetcher.py  # Pruebas de extracción de datos y Web3
├── test_strategy.py      # Pruebas de lógica de estrategia y cooldown
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

### Ejecutar el bot

El bot solo construye y simula swaps con `eth_call`; nunca envía transacciones.
Configura opcionalmente `BSC_RPC_URL` y `DEFAULT_RECIPIENT` en `.env`, y ejecuta:

```bash
python main.py
```

Para una ejecución controlada (útil para validar el loop sin dejar un proceso
continuo), pasa el número de iteraciones como primer argumento:

```bash
python main.py 2
```

El intervalo normal es `POLL_INTERVAL_SECONDS` (60 segundos). Los eventos BUY
se agregan a `signals_log.json`; el detalle de ejecución se guarda en `bot.log`.
El archivo de señales contiene el calldata y el resultado de la simulación, pero
no se transmite ni firma ninguna transacción.

### Pruebas del executor

```bash
python -m unittest test_executor.py -v
```

La prueba en vivo opcional de `test_executor.py` consulta precios reales y solo
muestra el calldata generado para TSLAB; no publica la transacción.

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
    "underlying_price": Decimal("380.1199951171875"),                  # Precio en Wall Street (Yahoo Finance)
    "onchain_price": Decimal("379.42021876694123945299467952202429"),  # Precio spot PancakeSwap V3 (fee 2500)
    "spread_usd": Decimal("-0.6997763502462605470053204779757"),        # onchain_price - underlying_price
    "spread_pct": Decimal("-0.184093538681259303753074007956"),         # Prima/Descuento en %
    "contract_address": "0x5b1910eaad6450e50f816082aa078c41f10c292f",  # Contrato TSLAB en BSC
    "pool_address": "0xB0f5E5400E8F0F7C242F2b7740C004f020579c41",      # Pool V3 TSLAB/USDT
    "dex": "pancakeswap_v3",                                            # Protocolo DEX utilizado
    "multiplier": Decimal("1.000000000000000000"),                      # Factor de conversión (Binance)
    "ondo_timestamp": None,
    "sources": {
        "yfinance": True,
        "ondo": False,
        "binance": True,
        "web3": True
    }
}
```
