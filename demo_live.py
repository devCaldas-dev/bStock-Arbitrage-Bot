"""
Demo LIVE — swap bTSLA → USDT vía Binance Web3 Trading API.

Uso:
    python demo_live.py --dry-run    # quote, approve, swap, simulación; NO broadcast
    python demo_live.py --live       # transmite approve (si hace falta) y swap

Nunca imprime WALLET_PRIVATE_KEY. Montos en Decimal.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("demo_live")

env_path = Path(__file__).parent / ".env"
if env_path.exists():
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip())

from binance_web3_api import BinanceWeb3API
from config import DEFAULT_CHAIN_ID, USDT_ADDRESS
from executor import (
    ERC20_READ_ABI,
    build_approve_transaction,
    broadcast_signed_transaction,
    sign_transaction,
    simulate_transaction,
    verify_transaction,
)
from web3_price_fetcher import w3

BTSLA_CONTRACT = "0x8755c5c39b1aa9053a83ac731242a2cf4d04b0fe"
DUMMY_WALLET = "0x0000000000000000000000000000000000000001"
MIN_BTSLA = Decimal("0.013")
MIN_BNB = Decimal("0.005")
DECIMALS = Decimal(10**18)
BSCSCAN_TX = "https://bscscan.com/tx/{}"
SEPARATOR = "-" * 68


def _preview(value: str, keep: int = 6) -> str:
    if not value:
        return "—"
    if len(value) <= keep + 4:
        return value[:2] + "…"
    return f"{value[:keep]}…{value[-4:]}"


def _wei(amount: Decimal) -> str:
    return str(int(amount * DECIMALS))


def _from_wei(raw: int) -> Decimal:
    return Decimal(raw) / DECIMALS


def _first_dict(payload: Any) -> Optional[Dict[str, Any]]:
    if isinstance(payload, list):
        return payload[0] if payload and isinstance(payload[0], dict) else None
    if isinstance(payload, dict):
        return payload
    return None


def _decode_approve_spender(calldata: str) -> Optional[str]:
    if not calldata or not calldata.startswith("0x") or len(calldata) < 74:
        return None
    try:
        return w3.to_checksum_address("0x" + calldata[34:74])
    except Exception:
        return None


def _section(title: str) -> None:
    print(f"\n{SEPARATOR}\n  {title}\n{SEPARATOR}")


def load_env() -> Dict[str, str]:
    return {
        "api_key": os.getenv("BINANCE_WEB3_API_KEY", "").strip(),
        "api_secret": os.getenv("BINANCE_WEB3_API_SECRET", "").strip(),
        "wallet_pk": os.getenv("WALLET_PRIVATE_KEY", "").strip(),
        "wallet": os.getenv("WALLET_ADDRESS", "").strip(),
    }


def check_credentials(env: Dict[str, str]) -> bool:
    _section("0. Credenciales (preview truncado)")
    ok = True
    print(f"  BINANCE_WEB3_API_KEY    : {_preview(env['api_key'])}  {'OK' if env['api_key'] else 'FALTA'}")
    print(f"  BINANCE_WEB3_API_SECRET : {_preview(env['api_secret'], 4)}  {'OK' if env['api_secret'] else 'FALTA'}")
    print(f"  WALLET_ADDRESS          : {_preview(env['wallet'], 8)}  {'OK' if env['wallet'] else 'FALTA'}")
    print(f"  WALLET_PRIVATE_KEY      : {'presente (no se imprime)' if env['wallet_pk'] else 'FALTA'}")
    if not env["api_key"] or not env["api_secret"]:
        print("  WARN: sin API keys el quote/approve fallarán.")
        ok = False
    if env["wallet"].lower() in ("", DUMMY_WALLET.lower()):
        print("  WARN: wallet ficticia o vacía → error KYT 40434 esperado en quote.")
        ok = False
    return ok


def fetch_balances(wallet: str) -> Tuple[Optional[Decimal], Optional[Decimal]]:
    if not wallet or wallet.lower() == DUMMY_WALLET.lower():
        return None, None
    try:
        wallet_cs = w3.to_checksum_address(wallet)
        bnb = _from_wei(w3.eth.get_balance(wallet_cs))
        token = w3.eth.contract(
            address=w3.to_checksum_address(BTSLA_CONTRACT),
            abi=ERC20_READ_ABI,
        )
        btsla = _from_wei(token.functions.balanceOf(wallet_cs).call())
        return btsla, bnb
    except Exception as exc:
        logger.warning("No se pudieron leer balances on-chain: %s", exc)
        return None, None


def fetch_allowance(wallet: str, spender: Optional[str]) -> Optional[Decimal]:
    if not wallet or not spender or wallet.lower() == DUMMY_WALLET.lower():
        return None
    try:
        token = w3.eth.contract(
            address=w3.to_checksum_address(BTSLA_CONTRACT),
            abi=ERC20_READ_ABI,
        )
        raw = token.functions.allowance(
            w3.to_checksum_address(wallet),
            w3.to_checksum_address(spender),
        ).call()
        return _from_wei(raw)
    except Exception as exc:
        logger.warning("No se pudo leer allowance: %s", exc)
        return None


def two_step_quote_and_swap(
    api: BinanceWeb3API,
    amount: Decimal,
    wallet: str,
    slippage: str,
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """Flujo RWA: GET quote → GET swap (no quote-and-swap)."""
    amount_wei = _wei(amount)
    token_in = w3.to_checksum_address(BTSLA_CONTRACT)
    token_out = w3.to_checksum_address(USDT_ADDRESS)

    print(f"  amount          : {amount} bTSLA")
    print(f"  amount_wei      : {amount_wei}")
    print(f"  from            : {token_in}")
    print(f"  to              : {token_out}")
    print(f"  wallet          : {_preview(wallet, 8)}")

    quote_raw = api.get_aggregated_quote(
        chain_id=DEFAULT_CHAIN_ID,
        amount=amount_wei,
        from_token=token_in,
        to_token=token_out,
        slippage=slippage,
        wallet_address=wallet,
    )
    quote = _first_dict(quote_raw)
    if not quote:
        print("  FAIL: get_aggregated_quote sin data.")
        print("        40375 monto <$5 | 40434 KYT | 40465 quote expirado")
        print("        40367 sesion no-trading del token RWA (mercado cerrado).")
        return None, None

    quote_id = quote.get("quoteId") or quote.get("id") or ""
    vendor = quote.get("vendorName") or quote.get("vendor") or ""
    to_amount = quote.get("toAmount") or quote.get("estimatedToAmount")
    print(f"  quoteId         : {quote_id}")
    print(f"  vendor          : {vendor or '(auto)'}")
    print(f"  toAmount wei    : {to_amount}")

    if not quote_id:
        print("  FAIL: quote sin quoteId.")
        return quote, None

    swap_raw = api.build_swap_transaction(
        chain_id=DEFAULT_CHAIN_ID,
        amount=amount_wei,
        from_token=token_in,
        to_token=token_out,
        wallet_address=wallet,
        quote_id=quote_id,
        slippage=slippage,
    )
    swap = _first_dict(swap_raw)
    if not swap:
        print("  FAIL: aggregator/swap sin calldata. Re-quote inmediato (TTL ~30s / 40465).")
        return quote, None

    to_addr = swap.get("to") or swap.get("routerAddress") or ""
    data = swap.get("data") or swap.get("callData") or ""
    gas_val = swap.get("gas") or swap.get("estimatedGas") or 300_000
    print(f"  swap.to         : {to_addr}")
    print(f"  calldata sel.   : {data[:10] if data else '—'}")
    print(f"  gas             : {gas_val}")
    return quote, {
        "to": w3.to_checksum_address(to_addr) if to_addr else "",
        "data": data,
        "value": int(swap.get("value") or 0),
        "gas": int(gas_val),
        "token_in": token_in,
        "amount_in": int(amount_wei),
        "quote_id": quote_id,
        "vendor": vendor or swap.get("vendorName") or swap.get("vendor") or "",
        "source": "binance_api_two_step",
    }


def interpret_prereq(
    amount: Decimal,
    btsla: Optional[Decimal],
    bnb: Optional[Decimal],
    allowance: Optional[Decimal],
) -> bool:
    _section("1. Prerequisitos on-chain")
    ready = True
    if btsla is None:
        print(f"  bTSLA balance   : no leído (wallet dummy o RPC)")
        ready = False
    else:
        flag = "OK" if btsla >= amount else "INSUFICIENTE"
        print(f"  bTSLA balance   : {btsla}  umbral={amount}  [{flag}]")
        if btsla < amount:
            ready = False
            print("  → Error 40375 si el nocional < $5 USD. Depositar ≥ 0.013 bTSLA.")
    if bnb is None:
        print(f"  BNB balance     : no leído")
        ready = False
    else:
        flag = "OK" if bnb >= MIN_BNB else "INSUFICIENTE"
        print(f"  BNB balance     : {bnb}  umbral={MIN_BNB}  [{flag}]")
        if bnb < MIN_BNB:
            ready = False
    if allowance is None:
        print("  allowance       : pendiente (se evalúa tras construir approve)")
    else:
        flag = "OK" if allowance >= amount else "REQUIERE APPROVE"
        print(f"  allowance       : {allowance} bTSLA  [{flag}]")
    return ready


def run_flow(dry_run: bool, amount: Decimal, slippage: str, max_live_tx: int = 0) -> int:
    env = load_env()
    creds_ok = check_credentials(env)
    wallet = env["wallet"] or DUMMY_WALLET
    api = BinanceWeb3API()

    btsla, bnb = fetch_balances(wallet)
    prereq_ok = interpret_prereq(amount, btsla, bnb, None)

    _section("2. Approve calldata (LiquidMesh / InchFusion)")
    amount_wei = int(amount * DECIMALS)
    approve_tx = build_approve_transaction(
        token_contract=BTSLA_CONTRACT,
        amount_wei=amount_wei,
        chain_id=DEFAULT_CHAIN_ID,
        vendor=None,
    )
    spender = None
    if approve_tx:
        spender = _decode_approve_spender(approve_tx.get("data") or "")
        print(f"  approve.to      : {approve_tx.get('to')}")
        print(f"  calldata sel.   : {(approve_tx.get('data') or '')[:10]}")
        print(f"  spender         : {spender or '(no decodificado)'}")
        print(f"  source          : {approve_tx.get('source')}")
    else:
        print("  WARN: approve sin data. Probar vendor LiquidMesh/InchFusion y token soportado.")

    allowance = fetch_allowance(wallet, spender) if spender else None
    if allowance is not None:
        need_approve = allowance < amount
        print(f"  allowance on-chain: {allowance}  need_approve={need_approve}")
    else:
        need_approve = True
        print("  allowance on-chain: desconocida → se asume approve necesario en LIVE")

    _section("3. Quote → swap (dos pasos, RWA)")
    quote, swap_tx = two_step_quote_and_swap(api, amount, wallet, slippage)
    if not swap_tx:
        print("\n  Flujo detenido: sin calldata de swap. No hay broadcast.")
        print("  Codigos: 40375 monto | 40434 KYT | 40465 quoteId | 40367 mercado cerrado.")
        return 1 if not dry_run else 0

    _section("4. Simulación (API real + fallback local)")
    sim = simulate_transaction(swap_tx, from_address=wallet)
    print(f"  source          : {sim.get('source')}")
    print(f"  success         : {sim.get('success')}")
    print(f"  gas_estimate    : {sim.get('gas_estimate')}")
    if sim.get("revert_reason"):
        print(f"  revert          : {str(sim.get('revert_reason'))[:160]}")
        print("  (STF / insufficient / allowance es esperado si la wallet no está financiada)")

    if dry_run:
        _section("5. DRY-RUN — firma opcional, broadcast omitido")
        if env["wallet_pk"]:
            signed = sign_transaction(swap_tx)
            print(f"  sign_swap       : {'OK (raw no se imprime)' if signed else 'FAIL'}")
        else:
            print("  sign_swap       : omitido (WALLET_PRIVATE_KEY no configurada)")
        print("  broadcast       : OMITIDO (--dry-run)")
        print("  verify          : OMITIDO (--dry-run)")
        print(f"\n  BscScan (plantilla): {BSCSCAN_TX.format('<tx_hash>')}")
        print("  LIVE: python demo_live.py --live")
        if not creds_ok or not prereq_ok:
            print("  Prerequisitos incompletos: financiar wallet antes de --live.")
        print(f"\n{SEPARATOR}")
        return 0

    if not env["wallet_pk"]:
        print("  FAIL: --live requiere WALLET_PRIVATE_KEY.")
        return 1
    if not creds_ok or not prereq_ok:
        print("  FAIL: prerequisitos no cumplidos. Abortando para no gastar gas.")
        return 1
    if not sim.get("success"):
        print("  FAIL: simulación revertida. Abortando broadcast.")
        return 1

    # ── Preflight: verificar que max_live_tx cubre las txs necesarias ──────────
    tx_requeridas = (1 if need_approve and approve_tx else 0) + 1  # approve? + swap
    if tx_requeridas > max_live_tx:
        print(
            f"  ABORT: limite insuficiente: requiere {tx_requeridas} tx, "
            f"limite --max-live-tx={max_live_tx}. "
            f"Usa --max-live-tx {tx_requeridas} o superior."
        )
        return 1

    nonce = w3.eth.get_transaction_count(w3.to_checksum_address(wallet), "pending")
    approve_hash = None
    live_tx_count = 0  # contador de broadcasts efectivos

    if need_approve and approve_tx:
        _section("5. LIVE — approve → confirmación")
        # Segunda barrera: verificar contador antes de broadcast
        live_tx_count += 1
        if live_tx_count > max_live_tx:
            print(f"  ABORT: limite de transacciones alcanzado ({live_tx_count} > {max_live_tx}).")
            return 1
        signed_approve = sign_transaction(approve_tx, nonce=nonce)
        if not signed_approve:
            print("  FAIL: no se pudo firmar approve.")
            return 1
        approve_hash = broadcast_signed_transaction(signed_approve, wallet)
        print(f"  approve_hash    : {approve_hash}")
        if not approve_hash:
            print("  FAIL: broadcast approve.")
            return 1
        print(f"  BscScan         : {BSCSCAN_TX.format(approve_hash)}")
        verified = verify_transaction(approve_hash, DEFAULT_CHAIN_ID, max_polls=10, poll_interval_s=4)
        if not verified.get("success"):
            print("  FAIL: approve no confirmado. No se envía el swap.")
            return 1
        nonce += 1
    else:
        print("  approve         : skip (allowance suficiente)")

    _section("6. LIVE — swap → broadcast → verify")
    # Segunda barrera: verificar contador antes de broadcast
    live_tx_count += 1
    if live_tx_count > max_live_tx:
        print(f"  ABORT: limite de transacciones alcanzado ({live_tx_count} > {max_live_tx}).")
        return 1
    signed_swap = sign_transaction(swap_tx, nonce=nonce)
    if not signed_swap:
        print("  FAIL: no se pudo firmar swap.")
        return 1
    swap_hash = broadcast_signed_transaction(signed_swap, wallet)
    print(f"  swap_hash       : {swap_hash}")
    if not swap_hash:
        print("  FAIL: broadcast swap.")
        return 1
    print(f"  BscScan         : {BSCSCAN_TX.format(swap_hash)}")
    result = verify_transaction(swap_hash, DEFAULT_CHAIN_ID)
    print(f"  confirmed       : {result.get('confirmed')}")
    print(f"  success         : {result.get('success')}")
    print(f"  block           : {result.get('block')}")
    print(f"  gas_used        : {result.get('gas_used')}")
    print(f"\n  TX HASH         : {swap_hash}")
    print(f"  EXPLORER        : {BSCSCAN_TX.format(swap_hash)}")
    if approve_hash:
        print(f"  APPROVE         : {BSCSCAN_TX.format(approve_hash)}")
    print(f"\n{SEPARATOR}")
    return 0 if result.get("success") else 1


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Demo bTSLA->USDT Binance Web3 (BSC 56)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Simula sin transmitir (default)")
    mode.add_argument("--live", action="store_true", help="Transmite approve+swap a BSC Mainnet")
    parser.add_argument("--amount", type=str, default=str(MIN_BTSLA), help="bTSLA a swappear (Decimal, min 0.013)")
    parser.add_argument("--slippage", type=str, default="0.5", help="slippagePercent")
    parser.add_argument(
        "--max-live-tx",
        type=int,
        default=None,
        metavar="N",
        help="Límite de transacciones reales a transmitir (obligatorio con --live, entero > 0).",
    )
    args = parser.parse_args()

    # --live exige --max-live-tx explícito
    if args.live and args.max_live_tx is None:
        print(
            "ABORT: --live requiere --max-live-tx N (entero > 0).\n"
            "Ejemplo: python demo_live.py --live --max-live-tx 2\n"
            "Esto protege contra broadcasts no intencionados."
        )
        return 2
    if args.live and args.max_live_tx is not None and args.max_live_tx <= 0:
        print("ABORT: --max-live-tx debe ser un entero mayor que 0.")
        return 2

    max_live_tx: int = args.max_live_tx if args.max_live_tx is not None else 0

    amount = Decimal(args.amount)
    if amount < MIN_BTSLA:
        print(f"ABORT: amount={amount} < mínimo aggregator {MIN_BTSLA} bTSLA (~$5, error 40375).")
        return 1

    dry_run = not args.live
    if dry_run:
        print("MODO: DRY-RUN - no se transmitira ninguna transaccion.", flush=True)
    else:
        print("MODO: LIVE - se firmaran y transmitiran transacciones en BSC Mainnet.", flush=True)

    return run_flow(dry_run=dry_run, amount=amount, slippage=args.slippage, max_live_tx=max_live_tx)


if __name__ == "__main__":
    sys.exit(main())
