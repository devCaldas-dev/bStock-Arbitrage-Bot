# bStock Arbitrage Bot — BNB Hack: Tokenized Stocks Edition

Detector de primas entre acciones tokenizadas que cotizan 24/7 en BNB Chain y sus subyacentes de Wall Street; calcula rentabilidad, prepara calldata V3 y simula la operación sin arriesgar capital.

[![Python 3.9+](https://img.shields.io/badge/Python-3.9%2B-blue)](#how-to-run) [![Web3](https://img.shields.io/badge/Web3-enabled-orange)](#architecture) [![BNB Chain](https://img.shields.io/badge/BNB%20Chain-BSC-yellow)](#architecture) [![Tests](https://img.shields.io/badge/tests-47%20passing-brightgreen)](#testing)

> 🎥 **[Ver video demo (5 min)](URL_DEL_VIDEO)** — arquitectura, demo en vivo, backtest y honestidad técnica.

## The Problem

Los bStocks cotizan 24/7 en BSC, mientras que las acciones reales solo cotizan de lunes a viernes en horario de mercado. Esa desconexión crea ineficiencias: el caso documentado de 4Stock (BNC4) llegó a mostrar una prima de 10x. La mayoría de las herramientas observa precios, pero no convierte la diferencia en una señal auditable y una transacción verificable.

## The Solution

- Monitorea `TSLA`, `NVDA`, `AAPL`, `MSFT` y `GOOGL` en paralelo.
- Usa la API oficial de datos RWA de Binance Web3 como fuente primaria de precios.
- Detecta primas positivas (`bStock > acción real`) comparando PancakeSwap con `yfinance`.
- Calcula spread, gas, comisión, slippage y `net_profit` antes de actuar.
- Construye y simula `exactInputSingle` de PancakeSwap V3 con `eth_call`.
- Guarda cada oportunidad en JSON con calldata lista para una futura ejecución.
- Es explícito sobre la asimetría: el MVP cubre prima positiva, mint & sell; el descuento requiere redeem, KYC y liquidación off-chain.

## Architecture

```text
┌─────────────────────────────────────────────────────────────┐
│                    BOT DE ARBITRAJE                         │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Binance Web3 RWA API ──→ onchain + referencia + estado     │
│         │                                                   │
│         ├─→ CLOSED: último precio conocido congelado        │
│         │                                                   │
│         └─→ Error: catálogo + PancakeSwap + Yahoo/Ondo      │
│         │                                                   │
│         ▼                                                   │
│  strategy.evaluate_opportunity()                            │
│         │                                                   │
│         ├─→ HOLD: spread < 1.5% (mercado eficiente)         │
│         ├─→ HOLD: descuento (no ejecutable sin KYC)         │
│         └─→ BUY: prima >= 1.5% + net_profit > 0             │
│                  │                                          │
│                  ▼                                          │
│         executor.build_swap_transaction()                   │
│         executor.simulate_transaction() (eth_call)          │
│         log_signal_to_json()                                │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

`data_fetcher.py` prioriza la API oficial RWA de Binance Web3 y conserva catálogo, PancakeSwap y Yahoo/Ondo como fallback. `strategy.py` decide. `executor.py` codifica el swap, consulta balance/allowance cuando aparece `STF` y simula. `main.py` repite el flujo y rota `bot.log`.

## Key Technical Decisions

| Decisión | Por qué |
|---|---|
| `Decimal` en lugar de `float` | Precisión financiera en spread y rentabilidad. |
| PancakeSwap V3 en lugar de V2 | En la observación de TSLA, V2 mostraba ~$5K de liquidez frente a ~$427K en V3; V3 evita ese artefacto. |
| Liquidez mínima de `$50K` | Evita señales falsas de pools ilíquidos. |
| API oficial RWA de Binance Web3 | Fuente primaria del hackathon; PancakeSwap + Yahoo/Ondo quedan como fallback operativo. |
| `eth_call` en lugar de envío | Demuestra calldata y validación sin arriesgar capital. |
| Asimetría mint vs redeem | Solo se automatiza lo que es técnicamente ejecutable en el MVP. |

## Backtest Results

El backtest analiza siete cierres diarios de Yahoo Finance por ticker y aplica una variación on-chain determinista limitada a ±3% para demostrar el comportamiento del detector.

| Métrica | Resultado observado |
|---|---:|
| Periodo | 2026-09-15 a 2026-09-23 |
| Días analizados | 7 |
| Tickers | 5 |
| Señales totales | 35 |
| Señales `BUY` | 14 |
| Días con `BUY` | 6 |
| Spread máximo | 8.24% |
| Ganancia teórica | $490.80 USD |

Ejemplos:

| Fecha | Ticker | Spread | Acción | Net profit |
|---|---|---:|---|---:|
| 2026-09-15 | AAPL | 1.64% | `BUY` | $12.74 |
| 2026-09-15 | GOOGL | -0.18% | `HOLD` | — |
| 2026-09-15 | MSFT | -1.33% | `HOLD` | — |

**ADVERTENCIA: el precio on-chain del backtest es una SIMULACIÓN basada en la referencia actual y una variación de hasta ±3%; no es histórico real de blockchain.** El backtest demuestra detección cuando el mercado subyacente está cerrado o durante alta volatilidad, pero sus señales y ganancias son teóricas.

## How to Run

### Requisitos

- Python 3.9+.
- Internet para Yahoo Finance, Binance Web3 y RPC de BNB Chain.

### Instalación

```bash
git clone <URL_DEL_REPOSITORIO>
cd arbitrage-bot
python -m venv venv
# Windows PowerShell
.\venv\Scripts\Activate.ps1
# Linux/macOS: source venv/bin/activate
pip install -r requirements.txt
```

### Configuración

```bash
cp .env.example .env
```

Variables opcionales:

```env
BSC_RPC_URL=https://bsc-dataseed.binance.org/
DEFAULT_RECIPIENT=0x0000000000000000000000000000000000000001
ONDO_API_KEY=tu_api_key_de_ondo
BINANCE_WEB3_API_KEY=tu_api_key_aqui
BINANCE_WEB3_API_SECRET=tu_api_secret_aqui
```

`ONDO_API_KEY` solo se necesita para el fallback de Ondo. `DEFAULT_RECIPIENT` se usa para construir y simular; no firma ni envía fondos.
`BINANCE_WEB3_API_KEY` y `BINANCE_WEB3_API_SECRET` habilitan la API oficial RWA del hackathon. Si no están configuradas o la API falla, el bot conserva el fallback PancakeSwap + Yahoo Finance.

### Data Sources

| Fuente | Uso | Costo |
|---|---|---|
| Binance Web3 RWA API | Primaria: `tokenPrice` on-chain y `referencePrice` subyacente | API key del hackathon |
| PancakeSwap V3 (Web3) | Fallback para precio on-chain si la API RWA falla | Gratis (RPC público) |
| Yahoo Finance (`yfinance`) | Fallback para el precio subyacente si la API RWA falla | Gratis |

La API RWA es la fuente primaria porque entrega ambos precios en una respuesta oficial y sincronizada. PancakeSwap V3 y Yahoo Finance permanecen como fallback para que el bot continúe funcionando ante errores de autenticación, red, rate limits o datos incompletos de Binance. Si también falla Yahoo Finance, el bot conserva el precio on-chain de Web3 y deja `underlying_price` en `None`.

### Binance Web3 RWA API

El cliente usa la autenticación oficial de Binance Web3:

- Base URL: `https://web3.binance.com/build`.
- Headers: `X-OC-APIKEY`, `X-OC-TIMESTAMP` y `X-OC-SIGN`.
- El timestamp es ISO 8601 UTC con milisegundos.
- La firma es Base64 de `HMAC-SHA256(timestamp + method + requestPath + body)`.
- `requestPath` incluye siempre `/build`, por ejemplo `/build/api/v1/dex/market/rwa/price?binanceChainId=56&tokenContractAddresses=...`.

Endpoints usados: `price`, `search`, `tokens` y `underlying-market` bajo `/api/v1/dex/market/rwa/`.

La verificación real fue exitosa. `price` devolvió `tokenPrice=378.89000000` y `referencePrice=378.89`. `underlying-market` devolvió `statusInfo.openState=true`, `reasonCode=TRADING` y `marketData.referencePrice=null` para el activo consultado.

### Comandos

```bash
python main.py                 # loop continuo, 60 s por ciclo
python main.py 2               # demo limitada a 2 ciclos
python backtest.py             # 7 días y backtest_results.json
python test_executor.py        # tests y demo opcional de calldata
python test_backtest.py        # tests del backtest
python -m unittest discover -v # suite completa (47 tests)
```

### Ejecución DRY vs LIVE

**Ejecución DRY:** `python main.py` detecta oportunidades, construye calldata V3, simula con `eth_call` y registra señales en JSON. `main.py` **no firma ni transmite ninguna transacción**.

**Flujo LIVE:** `demo_live.py` es el entrypoint separado para ejecución real.
- `--dry-run` construye y simula, pero nunca hace broadcast.
- `--live --max-live-tx N` puede firmar y transmitir approve+swap en BSC Mainnet si se cumplen las precondiciones (wallet financiada, KYT aprobado, simulación exitosa) y el límite `N` lo permite.
- El flujo LIVE **no se activa desde `main.py`**.

```bash
python demo_live.py --dry-run                    # simula, sin broadcast
python demo_live.py --live --max-live-tx 2       # LIVE, máximo 2 txs reales
```
## Limitations & Roadmap

| Limitación actual | Próximo paso |
|---|---|
| Solo prima positiva; redeem requiere KYC | Integrar el flujo permitido por el emisor. |
| Histórico on-chain simulado en backtest | Indexar swaps históricos de PancakeSwap. |
| `main.py` no ejecuta ni firma; `demo_live.py --live` sí (opt-in con `--max-live-tx`) | Añadir wallet, approvals y controles de riesgo explícitos. |
| Alertas solo en logs/JSON | Integrar notifier de Telegram. |
| Sin interfaz visual | Añadir dashboard de spreads, señales y simulaciones. |
| Ondo es opcional | Integrar Ondo API como validación cruzada completa. |

> **Alcance del demo entregado:** El flujo LIVE (`demo_live.py --live`) está implementado y cubierto por tests con mocks, pero no se ejecutó con fondos reales durante el desarrollo por restricciones de tiempo. Las simulaciones y calldata del demo son construidas y verificadas con `eth_call`, no transmitidas. El bot no vincula wallet productiva en el MVP.

## Testing

La suite contiene pruebas unitarias para firma HMAC, respuesta RWA mock, prioridad de la API oficial y fallback, además de los tests existentes:

```bash
python -m unittest discover -v
```

Cubre cálculos de estrategia, fuentes y liquidez, conversión a uint256, estructura del calldata, simulación mock, diagnóstico `STF`, imports de `main.py` y estructura de `backtest_results.json`.

> ⚠️ **ADVERTENCIA METODOLÓGICA**
> El precio on-chain del backtest es una **simulación** basada en la referencia actual ±3%. No es histórico real de blockchain. Las señales y ganancias son teóricas y demuestran **capacidad de detección**, no rentabilidad histórica.

## Verified Contracts (BSC Mainnet)

| Token | Contract | Pool V3 (0.25%) | Liquidez |
|---|---|---|---|
| TSLAB | `0x5b19...292f` | `0xB0f5...9c41` | $427K |
| USDT | `0x55d3...7955` | — | — |
| SwapRouter V3 | `0x1b81...eB14` | — | — |

## Why This Matters for BNB Hack

El hackathon busca herramientas que operen sobre la "brecha" entre acciones tokenizadas y sus subyacentes. Este bot:
- **Operacionaliza** la detección (no solo observa, construye tx).
- **Es honesto** sobre la asimetría (mint vs redeem).
- **Valida datos** de 3 fuentes independientes (Binance, PancakeSwap, Yahoo).
- **Simula sin riesgo** usando `eth_call`, listo para producción.

## License & Contact

**License:** prototipo de hackathon; añadir una licencia formal antes de distribuirlo en producción.

**Contact:** Armando Toro Cárdenas — [armandotorocardenas@email.com] — [@deCaldasCaridad](https://twitter.com/deCaldasCaridad)

