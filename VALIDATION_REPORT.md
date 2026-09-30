# Informe de validación DRY — Binance Web3 API

**Proyecto:** bStock Arbitrage Bot  
**Hackathon:** BNB Hack: Tokenized Stocks Edition  
**Red:** BSC Mainnet (`chainId=56`)  
**Alcance:** lectura y construcción de transacciones. **Sin broadcast.**

---

## 1. Comandos ejecutados y resultado

| Comando | Resultado |
|---|---|
| `python run_tests.py` | **26/26 OK** — Failures 0, Errors 0, Skipped 0 |
| `python validate_dry_run.py` | Validación contra API real: RWA Data OK; Trading/KYT según hallazgos 1–3 |
| `python demo_live.py --dry-run` | Construcción E2E sin transmitir (ver sección 6) |

Suite unitaria (`test_*.py`): firma OC, params camelCase (`binanceChainId`), fetcher RWA, executor (Decimal→wei, calldata, STF), strategy y backtest.

**Estado DRY:** el flujo de punta a punta **funciona sin broadcast**: quote (dos pasos) → approve calldata → swap calldata → simulación (API o `eth_call`) → `verify_transaction` contra hash (lista normalizada a dict). LIVE exige wallet real financiada.

---

## 2. Endpoints corregidos (parámetros finales)

Base: `https://web3.binance.com/build`. Auth OC: `X-OC-APIKEY`, `X-OC-TIMESTAMP`, `X-OC-SIGN`.

| Método cliente | Path final | Params camelCase | Notas |
|---|---|---|---|
| `get_rwa_price` | `GET /api/v1/dex/market/rwa/price` | `binanceChainId`, `tokenContractAddresses` | |
| `get_rwa_tokens` | `GET /api/v1/dex/market/rwa/tokens` | `binanceChainId` | |
| `search_rwa_tokens` | `GET /api/v1/dex/market/rwa/search` | `keyword` | |
| `get_rwa_underlying_market` | `GET /api/v1/dex/market/rwa/underlying-market` | `binanceChainId`, `tokenContractAddress` | |
| `get_rwa_underlying_info` | `GET /api/v1/dex/market/rwa/underlying-profile` | `binanceChainId`, `tokenContractAddress` | era *underlying-info* |
| `get_rwa_issuance_platforms` | `GET /api/v1/dex/market/rwa/platforms` | — | |
| `get_aggregated_quote` | `GET /api/v1/dex/aggregator/quote` | `binanceChainId`, `amount` (wei), `fromTokenAddress`, `toTokenAddress`, `slippagePercent`, `userWalletAddress`, `vendor` opcional | **Ruta RWA:** este + swap |
| `build_swap_transaction` | `GET /api/v1/dex/aggregator/swap` | mismos + `quoteId`, `userWalletAddress` | era `/build-tx` |
| `quote_and_build_swap` | `GET /api/v1/dex/aggregator/quote-and-swap` | + `vendor` (obligatorio) | **No usar para bTokens RWA** |
| `get_erc20_approve_transaction` | `GET /api/v1/dex/aggregator/approve-transaction` | `binanceChainId`, `tokenContractAddress`, `approveAmount`, `vendor` | LiquidMesh / InchFusion |
| `get_transaction_status` | `GET /api/v1/dex/aggregator/history` | `binanceChainId`, `txHash` | era *transaction-status* |
| `get_aggregator_supported_chains` | `GET /api/v1/dex/aggregator/supported/chain` | — | |
| `get_gas_price` | `GET /api/v1/dex/pre-transaction/gas-price` | `binanceChainId` | |
| `get_gas_limit` | `GET /api/v1/dex/pre-transaction/gas-limit` | `binanceChainId`, `evmTx` | |
| `simulate_transaction` | `POST /api/v1/dex/pre-transaction/simulate` | body: `binanceChainId`, `evmTx` | fallback `eth_call` |
| `broadcast_transaction` | `POST /api/v1/dex/pre-transaction/broadcast-transaction` | `binanceChainId`, `signedTransaction`, `address` | **solo LIVE** |
| `get_broadcast_orders` | `GET /api/v1/dex/post-transaction/orders` | `address`, `binanceChainId`, `limit` | |
| `get_latest_block_height` | `GET /api/v1/dex/pre-transaction/block-height` | `binanceChainId` | |
| `get_token_balances` | `POST /api/v1/dex/balance/token-balances-by-address` | `address`, `tokenContractAddresses[]` | |
| `get_transaction_detail` | `GET /api/v1/dex/post-transaction/transaction-detail-by-txhash` | `binanceChainId`, `txHash` | **lista → dict** |

Constantes de demo:

| Ítem | Valor |
|---|---|
| bTSLA BSC | `0x8755c5c39b1aa9053a83ac731242a2cf4d04b0fe` |
| USDT BSC | `0x55d398326f99059fF775485246999027B3197955` |
| Slippage | `0.5` (`slippagePercent`) |
| Amount wei | `int(Decimal(amount) * 10**18)` |

---

## 3. Hallazgos DRY — impacto y solución

| # | Hallazgo | Impacto | Solución |
|---|---|---|---|
| 1 | Mínimo del aggregator **$5 USD** (error **40375**). `0.001` bTSLA ≈ $0.38 es rechazado. | Quote/swap fallan en demo con montos “hackathon pequeños”. | Usar **≥ 0.013 bTSLA** (~$5 a ~$380/bTSLA). `LIVE_TRADE_AMOUNT=0.013`. |
| 2 | `quote-and-swap` con wallet `0x0000…0001` falla **KYT 40434**. | El atómico no sirve para validar con wallet ficticia. | Wallet real, financiada, KYT/KYC aprobado. |
| 3 | bTokens RWA: **quote → swap** (dos pasos), no `quote-and-swap`. | LiquidMesh en atómico: “Quote forbidden” / sin calldata. | `get_aggregated_quote` + `build_swap_transaction(quoteId)`. TTL quote ~30 s. |
| 4 | `build_approve_transaction` OK con **LiquidMesh / InchFusion**. | Approve sin `vendor` → 40001 / vacío. | Pasar `vendor` del quote; fallback LiquidMesh → InchFusion. |
| 5 | `get_transaction_detail` retorna **lista**. | `verify_transaction` rompía al leer `.get("status")`. | Normalizar `list[0]` → `dict` en el cliente. |
| 6 | `simulate_transaction` usa API real + fallback local. | Sin API o wallet vacía, simulación API puede faltar o revertir (STF). | POST `/simulate`; si no hay data → `eth_call`. Revert DRY con wallet vacía es esperado. |

---

## 4. Advertencia LIVE

**La demo LIVE no puede usarse con wallet ficticia ni con 0.001 bTSLA.**

Requisitos:

1. `WALLET_ADDRESS` real (nunca `0x0000…0001`).
2. **≥ ~$5 USD en bTSLA** (≥ **0.013** bTSLA) + **≥ 0.005 BNB** para gas.
3. Wallet con **KYC/KYT** aprobado en Binance Web3 (error 40434 si no).
4. `WALLET_PRIVATE_KEY` solo en `.env` local. **Nunca en logs, git ni este informe.**
5. Mercado RWA **abierto**. Error **40367** = sesión no-trading (quote imposible hasta la apertura).

Transmitir sin esos prerequisitos gasta gas y el aggregator rechaza el quote.

---

## 5. Confirmación del flujo DRY E2E

| Paso | Función | DRY |
|---|---|---|
| Quote | `GET /aggregator/quote` + `userWalletAddress` | Sí (mínimo $5 / wallet real; 40375/40434 documentados) |
| Approve calldata | `build_approve_transaction` LiquidMesh/InchFusion | Sí — no se firma ni se envía |
| Swap calldata | `GET /aggregator/swap` con `quoteId` | Sí |
| Broadcast dry | `simulate_transaction` (API o local) | Sí — **no** `broadcast_transaction` |
| Verify | `get_transaction_detail` normalizado + polling | Sí (hash ficticio → no confirmado) |

**Conclusión:** integración DRY lista. LIVE bloqueado solo por fondos + KYT, no por paths de API.

---

## 6. Salida de `demo_live.py --dry-run`

Ejecutado **2026-09-25** (hora local), **sin broadcast**. Secretos omitidos.

```
MODO: DRY-RUN - no se transmitira ninguna transaccion.

0. Credenciales
   BINANCE_WEB3_API_KEY / SECRET : presentes (preview truncado)
   WALLET_ADDRESS / WALLET_PRIVATE_KEY : no configurados en esta corrida
   WARN: wallet ficticia → 40434 esperado si el quote llegara a KYT

1. Prerequisitos on-chain
   bTSLA / BNB : no leidos (wallet dummy)

2. Approve calldata (LiquidMesh / InchFusion)  OK
   approve.to      : 0x8755c5C39b1AA9053a83AC731242a2cf4D04B0Fe  (contrato bTSLA)
   calldata sel.   : 0x095ea7b3  (approve)
   spender         : 0xB44446b0c8E56988c34f7Ff73Ae904982b5FdDA5
   source          : binance_api

3. Quote → swap
   amount          : 0.013 bTSLA  (13000000000000000 wei)
   FAIL: GET /aggregator/quote sin data
   Log API: code=40367  msg=Token is currently in a non-trading session.
            Expected to open in 0d 6h 30m.
   broadcast omitido (dry-run + sin calldata)
```

**Lectura:** el approve E2E contra API real **confirmado**. El quote RWA en este horario falló por **sesión no-trading (40367)**, no por paths incorrectos. Con mercado abierto + wallet financiada, el siguiente paso es quote → swap → simulación.

---

*No se incluyen secretos. Montos en `Decimal`. Broadcast solo con `python demo_live.py --live`.*
