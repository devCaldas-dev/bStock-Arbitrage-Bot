# Checklist de Demo en Vivo — bStock Arbitrage Bot
## BNB Hack: Tokenized Stocks Edition

> Completa estos pasos **en orden** antes y durante la demostración.  
> Requisitos actualizados tras validación DRY contra la API real (sep 2026).

---

## Requisitos reales (no negociables)

| Requisito | Valor | Si se ignora |
|---|---|---|
| Monto mínimo swap | **0.013 bTSLA (~$5 USD)** | Error **40375** — aggregator rechaza 0.001 (~$0.38) |
| Wallet | **Real**, KYC/KYT aprobado | Error **40434** — no usar `0x0000…0001` |
| Gas | **≥ 0.005 BNB** | Tx pendiente / out of gas |
| Flujo RWA | **approve → confirmación → quote → swap → broadcast → verify** | `quote-and-swap` atómico no sirve para bTokens |
| Quote TTL | ~30 s | Error **40465** — re-cotizar, no reutilizar `quoteId` |

`LIVE_TRADE_AMOUNT=0.013` (no 0.001 / 0.005).

---

## Errores de API — interpretación

| Código | Significado | Qué hacer en demo |
|---|---|---|
| **40375** | Nocional < mínimo (~$5 USD) | Subir a ≥ 0.013 bTSLA; no insistir con 0.001 |
| **40434** | KYT / wallet no elegible | Cambiar a wallet financiada con KYC/KYT Binance Web3. Dummy address siempre falla |
| **40465** | Quote inválido o **expirado** | Nuevo `GET /quote` inmediato y `GET /swap` con `quoteId` fresco |
| **40367** | Token RWA en **sesión no-trading** | Esperar apertura del mercado subyacente; el quote no llega aunque el monto y KYT estén bien |

---

## FASE 0 — Preparación (24 horas antes)

### 0.1 Wallet de demo
- [ ] Crear una wallet BSC **nueva y dedicada** (no la personal)
  ```bash
  python -c "from web3 import Web3; a=Web3().eth.account.create(); print('Address:', a.address); print('PK: [guardar offline, no pegar en chat]')"
  ```
- [ ] Completar **KYC/KYT** asociado a Binance Web3 para esa address
- [ ] Confirmar que **no** es `0x0000000000000000000000000000000000000001`

### 0.2 Financiar
- [ ] **BNB ≥ 0.005** (recomendado 0.02 para 2 approves + 2 swaps)
  ```
  Red     : BNB Smart Chain (BSC Mainnet)
  Chain ID: 56
  ```
- [ ] **bTSLA ≥ 0.013** (~$5). Recomendado **0.03** (cubre 2 swaps)
  - Contrato: `0x8755c5c39b1aa9053a83ac731242a2cf4d04b0fe`
- [ ] Verificar on-chain
  ```bash
  python demo_live.py --dry-run
  ```

### 0.3 Credenciales
- [ ] API Key Binance Web3 (RWA, Trading, Transaction, Wallet)
- [ ] `.env` (nunca al git):
  ```bash
  cp .env.example .env
  # BINANCE_WEB3_API_KEY / SECRET
  # WALLET_PRIVATE_KEY / WALLET_ADDRESS  (wallet REAL)
  # LIVE_MODE=false
  # LIVE_TRADE_AMOUNT=0.013
  # MAX_LIVE_TX_PER_SESSION=2
  ```
- [ ] `grep -n ".env" .gitignore` debe listar `.env`

---

## FASE 1 — Verificación técnica (2 horas antes)

### 1.1 Entorno
```bash
.\venv\Scripts\activate
pip install -r requirements.txt
python run_tests.py
# Esperado: Ran 26 tests / Status: OK
```

### 1.2 API RWA
```bash
python -c "
from binance_web3_api import BinanceWeb3API
api = BinanceWeb3API()
print('tokens', len(api.get_rwa_tokens('56') or []))
print(api.search_rwa_tokens('TSLA'))
"
```

### 1.3 DRY E2E (sin transmitir)
```bash
python validate_dry_run.py
python demo_live.py --dry-run --amount 0.013
```
- [ ] Quote dos pasos o error documentado 40375/40434
- [ ] Approve calldata con vendor LiquidMesh/InchFusion
- [ ] Simulación API o fallback local
- [ ] Línea `broadcast : OMITIDO (--dry-run)`

**No** usar `0.001` ni wallet dummy para la prueba de quote RWA.

---

## FASE 2 — Demo en vivo

### Orden de ejecución (obligatorio)

1. **Approve** ERC-20 al spender del aggregator (`vendor` = LiquidMesh o InchFusion)
2. **Esperar confirmación** (`verify_transaction`, status `1` en BscScan)
3. **Quote** `GET /api/v1/dex/aggregator/quote` (wallet real, amount ≥ 0.013)
4. **Swap calldata** `GET /api/v1/dex/aggregator/swap` con `quoteId` fresco
5. **Broadcast** signed swap
6. **Verify** `get_transaction_detail` (lista normalizada a dict)

No usar `quote-and-swap` para bTSLA/RWA.

### 2.1 Activar LIVE
```powershell
# PowerShell — no imprimir la private key
$env:LIVE_MODE="true"
$env:LIVE_TRADE_AMOUNT="0.013"
$env:MAX_LIVE_TX_PER_SESSION="2"
```

### 2.2 Comando de demo
```bash
python demo_live.py --live --amount 0.013 --slippage 0.5
```
El script aborta si saldo bTSLA < 0.013, BNB < 0.005, o simulación revertida.

Alternativa bot (1 ciclo):
```bash
python main.py 1
```
Asegurar `LIVE_TRADE_AMOUNT=0.013` en `.env`.

### 2.3 Ante el jurado
- Approve: `https://bscscan.com/tx/<approve_hash>` — Success, method `approve`
- Swap: `https://bscscan.com/tx/<swap_hash>` — bTSLA → USDT
```bash
python -c "from executor import verify_transaction; print(verify_transaction('0xSWAP_HASH'))"
```

---

## FASE 3 — Post-demo

- [ ] Revocar approve (`amount_wei=0`) si se usó allowance al router
- [ ] Retirar bTSLA/USDT/BNB residuales
- [ ] Vaciar `WALLET_PRIVATE_KEY` del `.env`
- [ ] `LIVE_MODE=false`

---

## Montos mínimos (tabla real)

| Ítem | Mínimo viable | Demo cómoda |
|---|---|---|
| BNB gas | **0.005 BNB** | 0.02 BNB |
| bTSLA | **0.013 (~$5)** | 0.03 |
| `LIVE_TRADE_AMOUNT` | **0.013** | 0.013–0.02 |
| Slippage | 0.5% | 0.5% |
| `MAX_LIVE_TX_PER_SESSION` | 1 | 2 |

---

## Comandos rápidos

```bash
python run_tests.py
python demo_live.py --dry-run
python demo_live.py --live --amount 0.013
```

---

*Actualizado tras validación DRY: mínimo $5, KYT 40434, flujo quote→swap, approve LiquidMesh/InchFusion.*
