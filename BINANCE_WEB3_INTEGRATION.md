# Integración Binance Web3 API — bStock Arbitrage Bot

> **Hackathon:** BNB Hack: Tokenized Stocks Edition  
> **Red:** BSC Mainnet (chain_id = 56)  
> **Fecha de referencia:** Septiembre 2026

---

## Índice

1. [Arquitectura de la integración](#1-arquitectura-de-la-integración)
2. [Módulos de API integrados](#2-módulos-de-api-integrados)
3. [Autenticación OC](#3-autenticación-oc)
4. [Flujo completo: construir → firmar → transmitir → verificar](#4-flujo-completo)
5. [Ejemplos de petición y respuesta](#5-ejemplos-de-petición-y-respuesta)
6. [Guía de configuración](#6-guía-de-configuración)
7. [Riesgos, limitaciones y seguridad](#7-riesgos-limitaciones-y-seguridad)

---

## 1. Arquitectura de la integración

```
┌─────────────────────────────────────────────────────────────────────┐
│                        main.py (Bot Loop)                           │
│  DRY_MODE ──────────────────────────────────────────── LIVE_MODE    │
│  fetch_prices() → evaluate_opportunity() → _handle_buy_signal()     │
└────────────┬────────────────────────────────────────┬───────────────┘
             │                                        │
    ┌────────▼────────┐                    ┌──────────▼──────────────┐
    │   executor.py   │                    │     executor.py         │
    │ (DRY: simula)   │                    │   (LIVE: ejecuta)       │
    │                 │                    │                         │
    │ build_api_swap  │                    │ build_api_swap          │
    │ simulate_tx     │                    │ simulate_tx  ◄─ STOP si │
    │ log_signal_json │                    │ build_approve    falla   │
    └────────┬────────┘                    │ sign_transaction        │
             │                             │ broadcast_signed_tx     │
             │                             │ verify_transaction      │
             │                             │ log_signal_json         │
             │                             └──────────┬──────────────┘
             │                                        │
             └──────────────┬─────────────────────────┘
                            │
               ┌────────────▼────────────────────┐
               │       binance_web3_api.py        │
               │                                  │
               │  RWA Data ──────► precios RWA    │
               │  Trading API ───► quote + swap   │
               │  Trading API ───► approve ERC-20 │
               │  Transaction ───► gas, simulate  │
               │  Transaction ───► broadcast      │
               │  Wallet API ────► tx detail      │
               └──────────────────────────────────┘
                            │
               ┌────────────▼──────────────────┐
               │   https://web3.binance.com    │
               │   /build  (BASE_URL)          │
               │   BSC Mainnet  chain_id=56    │
               └───────────────────────────────┘
```

**Decisión de diseño clave:** `build_api_swap_transaction()` siempre intenta la
Trading API primero. Si la API no responde (credenciales faltantes, rate-limit),
el bot hace *fallback* automático a `build_swap_transaction()` que construye el
calldata localmente contra PancakeSwap V3. Esto garantiza que el bot sigue
detectando oportunidades en DRY_MODE incluso sin credenciales de API activas.

---

## 2. Módulos de API integrados

| Módulo | Método en `BinanceWeb3API` | Uso en el bot |
|---|---|---|
| **RWA Data** | `get_rwa_price()` | Precio oficial on-chain del bStock |
| **RWA Data** | `get_rwa_underlying_market()` | Precio Wall Street del subyacente |
| **RWA Data** | `get_rwa_tokens()` | Catálogo de bStocks disponibles |
| **RWA Data** | `search_rwa_tokens()` | Búsqueda de contrato por ticker |
| **General Data** | `get_price_info()` | Precio genérico USDT/WBNB |
| **Trading API** | `get_aggregated_quote()` | Mejor cotización agregada DEX |
| **Trading API** | `quote_and_build_swap()` | Quote + calldata en una llamada |
| **Trading API** | `build_swap_transaction()` | Calldata usando quoteId previo |
| **Trading API** | `get_erc20_approve_transaction()` | Calldata del approve ERC-20 |
| **Trading API** | `get_transaction_status()` | Estado de orden del agregador |
| **Transaction API** | `get_gas_price()` | gasPrice actual en BSC |
| **Transaction API** | `get_gas_limit()` | Estimación de gas para la tx |
| **Transaction API** | `simulate_transaction()` | Simulación server-side (POST) |
| **Transaction API** | `broadcast_transaction()` | Transmisión de tx firmada |
| **Transaction API** | `get_broadcast_orders()` | Historial de broadcasts |
| **Wallet API** | `get_transaction_detail()` | Estado final por tx_hash |
| **Wallet API** | `get_token_balances()` | Balances de bStock y USDT |
| **Wallet API** | `get_transactions_by_address()` | Historial de la wallet |

---

## 3. Autenticación OC

Todos los endpoints de `https://web3.binance.com/build` usan el esquema
propietario **OC** con tres headers HTTP:

```
X-OC-APIKEY   : <api_key>
X-OC-TIMESTAMP: 2026-09-25T14:32:01.123Z   ← ISO-8601 UTC con ms
X-OC-SIGN     : <firma_base64>
```

### Algoritmo de firma

```python
import base64, hashlib, hmac

def sign(api_secret: str, timestamp: str, method: str,
         request_path: str, body: str = "") -> str:
    """
    request_path incluye el prefijo /build y la query string completa.
    Ejemplo: /build/api/v1/dex/aggregator/quote?binanceChainId=56&amount=...
    body es "" para GET; JSON serializado para POST.
    """
    pre_hash = timestamp + method.upper() + request_path + body
    digest   = hmac.new(
        api_secret.encode("utf-8"),
        pre_hash.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return base64.b64encode(digest).decode("utf-8")
```

**Puntos críticos:**
- El timestamp debe estar en formato `YYYY-MM-DDTHH:MM:SS.mmmZ` (UTC).
- El `requestPath` firmado incluye `/build` como prefijo pero la `BASE_URL`
  ya lo incluye, así que el path firmado es distinto a la URL completa.
- Para POST, el body debe ser el JSON serializado **sin espacios** y en el
  mismo orden que se envía (`json.dumps(body, separators=(",", ":"))` ).

---

## 4. Flujo completo

### 4.1 DRY_MODE (desarrollo y monitoreo)

```
fetch_prices(ticker)
    └─► evaluate_opportunity(data)  →  action = "BUY" ?
            └─► build_api_swap_transaction(bstock, usdt, 1.0, wallet_ficticio)
                    │   [si API falla]
                    └─► build_swap_transaction(bstock, usdt, 1.0)  ← fallback local
            └─► simulate_transaction(tx, from=wallet_ficticio)
                    ├─► POST /api/v1/dex/pre-transaction/simulate-transaction  [API]
                    └─► eth_call local  [fallback]
            └─► log_signal_to_json(signal, tx_data, simulation)
```

### 4.2 LIVE_MODE (demo en vivo)

```
Step 0: Validar prerequisitos
        BINANCE_WEB3_API_KEY ✓
        BINANCE_WEB3_API_SECRET ✓
        WALLET_PRIVATE_KEY ✓
        WALLET_ADDRESS ✓ (no dirección nula)
        LIVE_TRADE_AMOUNT ≥ 0.001 bStock ✓

Step 1: build_api_swap_transaction(bstock, usdt, 0.005, wallet)
        GET /api/v1/dex/aggregator/quote-and-build
        → {to, data, value, gas, quoteId}

Step 2: simulate_transaction(tx, from=wallet)
        POST /api/v1/dex/pre-transaction/simulate-transaction
        → {success: true}   ← STOP si false

Step 3: build_approve_transaction(bstock, amount_wei)
        GET /api/v1/dex/aggregator/approve-transaction
        → {to: bstock_contract, data: calldata_approve, value: 0}

Step 4: sign_transaction(approve_tx, nonce=N)
        web3.eth.account.sign_transaction(tx, WALLET_PRIVATE_KEY)
        → SignedTransaction

Step 5: broadcast_signed_transaction(signed_approve, wallet)
        POST /api/v1/dex/pre-transaction/broadcast-transaction
        → {txHash: "0xAAPROVE..."}

Step 6: verify_transaction("0xAPPROVE...", max_polls=10)
        GET /api/v1/dex/wallet/transaction?txHash=...
        → {status: "1"}   ← STOP si "0"

Step 7: sign_transaction(swap_tx, nonce=N+1)
        → SignedTransaction

Step 8: broadcast_signed_transaction(signed_swap, wallet)
        POST /api/v1/dex/pre-transaction/broadcast-transaction
        → {txHash: "0xSWAP..."}

Step 9: verify_transaction("0xSWAP...", max_polls=12)
        GET /api/v1/dex/wallet/transaction?txHash=...
        → {status: "1", blockNumber: "44123456", gasUsed: "185000"}

Step 10: log_signal_to_json(signal, tx_data, simulation, execution)
```

---

## 5. Ejemplos de petición y respuesta

### 5.1 RWA Price

**Petición:**
```http
GET /build/api/v1/dex/market/rwa/price
    ?binanceChainId=56
    &tokenContractAddresses=0x8755c5c39b1aa9053a83ac731242a2cf4d04b0fe

X-OC-APIKEY: <key>
X-OC-TIMESTAMP: 2026-09-25T14:32:01.123Z
X-OC-SIGN: <firma>
```

**Respuesta esperada:**
```json
{
  "code": "000000",
  "data": [
    {
      "tokenContractAddress": "0x8755c5c39b1aa9053a83ac731242a2cf4d04b0fe",
      "symbol": "bTSLA",
      "price": "248.73",
      "priceChangePercent": "1.24",
      "volume24h": "15420.00"
    }
  ]
}
```

**Código Python:**
```python
from binance_web3_api import BinanceWeb3API

api = BinanceWeb3API()
data = api.get_rwa_price(
    chain_id         = "56",
    contract_address = "0x8755c5c39b1aa9053a83ac731242a2cf4d04b0fe",
)
# data[0]["price"] → "248.73"
onchain_price = Decimal(data[0]["price"])
```

---

### 5.2 Quote & Build Swap (Trading API)

**Petición:**
```http
GET /build/api/v1/dex/aggregator/quote-and-build
    ?binanceChainId=56
    &amount=5000000000000000          ← 0.005 bStock en wei (18 dec)
    &fromTokenAddress=0x8755c5c39b1aa9053a83ac731242a2cf4d04b0fe
    &toTokenAddress=0x55d398326f99059fF775485246999027B3197955
    &userWalletAddress=0xTuWallet
    &slippage=0.5
    &vendor=LiquidMesh
```

**Respuesta esperada:**
```json
{
  "code": "000000",
  "data": {
    "quoteId"   : "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "to"        : "0xRouterDelAgregador",
    "data"      : "0x12345678abcdef...",
    "value"     : "0x0",
    "gas"       : 280000,
    "fromAmount": "5000000000000000",
    "toAmount"  : "1241500000000000000",
    "priceImpact": "0.08"
  }
}
```

**Código Python:**
```python
from decimal import Decimal
from executor import build_api_swap_transaction

tx = build_api_swap_transaction(
    bstock_contract   = "0x8755c5c39b1aa9053a83ac731242a2cf4d04b0fe",
    amount_bstock     = Decimal("0.005"),
    wallet_address    = "0xTuWallet",
    slippage_pct      = "0.5",
)
# tx["to"]       → dirección del router del agregador
# tx["data"]     → calldata listo para firmar
# tx["gas"]      → 280000
# tx["quote_id"] → "a1b2c3d4-..."
```

---

### 5.3 ERC-20 Approve (Trading API)

**Petición:**
```http
GET /build/api/v1/dex/aggregator/approve-transaction
    ?binanceChainId=56
    &tokenContractAddress=0x8755c5c39b1aa9053a83ac731242a2cf4d04b0fe
    &approveAmount=5000000000000000
```

**Respuesta esperada:**
```json
{
  "code": "000000",
  "data": {
    "to"   : "0x8755c5c39b1aa9053a83ac731242a2cf4d04b0fe",
    "data" : "0x095ea7b3000000000000000000000000<router>0000000000000000000000000000000000000000000000000011c37937e08000",
    "value": "0x0"
  }
}
```

**Código Python:**
```python
from executor import build_approve_transaction

approve_tx = build_approve_transaction(
    token_contract = "0x8755c5c39b1aa9053a83ac731242a2cf4d04b0fe",
    amount_wei     = 5_000_000_000_000_000,  # 0.005 × 10^18
)
# approve_tx["data"] → calldata de approve(router, amount)
```

---

### 5.4 Broadcast (Transaction API)

**Petición:**
```http
POST /build/api/v1/dex/pre-transaction/broadcast-transaction
Content-Type: application/json

{
  "binanceChainId"   : "56",
  "signedTransaction": "0x02f8...<tx firmada en hex>",
  "address"          : "0xTuWallet"
}
```

**Respuesta esperada:**
```json
{
  "code": "000000",
  "data": {
    "txHash": "0xabc123def456...",
    "status": "pending"
  }
}
```

**Código Python:**
```python
from executor import sign_transaction, broadcast_signed_transaction

# Firmar (lee WALLET_PRIVATE_KEY del entorno)
signed = sign_transaction(tx_data, nonce=None)  # nonce=None → consulta on-chain

# Broadcast
tx_hash = broadcast_signed_transaction(signed, wallet_address="0xTuWallet")
# tx_hash → "0xabc123def456..."
```

---

### 5.5 Verificación de transacción (Wallet API)

**Petición:**
```http
GET /build/api/v1/dex/wallet/transaction
    ?txHash=0xabc123def456...
    &binanceChainId=56
```

**Respuesta esperada (confirmada):**
```json
{
  "code": "000000",
  "data": {
    "txHash"     : "0xabc123def456...",
    "status"     : "1",
    "blockNumber": "44123456",
    "gasUsed"    : "185432",
    "from"       : "0xTuWallet",
    "to"         : "0xRouterAgregador"
  }
}
```

**Código Python:**
```python
from executor import verify_transaction

result = verify_transaction("0xabc123def456...", chain_id="56")
# result["confirmed"] → True
# result["success"]   → True  (status="1")
# result["block"]     → 44123456
# result["gas_used"]  → 185432
```

---

### 5.6 Flujo LIVE completo (código de referencia)

```python
import os
from decimal import Decimal
from executor import execute_live_swap

# Variables de entorno requeridas:
# export BINANCE_WEB3_API_KEY="..."
# export BINANCE_WEB3_API_SECRET="..."
# export WALLET_PRIVATE_KEY="0x..."
# export WALLET_ADDRESS="0xTuWallet"

resultado = execute_live_swap(
    bstock_contract    = "0x8755c5c39b1aa9053a83ac731242a2cf4d04b0fe",  # bTSLA BSC
    wallet_address     = os.getenv("WALLET_ADDRESS"),
    amount_bstock      = Decimal("0.005"),
    slippage_pct       = "0.5",
    current_price_usdt = Decimal("248.73"),  # precio de referencia para logging
)

print("approve_hash :", resultado["approve_hash"])
print("swap_hash    :", resultado["swap_hash"])
print("confirmado   :", resultado["verified"])
print("exitoso      :", resultado["success"])
print("error        :", resultado["error"])
```

---

## 6. Guía de configuración

### 6.1 Prerequisitos del entorno

```bash
# 1. Activar virtualenv
.\venv\Scripts\activate          # Windows PowerShell
source venv/bin/activate         # Linux / macOS

# 2. Instalar dependencias (ya en requirements.txt)
pip install -r requirements.txt

# 3. Configurar variables de entorno
cp .env.example .env
# Editar .env con tus credenciales reales
```

### 6.2 Variables de entorno

| Variable | Obligatoria | Descripción |
|---|---|---|
| `BINANCE_WEB3_API_KEY` | Sí | Clave de API Binance Web3 |
| `BINANCE_WEB3_API_SECRET` | Sí | Secreto de API Binance Web3 |
| `WALLET_PRIVATE_KEY` | Solo LIVE | Clave privada de la wallet BSC |
| `WALLET_ADDRESS` | Solo LIVE | Dirección pública de la wallet |
| `LIVE_MODE` | No | `true` activa transacciones reales (default: `false`) |
| `LIVE_TRADE_AMOUNT` | No | Monto bStock por operación (default: `0.005`) |
| `LIVE_SLIPPAGE_PCT` | No | Slippage máximo en % (default: `0.5`) |
| `MAX_LIVE_TX_PER_SESSION` | No | Límite de txns LIVE por sesión (default: `3`) |

### 6.3 Ejecución

```bash
# DRY_MODE (solo monitoreo y simulación):
python main.py

# DRY_MODE con límite de ciclos (para pruebas):
python main.py 3

# LIVE_MODE (transacciones reales — demo hackathon):
$env:LIVE_MODE="true"
$env:WALLET_PRIVATE_KEY="0x..."
$env:WALLET_ADDRESS="0xTuWallet"
python main.py 1
```

### 6.4 Estructura de archivos modificados

```
arbitrage-bot/
├── binance_web3_api.py   ← 25+ métodos: RWA, Trading, Transaction, Wallet
├── executor.py           ← Firma, broadcast, verify, fallback local
├── main.py               ← LIVE_MODE flag, validación, manejo de BUY
├── config.py             ← LIVE_MODE, LIVE_TRADE_AMOUNT, WALLET_ADDRESS, etc.
├── .env.example          ← Plantilla completa de variables de entorno
├── .env                  ← TUS credenciales (en .gitignore, nunca al repo)
└── signals_log.json      ← Historial de señales + resultado LIVE
```

---

## 7. Riesgos, limitaciones y seguridad

### 7.1 Manejo de clave privada

| Riesgo | Mitigación implementada |
|---|---|
| Clave privada expuesta en código | Se lee **solo** desde `WALLET_PRIVATE_KEY` env var |
| Clave en historial de shell | Usar archivo `.env` en lugar de `export` directo |
| Clave en logs | `sign_transaction()` nunca imprime ni registra la clave |
| Wallet principal comprometida | Usar **wallet dedicada** de demo con fondos mínimos |

**Recomendación operativa:** Crea una wallet nueva específicamente para la
hackathon. Deposita exactamente lo necesario: ~0.01–0.05 BNB para gas y
0.01–0.05 del bStock que vas a demostrar.

### 7.2 Approve ERC-20

- El bot usa **approve ajustado** (solo el monto del swap), no `approve(MAX_UINT256)`.
- Esto limita la exposición: si el router es comprometido, solo puede gastar el
  monto aprobado.
- Desventaja: cada swap diferente requiere un nuevo approve (2 txns en lugar de 1).
- Para la demo, con una sola operación de `0.005 bStock`, el costo extra es
  mínimo (~$0.01 en gas BSC).

### 7.3 Gas y slippage

| Parámetro | Valor por defecto | Recomendación demo |
|---|---|---|
| `gasPrice` | Consultado vía API | Usar `+10%` sobre el actual para prioridad |
| `gas` limit | 280,000–300,000 | La API estima automáticamente |
| `slippage` | 0.5% | Mantener en 0.5%–1.0% para bStocks de baja liquidez |
| Deadline | 20 min (local) | La API gestiona su propio deadline |

### 7.4 Simulación como gate obligatorio

El bot **nunca transmite sin simular primero**. Si `simulate_transaction()`
retorna `success: False`, la ejecución se aborta y se registra el motivo.
Esto evita desperdiciar gas en transacciones que van a revertir.

### 7.5 Límite de transacciones por sesión

`MAX_LIVE_TX_PER_SESSION` (default: 3) impide que un bug en el bucle o un
mercado volátil envíe decenas de transacciones no deseadas. Ajusta solo cuando
hayas validado el funcionamiento correcto en al menos 2–3 ciclos de demo.

### 7.6 Asimetría del arbitraje de bStocks

| Escenario | Automatable | Mecanismo |
|---|---|---|
| **Prima** (bStock > Wall St.) | ✅ Sí | Mint bStock al precio del emisor → vender en DEX |
| **Descuento** (bStock < Wall St.) | ❌ No (MVP) | Requiere redención KYC off-chain con el emisor |

El bot solo actúa sobre **primas positivas** con `net_profit > 0` tras costos.
Los descuentos se registran como `HOLD` con la razón explicada.

### 7.7 Rate limits de la API

- La Trading API y Transaction API tienen rate limits no publicados explícitamente.
- El `REQUEST_TIMEOUT = 10s` en `config.py` protege contra cuelgues.
- El `POLL_INTERVAL_SECONDS = 60s` entre ciclos previene exceso de llamadas.
- Si recibes código `429` (TooManyRequests), incrementa `POLL_INTERVAL_SECONDS`
  y añade backoff en `BinanceWeb3API._request()`.

### 7.8 Dependencia del quoteId

El `quoteId` retornado por `quote_and_build_swap()` tiene **vigencia corta**
(típicamente 30–60 segundos). Si el bot tarda más de eso entre la cotización
y el broadcast (por latencia de red o simulación lenta), el swap puede fallar
con error de cotización expirada. El método `quote_and_build_swap()` atómico
minimiza este riesgo al hacer quote y build en una sola llamada.

---

*Documento generado para el proyecto bStock Arbitrage Bot — BNB Hack: Tokenized Stocks Edition.*
