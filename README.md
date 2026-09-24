# bStock Arbitrage Bot — BNB Hack: Tokenized Stocks Edition

Detector de primas entre acciones tokenizadas que cotizan 24/7 en BNB Chain y sus subyacentes de Wall Street; calcula rentabilidad, prepara calldata V3 y simula la operación sin arriesgar capital.

[![Python 3.9+](https://img.shields.io/badge/Python-3.9%2B-blue)](#how-to-run) [![Web3](https://img.shields.io/badge/Web3-enabled-orange)](#architecture) [![BNB Chain](https://img.shields.io/badge/BNB%20Chain-BSC-yellow)](#architecture) [![Tests](https://img.shields.io/badge/tests-21%20passing-brightgreen)](#testing)

## The Problem

Los bStocks cotizan 24/7 en BSC, mientras que las acciones reales solo cotizan de lunes a viernes en horario de mercado. Esa desconexión crea ineficiencias: el caso documentado de 4Stock (BNC4) llegó a mostrar una prima de 10x. La mayoría de las herramientas observa precios, pero no convierte la diferencia en una señal auditable y una transacción verificable.

## The Solution

- Monitorea `TSLA`, `NVDA`, `AAPL`, `MSFT` y `GOOGL` en paralelo.
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
│  Binance Catalog ──→ contract_address + multiplier          │
│         │                                                   │
│         ▼                                                   │
│  Web3 (PancakeSwap V3) ──→ onchain_price_usdt              │
│         │                                                   │
│         ▼                                                   │
│  Yahoo Finance ──→ underlying_price (acción real)           │
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
│         executor.simulate_transaction() (eth_call)         │
│         log_signal_to_json()                                │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

`data_fetcher.py` une catálogo, precio on-chain y subyacente. `strategy.py` decide. `executor.py` codifica el swap, consulta balance/allowance cuando aparece `STF` y simula. `main.py` repite el flujo y rota `bot.log`.

## Key Technical Decisions

| Decisión | Por qué |
|---|---|
| `Decimal` en lugar de `float` | Precisión financiera en spread y rentabilidad. |
| PancakeSwap V3 en lugar de V2 | En la observación de TSLA, V2 mostraba ~$5K de liquidez frente a ~$427K en V3; V3 evita ese artefacto. |
| Liquidez mínima de `$50K` | Evita señales falsas de pools ilíquidos. |
| `yfinance` como fuente primaria | Cero API key para el jurado; Ondo queda como fallback opcional. |
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
```

`ONDO_API_KEY` solo se necesita para el fallback de Ondo. `DEFAULT_RECIPIENT` se usa para construir y simular; no firma ni envía fondos.

### Comandos

```bash
python main.py                 # loop continuo, 60 s por ciclo
python main.py 2               # demo limitada a 2 ciclos
python backtest.py             # 7 días y backtest_results.json
python test_executor.py        # tests y demo opcional de calldata
python test_backtest.py        # tests del backtest
python -m unittest discover -v # suite completa
```

## Limitations & Roadmap

| Limitación actual | Próximo paso |
|---|---|
| Solo prima positiva; redeem requiere KYC | Integrar el flujo permitido por el emisor. |
| Histórico on-chain simulado en backtest | Indexar swaps históricos de PancakeSwap. |
| No hay ejecución real ni firma | Añadir wallet, approvals y controles de riesgo explícitos. |
| Alertas solo en logs/JSON | Integrar notifier de Telegram. |
| Sin interfaz visual | Añadir dashboard de spreads, señales y simulaciones. |
| Ondo es opcional | Integrar Ondo API como validación cruzada completa. |

## Testing

La suite contiene **21 tests pasando**:

```bash
python -m unittest discover -v
```

Cubre cálculos de estrategia, fuentes y liquidez, conversión a uint256, estructura del calldata, simulación mock, diagnóstico `STF`, imports de `main.py` y estructura de `backtest_results.json`.

## License & Contact

**License:** prototipo de hackathon; añadir una licencia formal antes de distribuirlo en producción.

**Contact:** abrir un issue o pull request en el repositorio del proyecto.
