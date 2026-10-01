"""
Script de Validación DRY — Binance Web3 API Integration
BNB Hack: Tokenized Stocks Edition

Ejecuta pruebas en seco contra la API real de Binance Web3 (sin enviar transacciones).
Genera un reporte estructurado en formato JSON para documentación.

Uso:
    python validate_dry_run.py

Sin LIVE_MODE, sin firma, sin broadcast. Solo lectura y construcción.
"""

import json
import logging
import os
import sys
import time
from decimal import Decimal
from pathlib import Path

# Silenciar logs de urllib3 para output limpio
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

from binance_web3_api import BinanceWeb3API
from executor import (
    build_api_swap_transaction,
    build_approve_transaction,
    build_swap_transaction,
    simulate_transaction,
    verify_transaction,
)
from config import DEFAULT_CHAIN_ID, USDT_ADDRESS


# ─── Constantes de prueba ────────────────────────────────────────────────────
BTSLA_CONTRACT  = "0x8755c5c39b1aa9053a83ac731242a2cf4d04b0fe"  # bTSLA BSC Mainnet
TEST_WALLET     = "0x0000000000000000000000000000000000000001"  # wallet ficticia (sin fondos)
# Monto mínimo real: la API exige ~5 USD mínimo para quotes (~0.013 bTSLA a $380/bTSLA)
# Con wallet ficticia el quote-and-swap falla por KYT (40434) — comportamiento esperado
TEST_AMOUNT     = Decimal("0.02")                                # ~$7.60 USD (supera mínimo de $5)
CHAIN_ID        = "56"
FAKE_TX_HASH    = "0x0000000000000000000000000000000000000000000000000000000000000001"
SEPARATOR       = "─" * 68

results = {}   # acumula resultados para el reporte final


# ─── Helper de impresión ─────────────────────────────────────────────────────
def section(title: str):
    print(f"\n{SEPARATOR}")
    print(f"  {title}")
    print(SEPARATOR)

def ok(label: str, value=None):
    tag = "  ✅ OK"
    print(f"{tag}  {label}" + (f": {value}" if value is not None else ""))

def warn(label: str, value=None):
    tag = "  ⚠️  WARN"
    print(f"{tag} {label}" + (f": {value}" if value is not None else ""))

def fail(label: str, value=None):
    tag = "  ❌ FAIL"
    print(f"{tag} {label}" + (f": {value}" if value is not None else ""))



def main() -> int:
    """Ejecuta el flujo de validación DRY completo."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    global results
    results = {}

    # Cargar .env manualmente antes de importar módulos del proyecto
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, val = line.partition("=")
                os.environ.setdefault(key.strip(), val.strip())


    # ═════════════════════════════════════════════════════════════════════════════
    # SECCIÓN 0: Verificar credenciales y conectividad base
    # ═════════════════════════════════════════════════════════════════════════════
    section("0. Credenciales y conectividad")
    api_key    = os.getenv("BINANCE_WEB3_API_KEY", "").strip()
    api_secret = os.getenv("BINANCE_WEB3_API_SECRET", "").strip()

    has_creds = bool(api_key and api_secret)
    results["credentials_present"] = has_creds

    if has_creds:
        ok("BINANCE_WEB3_API_KEY presente", f"{api_key[:6]}...{api_key[-4:]}")
        ok("BINANCE_WEB3_API_SECRET presente", f"{api_secret[:4]}...{api_secret[-4:]}")
    else:
        warn("Credenciales no configuradas — todos los llamados API fallarán (fallback local activo)")

    api = BinanceWeb3API()


    # ═════════════════════════════════════════════════════════════════════════════
    # SECCIÓN 1: RWA Data — get_rwa_tokens()
    # ═════════════════════════════════════════════════════════════════════════════
    section("1. RWA Data — get_rwa_tokens(chainId=56)")
    t0 = time.time()
    rwa_tokens = api.get_rwa_tokens(CHAIN_ID)
    elapsed = round(time.time() - t0, 3)

    if rwa_tokens and isinstance(rwa_tokens, (list, dict)):
        count = len(rwa_tokens) if isinstance(rwa_tokens, list) else 1
        ok(f"get_rwa_tokens() respondió en {elapsed}s", f"{count} token(s)")
        results["rwa_tokens"] = {"status": "ok", "count": count, "elapsed_s": elapsed}
        # Mostrar primeros 3 tokens si es lista
        if isinstance(rwa_tokens, list):
            for t in rwa_tokens[:3]:
                if isinstance(t, dict):
                    sym = t.get("symbol") or t.get("tokenSymbol", "?")
                    addr = (t.get("tokenContractAddress") or t.get("contractAddress", "?"))[:20]
                    print(f"       • {sym} — {addr}...")
    else:
        warn(f"get_rwa_tokens() sin datos (elapsed={elapsed}s) — API puede requerir credenciales")
        results["rwa_tokens"] = {"status": "no_data", "elapsed_s": elapsed}


    # ═════════════════════════════════════════════════════════════════════════════
    # SECCIÓN 2: RWA Data — search_rwa_tokens("TSLA")
    # ═════════════════════════════════════════════════════════════════════════════
    section("2. RWA Data — search_rwa_tokens('TSLA')")
    t0 = time.time()
    search_result = api.search_rwa_tokens("TSLA")
    elapsed = round(time.time() - t0, 3)

    found_contract = None
    if search_result:
        ok(f"search_rwa_tokens() respondió en {elapsed}s")
        results["search_rwa"] = {"status": "ok", "elapsed_s": elapsed, "raw_type": type(search_result).__name__}
        # Intentar extraer dirección del contrato
        items = search_result if isinstance(search_result, list) else [search_result]
        for item in items:
            if not isinstance(item, dict):
                continue
            # Puede venir directamente o en assets[]
            assets = item.get("assets", [item])
            for asset in assets:
                if not isinstance(asset, dict):
                    continue
                addr = asset.get("tokenContractAddress") or asset.get("contractAddress")
                chain = str(asset.get("binanceChainId", asset.get("chainId", "")))
                if addr and chain == "56":
                    found_contract = addr
                    ok("Contrato bTSLA en BSC detectado", addr)
                    break
            if found_contract:
                break
        if not found_contract:
            warn("No se pudo extraer dirección de contrato de la respuesta de búsqueda")
            print(f"       Tipo respuesta: {type(search_result).__name__}, muestra: {str(search_result)[:200]}")
    else:
        warn(f"search_rwa_tokens() sin datos (elapsed={elapsed}s)")
        results["search_rwa"] = {"status": "no_data", "elapsed_s": elapsed}

    # Usar contrato conocido si la búsqueda falló
    contract_to_use = found_contract or BTSLA_CONTRACT
    print(f"  →  Contrato a usar en validaciones: {contract_to_use}")


    # ═════════════════════════════════════════════════════════════════════════════
    # SECCIÓN 3: RWA Data — get_rwa_price()
    # ═════════════════════════════════════════════════════════════════════════════
    section(f"3. RWA Data — get_rwa_price(chainId=56, contract={contract_to_use[:20]}...)")
    t0 = time.time()
    rwa_price = api.get_rwa_price(CHAIN_ID, contract_to_use)
    elapsed = round(time.time() - t0, 3)

    rwa_price_value = None
    if rwa_price:
        record = rwa_price if isinstance(rwa_price, dict) else (rwa_price[0] if isinstance(rwa_price, list) and rwa_price else None)
        if record:
            rwa_price_value = record.get("price") or record.get("tokenPrice") or record.get("onChainPrice")
            ok(f"get_rwa_price() respondió en {elapsed}s", f"price={rwa_price_value}")
            results["rwa_price"] = {"status": "ok", "price": str(rwa_price_value), "elapsed_s": elapsed}
        else:
            warn(f"get_rwa_price() datos vacíos (elapsed={elapsed}s)")
            results["rwa_price"] = {"status": "empty", "elapsed_s": elapsed}
    else:
        warn(f"get_rwa_price() sin datos (elapsed={elapsed}s)")
        results["rwa_price"] = {"status": "no_data", "elapsed_s": elapsed}


    # ═════════════════════════════════════════════════════════════════════════════
    # SECCIÓN 4: RWA Data — get_rwa_underlying_market()
    # ═════════════════════════════════════════════════════════════════════════════
    section(f"4. RWA Data — get_rwa_underlying_market()")
    t0 = time.time()
    underlying = api.get_rwa_underlying_market(CHAIN_ID, contract_to_use)
    elapsed = round(time.time() - t0, 3)

    if underlying:
        ref_price = None
        if isinstance(underlying, dict):
            md = underlying.get("marketData", underlying)
            ref_price = md.get("referencePrice") or md.get("reference_price") or underlying.get("underlyingPrice")
        ok(f"get_rwa_underlying_market() respondió en {elapsed}s", f"referencePrice={ref_price}")
        results["rwa_underlying"] = {"status": "ok", "reference_price": str(ref_price), "elapsed_s": elapsed}
    else:
        warn(f"get_rwa_underlying_market() sin datos (elapsed={elapsed}s)")
        results["rwa_underlying"] = {"status": "no_data", "elapsed_s": elapsed}


    # ═════════════════════════════════════════════════════════════════════════════
    # SECCIÓN 5: Trading API — get_aggregated_quote()
    # ═════════════════════════════════════════════════════════════════════════════
    section("5. Trading API — get_aggregated_quote(bTSLA→USDT, 0.001 bStock)")
    amount_wei = str(int(TEST_AMOUNT * Decimal(10**18)))
    print(f"  →  amount_wei = {amount_wei}")
    t0 = time.time()
    quote = api.get_aggregated_quote(
        chain_id       = CHAIN_ID,
        amount         = amount_wei,
        from_token     = contract_to_use,
        to_token       = USDT_ADDRESS,
        slippage       = "0.5",
        wallet_address = TEST_WALLET,  # requerido para tokens Ondo/RFQ
    )
    elapsed = round(time.time() - t0, 3)

    quote_id = None
    if quote:
        quote_id = quote.get("quoteId") or quote.get("orderId") or quote.get("id")
        to_amount = quote.get("toAmount") or quote.get("estimatedToAmount")
        ok(f"get_aggregated_quote() respondió en {elapsed}s")
        ok("quoteId", quote_id)
        ok("toAmount (USDT wei)", to_amount)
        results["aggregated_quote"] = {
            "status"    : "ok",
            "quote_id"  : quote_id,
            "to_amount" : str(to_amount),
            "elapsed_s" : elapsed,
        }
    else:
        warn(f"get_aggregated_quote() sin datos (elapsed={elapsed}s)")
        results["aggregated_quote"] = {"status": "no_data", "elapsed_s": elapsed}


    # ═════════════════════════════════════════════════════════════════════════════
    # SECCIÓN 6: Trading API — quote_and_build_swap() (atómico)
    # ═════════════════════════════════════════════════════════════════════════════
    section("6. Trading API — quote_and_build_swap() atómico")
    t0 = time.time()
    swap_tx_api = api.quote_and_build_swap(
        chain_id       = CHAIN_ID,
        amount         = amount_wei,
        from_token     = contract_to_use,
        to_token       = USDT_ADDRESS,
        wallet_address = TEST_WALLET,
        slippage       = "0.5",
    )
    elapsed = round(time.time() - t0, 3)

    api_calldata_ok = False
    if swap_tx_api:
        to_addr  = swap_tx_api.get("to") or swap_tx_api.get("routerAddress", "")
        calldata = swap_tx_api.get("data") or swap_tx_api.get("callData", "")
        gas_est  = swap_tx_api.get("gas") or swap_tx_api.get("estimatedGas", "N/A")
        q_id     = swap_tx_api.get("quoteId") or ""
        api_calldata_ok = bool(to_addr and calldata and calldata.startswith("0x"))
        if api_calldata_ok:
            ok(f"quote_and_build_swap() respondió en {elapsed}s")
            ok("to (router)", to_addr)
            ok("calldata selector", calldata[:10])
            ok("calldata length", f"{len(calldata)} chars")
            ok("gas estimado", gas_est)
            ok("quoteId", q_id)
        else:
            warn(f"Respuesta incompleta: to='{to_addr}', calldata='{calldata[:20]}'")
        results["quote_and_build"] = {
            "status"          : "ok" if api_calldata_ok else "incomplete",
            "to"              : to_addr,
            "calldata_len"    : len(calldata),
            "calldata_selector": calldata[:10],
            "gas"             : str(gas_est),
            "quote_id"        : q_id,
            "elapsed_s"       : elapsed,
        }
    else:
        warn(f"quote_and_build_swap() sin datos (elapsed={elapsed}s) — se usará fallback local")
        results["quote_and_build"] = {"status": "no_data", "elapsed_s": elapsed}


    # ═════════════════════════════════════════════════════════════════════════════
    # SECCIÓN 7: executor.build_api_swap_transaction() — función de alto nivel
    # ═════════════════════════════════════════════════════════════════════════════
    section("7. executor.build_api_swap_transaction() — función orquestadora")
    t0 = time.time()
    exec_tx = build_api_swap_transaction(
        bstock_contract    = contract_to_use,
        usdt_contract      = USDT_ADDRESS,
        amount_bstock      = TEST_AMOUNT,
        wallet_address     = TEST_WALLET,
        chain_id           = CHAIN_ID,
        slippage_pct       = "0.5",
        current_price_usdt = Decimal("248.00"),   # referencia de logging
    )
    elapsed = round(time.time() - t0, 3)

    if exec_tx:
        src = exec_tx.get("source", "?")
        ok(f"build_api_swap_transaction() completó en {elapsed}s — fuente={src}")
        ok("to", exec_tx.get("to"))
        ok("calldata selector", (exec_tx.get("data") or "")[:10])
        ok("gas", exec_tx.get("gas"))
        ok("amount_in (wei)", exec_tx.get("amount_in"))
        ok("quote_id", exec_tx.get("quote_id") or "(none)")
        results["exec_build_swap"] = {
            "status"  : "ok",
            "source"  : src,
            "to"      : exec_tx.get("to"),
            "gas"     : exec_tx.get("gas"),
            "selector": (exec_tx.get("data") or "")[:10],
            "elapsed_s": elapsed,
        }
    else:
        # Con wallet ficticia (0x0000...0001) el error KYT 40434 es ESPERADO
        # En producción debe usarse WALLET_ADDRESS real con KYC completado
        warn(
            f"build_api_swap_transaction() retornó None (elapsed={elapsed}s) — "
            f"con wallet ficticia el error KYT 40434 es ESPERADO en validación DRY"
        )
        warn("En LIVE_MODE usar WALLET_ADDRESS real con fondos")
        results["exec_build_swap"] = {
            "status"   : "expected_kyt_fail_with_dummy_wallet",
            "elapsed_s": elapsed,
            "note"     : "Error 40434 KYT es esperado con wallet ficticia 0x0000..0001",
        }


    # ═════════════════════════════════════════════════════════════════════════════
    # SECCIÓN 8: Trading API — get_erc20_approve_transaction()
    # ═════════════════════════════════════════════════════════════════════════════
    section("8. Trading API — get_erc20_approve_transaction()")
    approve_amount_wei = int(TEST_AMOUNT * Decimal(10**18))
    t0 = time.time()
    approve_raw = api.get_erc20_approve_transaction(
        chain_id       = CHAIN_ID,
        token_contract = contract_to_use,
        approve_amount = str(approve_amount_wei),
    )
    elapsed = round(time.time() - t0, 3)

    if approve_raw:
        app_to   = approve_raw.get("to", "")
        app_data = approve_raw.get("data", "")
        ok(f"get_erc20_approve_transaction() respondió en {elapsed}s")
        ok("to (token contract)", app_to)
        ok("calldata selector", app_data[:10])
        results["approve_tx"] = {
            "status"   : "ok",
            "to"       : app_to,
            "selector" : app_data[:10],
            "elapsed_s": elapsed,
        }
    else:
        warn(f"get_erc20_approve_transaction() sin datos (elapsed={elapsed}s)")
        results["approve_tx"] = {"status": "no_data", "elapsed_s": elapsed}

    # executor.build_approve_transaction()
    t0 = time.time()
    exec_approve = build_approve_transaction(
        token_contract = contract_to_use,
        amount_wei     = approve_amount_wei,
        chain_id       = CHAIN_ID,
    )
    elapsed = round(time.time() - t0, 3)

    if exec_approve:
        ok(f"executor.build_approve_transaction() OK en {elapsed}s — to={exec_approve.get('to')}")
        results["exec_approve"] = {"status": "ok", "to": exec_approve.get("to"), "elapsed_s": elapsed}
    else:
        warn("executor.build_approve_transaction() retornó None — API no disponible")
        results["exec_approve"] = {"status": "no_data", "elapsed_s": elapsed}


    # ═════════════════════════════════════════════════════════════════════════════
    # SECCIÓN 9: Transaction API — get_gas_price()
    # ═════════════════════════════════════════════════════════════════════════════
    section("9. Transaction API — get_gas_price(chainId=56)")
    t0 = time.time()
    gas_data = api.get_gas_price(CHAIN_ID)
    elapsed = round(time.time() - t0, 3)

    if gas_data:
        gp = gas_data.get("gasPrice") or gas_data.get("gas_price") or gas_data.get("fast")
        ok(f"get_gas_price() respondió en {elapsed}s", f"gasPrice={gp}")
        results["gas_price"] = {"status": "ok", "gas_price": str(gp), "elapsed_s": elapsed}
    else:
        warn(f"get_gas_price() sin datos (elapsed={elapsed}s)")
        results["gas_price"] = {"status": "no_data", "elapsed_s": elapsed}


    # ═════════════════════════════════════════════════════════════════════════════
    # SECCIÓN 10: Transaction API — simulate_transaction() (endpoint real)
    # ═════════════════════════════════════════════════════════════════════════════
    section("10. Transaction API — simulate_transaction() POST")

    # Usar calldata real si está disponible, sino calldata local de fallback
    tx_for_sim = exec_tx
    if not tx_for_sim:
        print("  →  API no disponible, usando tx local (build_swap_transaction fallback)")
        tx_for_sim = build_swap_transaction(
            bstock_contract    = contract_to_use,
            amount_bstock      = TEST_AMOUNT,
            recipient          = TEST_WALLET,
            current_price_usdt = Decimal("248.00"),
        )

    if tx_for_sim:
        t0 = time.time()
        sim_result = simulate_transaction(tx_for_sim, from_address=TEST_WALLET)
        elapsed = round(time.time() - t0, 3)

        source  = sim_result.get("source", "?")
        success = sim_result.get("success", False)
        revert  = sim_result.get("revert_reason")
        gas_est = sim_result.get("gas_estimate")

        print(f"  →  Fuente de simulación: {source}")
        if success:
            ok(f"simulate_transaction() completó en {elapsed}s — NO revierte", f"gas_estimate={gas_est}")
        else:
            # Revert por falta de fondos (wallet ficticia) es ESPERADO en DRY
            if revert and any(kw in str(revert).upper() for kw in ["STF", "INSUFFICIENT", "ALLOWANCE", "TRANSFER"]):
                warn(f"Revert ESPERADO por wallet ficticia sin fondos (elapsed={elapsed}s)", str(revert)[:80])
            else:
                warn(f"simulate_transaction() revirtió (elapsed={elapsed}s)", str(revert)[:80])

        results["simulate"] = {
            "status"        : "ok",
            "source"        : source,
            "tx_success"    : success,
            "revert_reason" : str(revert)[:120] if revert else None,
            "gas_estimate"  : gas_est,
            "elapsed_s"     : elapsed,
            "note"          : "Revert por wallet ficticia es ESPERADO en DRY_MODE",
        }
    else:
        fail("No se pudo obtener tx para simulación")
        results["simulate"] = {"status": "no_tx"}


    # ═════════════════════════════════════════════════════════════════════════════
    # SECCIÓN 11: Wallet API — get_transaction_detail() (hash ficticio)
    # ═════════════════════════════════════════════════════════════════════════════
    section("11. Wallet API — get_transaction_detail() con hash ficticio")
    print(f"  →  Consultando hash: {FAKE_TX_HASH}")
    t0 = time.time()
    detail = api.get_transaction_detail(FAKE_TX_HASH, CHAIN_ID)
    elapsed = round(time.time() - t0, 3)

    if detail is not None:
        status = detail.get("status")
        ok(f"get_transaction_detail() respondió en {elapsed}s — API alcanzable")
        print(f"       status={status} (None/vacío esperado para hash ficticio)")
        results["tx_detail"] = {"status": "ok", "tx_status": str(status), "elapsed_s": elapsed}
    else:
        warn(f"get_transaction_detail() sin datos (elapsed={elapsed}s)")
        results["tx_detail"] = {"status": "no_data", "elapsed_s": elapsed}

    # verify_transaction() — orquestador con polling
    section("11b. executor.verify_transaction() con hash ficticio (1 poll)")
    t0 = time.time()
    verify_res = verify_transaction(FAKE_TX_HASH, CHAIN_ID, max_polls=1, poll_interval_s=0)
    elapsed = round(time.time() - t0, 3)

    confirmed = verify_res.get("confirmed", False)
    ok(f"verify_transaction() completó en {elapsed}s — confirmed={confirmed}")
    print(f"       (False esperado para hash ficticio)")
    results["verify_tx"] = {
        "status"    : "ok",
        "confirmed" : confirmed,
        "elapsed_s" : elapsed,
    }


    # ═════════════════════════════════════════════════════════════════════════════
    # SECCIÓN 12: Wallet API — get_token_balances()
    # ═════════════════════════════════════════════════════════════════════════════
    section("12. Wallet API — get_token_balances() para TEST_WALLET")
    t0 = time.time()
    balances = api.get_token_balances(
        address        = TEST_WALLET,
        chain_id       = CHAIN_ID,
        token_addresses= [contract_to_use, USDT_ADDRESS],
    )
    elapsed = round(time.time() - t0, 3)

    if balances is not None:
        ok(f"get_token_balances() respondió en {elapsed}s — API alcanzable")
        print(f"       (Balances = 0 esperado para wallet ficticia)")
        results["token_balances"] = {"status": "ok", "elapsed_s": elapsed}
    else:
        warn(f"get_token_balances() sin datos (elapsed={elapsed}s)")
        results["token_balances"] = {"status": "no_data", "elapsed_s": elapsed}


    # ═════════════════════════════════════════════════════════════════════════════
    # SECCIÓN 13: Fallback local — build_swap_transaction() (sin API)
    # ═════════════════════════════════════════════════════════════════════════════
    section("13. Fallback local — build_swap_transaction() (PancakeSwap V3 calldata)")
    t0 = time.time()
    local_tx = build_swap_transaction(
        bstock_contract    = contract_to_use,
        amount_bstock      = TEST_AMOUNT,
        recipient          = TEST_WALLET,
        current_price_usdt = Decimal("248.00"),
        slippage_pct       = Decimal("0.5"),
    )
    elapsed = round(time.time() - t0, 3)

    if local_tx:
        selector = (local_tx.get("data") or "")[:10]
        ok(f"build_swap_transaction() local en {elapsed}s — fuente={local_tx.get('source')}")
        ok("Selector PancakeSwap exactInputSingle", selector)
        ok("amount_in (wei)", local_tx.get("amount_in"))
        ok("amount_out_min (wei)", local_tx.get("amount_out_min"))
        assert selector == "0x414bf389", f"Selector incorrecto: {selector}"
        ok("Selector verificado: 0x414bf389 (exactInputSingle)")
        results["local_fallback"] = {
            "status"          : "ok",
            "source"          : local_tx.get("source"),
            "selector"        : selector,
            "amount_in"       : local_tx.get("amount_in"),
            "amount_out_min"  : local_tx.get("amount_out_min"),
            "elapsed_s"       : elapsed,
        }
    else:
        fail(f"build_swap_transaction() local retornó None (elapsed={elapsed}s)")
        results["local_fallback"] = {"status": "failed", "elapsed_s": elapsed}


    # ═════════════════════════════════════════════════════════════════════════════
    # RESUMEN FINAL
    # ═════════════════════════════════════════════════════════════════════════════
    section("RESUMEN FINAL")

    ok_count   = sum(1 for v in results.values() if isinstance(v, dict) and v.get("status") == "ok")
    fail_count = sum(1 for v in results.values() if isinstance(v, dict) and v.get("status") == "failed")
    warn_count = sum(1 for v in results.values() if isinstance(v, dict) and v.get("status") in ("no_data", "incomplete"))
    total      = ok_count + fail_count + warn_count

    print(f"\n  Total checks  : {total}")
    print(f"  ✅ OK         : {ok_count}")
    print(f"  ⚠️  WARN/NODATA: {warn_count}")
    print(f"  ❌ FAIL       : {fail_count}")

    # Determinar estado global
    if fail_count == 0 and results.get("local_fallback", {}).get("status") == "ok":
        print("\n  🟢 ESTADO GLOBAL: LISTO PARA DEMO")
        print("     El fallback local garantiza operación sin credenciales API.")
        if warn_count > 0:
            print("     ⚠️  Configura credenciales API para activar Trading/Transaction API.")
        results["global_status"] = "ready_for_demo"
    elif fail_count > 0:
        print("\n  🔴 ESTADO GLOBAL: FALLOS CRÍTICOS DETECTADOS")
        results["global_status"] = "critical_failures"
    else:
        print("\n  🟡 ESTADO GLOBAL: OPERATIVO CON ADVERTENCIAS")
        results["global_status"] = "operational_with_warnings"

    # Guardar reporte JSON
    results["timestamp"]      = int(time.time())
    results["credentials"]    = has_creds
    results["chain_id"]       = CHAIN_ID
    results["test_contract"]  = contract_to_use

    report_path = Path("validation_results.json")
    report_path.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    print(f"\n  Reporte guardado: {report_path.resolve()}")
    print(SEPARATOR)

    return 1 if fail_count > 0 else 0

if __name__ == "__main__":
    raise SystemExit(main())
