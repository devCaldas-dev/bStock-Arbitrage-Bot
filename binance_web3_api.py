"""Cliente autenticado para la API oficial RWA de Binance Web3."""

import base64
import hashlib
import hmac
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union
from urllib.parse import urlencode

import requests
from requests.exceptions import RequestException, Timeout

from config import REQUEST_TIMEOUT

logger = logging.getLogger(__name__)


class BinanceWeb3API:
    """Cliente de los endpoints RWA autenticados con el esquema OC de Binance."""

    BASE_URL = "https://web3.binance.com/build"
    RWA_PRICE_ENDPOINT = "/api/v1/dex/market/rwa/price"
    RWA_SEARCH_ENDPOINT = "/api/v1/dex/market/rwa/search"
    RWA_TOKENS_ENDPOINT = "/api/v1/dex/market/rwa/tokens"
    RWA_UNDERLYING_ENDPOINT = "/api/v1/dex/market/rwa/underlying-market"

    # Endpoints Trading, Pre-transaction, Post-transaction y Wallet
    AGGREGATOR_QUOTE_ENDPOINT = "/api/v1/dex/aggregator/quote"
    AGGREGATOR_SWAP_ENDPOINT = "/api/v1/dex/aggregator/swap"
    AGGREGATOR_QUOTE_AND_SWAP_ENDPOINT = "/api/v1/dex/aggregator/quote-and-swap"
    APPROVE_TRANSACTION_ENDPOINT = "/api/v1/dex/aggregator/approve-transaction"
    GAS_PRICE_ENDPOINT = "/api/v1/dex/pre-transaction/gas-price"
    TRANSACTION_DETAIL_ENDPOINT = "/api/v1/dex/post-transaction/transaction-detail-by-txhash"
    TOKEN_BALANCES_ENDPOINT = "/api/v1/dex/balance/token-balances-by-address"

    def __init__(self, api_key: Optional[str] = None, api_secret: Optional[str] = None):
        self.api_key = (api_key if api_key is not None else os.getenv("BINANCE_WEB3_API_KEY", "")).strip()
        self.api_secret = (api_secret if api_secret is not None else os.getenv("BINANCE_WEB3_API_SECRET", "")).strip()
        self.timeout = REQUEST_TIMEOUT
        self._request_timestamp = ""

    @staticmethod
    def _build_timestamp() -> str:
        now = datetime.now(timezone.utc)
        return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"

    def _sign(self, method: str, request_path: str, body: str = "") -> str:
        """Firma Base64 del preHash definido por Binance Web3."""
        pre_hash = self._request_timestamp + method.upper() + request_path + body
        digest = hmac.new(
            self.api_secret.encode("utf-8"),
            pre_hash.encode("utf-8"),
            hashlib.sha256,
        ).digest()
        return base64.b64encode(digest).decode("utf-8")

    def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        json_data: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Construye la URL y requestPath con /build, y ejecuta la petición."""
        if not self.api_key or not self.api_secret:
            logger.warning("binance_web3_api_credentials_missing", extra={"endpoint": endpoint})
            return None

        clean_endpoint = "/" + endpoint.lstrip("/")
        query = urlencode(params or {}, doseq=True)
        request_path = "/build" + clean_endpoint + (f"?{query}" if query else "")
        body_str = json.dumps(json_data, separators=(",", ":")) if json_data is not None else ""
        self._request_timestamp = self._build_timestamp()
        headers = {
            "X-OC-APIKEY": self.api_key,
            "X-OC-TIMESTAMP": self._request_timestamp,
            "X-OC-SIGN": self._sign(method, request_path, body=body_str),
            "Accept": "application/json",
        }
        if json_data is not None:
            headers["Content-Type"] = "application/json"
        url = f"{self.BASE_URL}{clean_endpoint}{f'?{query}' if query else ''}"
        try:
            response = requests.request(
                method.upper(),
                url,
                headers=headers,
                data=body_str.encode("utf-8") if json_data is not None else None,
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                logger.error("binance_web3_api_invalid_payload", extra={"endpoint": endpoint})
                return None
            if payload.get("code") not in (None, 0, "0", "000000") or payload.get("success") is False:
                logger.error(
                    "binance_web3_api_rejected",
                    extra={"endpoint": endpoint, "code": payload.get("code"), "response_message": payload.get("msg")},
                )
            return payload
        except Timeout:
            logger.error("binance_web3_api_timeout", extra={"endpoint": endpoint, "timeout": self.timeout})
        except RequestException as error:
            logger.error("binance_web3_api_request_failed", extra={"endpoint": endpoint, "error": str(error)})
        except (TypeError, ValueError) as error:
            logger.error("binance_web3_api_invalid_json", extra={"endpoint": endpoint, "error": str(error)})
        return None

    @staticmethod
    def _data(payload: Optional[Dict[str, Any]]) -> Any:
        return payload.get("data") if payload else None

    def get_rwa_price(self, chain_id: str, contract_address: str) -> Optional[Any]:
        payload = self._request(
            "GET",
            self.RWA_PRICE_ENDPOINT,
            {"binanceChainId": chain_id, "tokenContractAddresses": contract_address},
        )
        return self._data(payload)

    def get_rwa_tokens(self, chain_id: str = "56") -> Optional[Any]:
        payload = self._request("GET", self.RWA_TOKENS_ENDPOINT, {"binanceChainId": chain_id})
        return self._data(payload)

    def search_rwa_tokens(self, keyword: str) -> Optional[Any]:
        payload = self._request("GET", self.RWA_SEARCH_ENDPOINT, {"keyword": keyword})
        return self._data(payload)

    def get_rwa_underlying_market(self, chain_id: str, contract_address: str) -> Optional[Any]:
        payload = self._request(
            "GET",
            self.RWA_UNDERLYING_ENDPOINT,
            {"binanceChainId": chain_id, "tokenContractAddress": contract_address},
        )
        return self._data(payload)

    def get_market_status(self) -> Optional[Any]:
        """Devuelve el estado incluido por el endpoint oficial de mercado subyacente."""
        payload = self._request("GET", self.RWA_UNDERLYING_ENDPOINT)
        return self._data(payload)

    def get_aggregated_quote(
        self,
        chain_id: str,
        amount: Union[int, str],
        from_token: str,
        to_token: str,
        slippage: str = "0.5",
        wallet_address: Optional[str] = None,
        vendor: Optional[str] = None,
    ) -> Optional[Any]:
        """Obtiene la mejor cotización agregada de DEX (GET /api/v1/dex/aggregator/quote)."""
        params: Dict[str, Any] = {
            "binanceChainId": str(chain_id),
            "amount": str(amount),
            "fromTokenAddress": from_token,
            "toTokenAddress": to_token,
            "slippagePercent": str(slippage),
        }
        if wallet_address:
            params["userWalletAddress"] = wallet_address
        if vendor:
            params["vendor"] = vendor
        payload = self._request("GET", self.AGGREGATOR_QUOTE_ENDPOINT, params=params)
        return self._data(payload)

    def build_swap_transaction(
        self,
        chain_id: str,
        amount: Union[int, str],
        from_token: str,
        to_token: str,
        wallet_address: str,
        quote_id: str,
        slippage: str = "0.5",
        vendor: Optional[str] = None,
    ) -> Optional[Any]:
        """Construye calldata de swap usando un quoteId previo (GET /api/v1/dex/aggregator/swap)."""
        params: Dict[str, Any] = {
            "binanceChainId": str(chain_id),
            "amount": str(amount),
            "fromTokenAddress": from_token,
            "toTokenAddress": to_token,
            "userWalletAddress": wallet_address,
            "quoteId": str(quote_id),
            "slippagePercent": str(slippage),
        }
        if vendor:
            params["vendor"] = vendor
        payload = self._request("GET", self.AGGREGATOR_SWAP_ENDPOINT, params=params)
        return self._data(payload)

    def quote_and_build_swap(
        self,
        chain_id: str,
        amount: Union[int, str],
        from_token: str,
        to_token: str,
        wallet_address: str,
        slippage: str = "0.5",
        vendor: Optional[str] = None,
    ) -> Optional[Any]:
        """Cotización y construcción atómica de swap (GET /api/v1/dex/aggregator/quote-and-swap)."""
        params: Dict[str, Any] = {
            "binanceChainId": str(chain_id),
            "amount": str(amount),
            "fromTokenAddress": from_token,
            "toTokenAddress": to_token,
            "userWalletAddress": wallet_address,
            "slippagePercent": str(slippage),
        }
        if vendor:
            params["vendor"] = vendor
        payload = self._request("GET", self.AGGREGATOR_QUOTE_AND_SWAP_ENDPOINT, params=params)
        return self._data(payload)

    def get_erc20_approve_transaction(
        self,
        chain_id: str,
        token_contract: str,
        approve_amount: Union[int, str],
        vendor: Optional[str] = None,
    ) -> Optional[Any]:
        """Obtiene calldata de aprobación ERC-20 (GET /api/v1/dex/aggregator/approve-transaction)."""
        params: Dict[str, Any] = {
            "binanceChainId": str(chain_id),
            "tokenContractAddress": token_contract,
            "approveAmount": str(approve_amount),
        }
        if vendor:
            params["vendor"] = vendor
        payload = self._request("GET", self.APPROVE_TRANSACTION_ENDPOINT, params=params)
        return self._data(payload)

    def get_gas_price(self, chain_id: str = "56") -> Optional[Any]:
        """Consulta el gasPrice actual de la red (GET /api/v1/dex/pre-transaction/gas-price)."""
        params = {"binanceChainId": str(chain_id)}
        payload = self._request("GET", self.GAS_PRICE_ENDPOINT, params=params)
        return self._data(payload)

    def get_transaction_detail(self, tx_hash: str, chain_id: str = "56") -> Optional[Any]:
        """Consulta detalle y estado de transacción por hash (GET /api/v1/dex/post-transaction/transaction-detail-by-txhash)."""
        params = {
            "binanceChainId": str(chain_id),
            "txHash": tx_hash,
        }
        payload = self._request("GET", self.TRANSACTION_DETAIL_ENDPOINT, params=params)
        data = self._data(payload)
        if isinstance(data, list) and data:
            return data[0]
        return data

    def get_token_balances(
        self,
        address: str,
        chain_id: str = "56",
        token_addresses: Optional[List[str]] = None,
    ) -> Optional[Any]:
        """Consulta balances de tokens para una wallet (POST /api/v1/dex/balance/token-balances-by-address)."""
        body: Dict[str, Any] = {
            "address": address,
            "binanceChainId": str(chain_id),
        }
        if token_addresses:
            body["tokenContractAddresses"] = token_addresses
        payload = self._request("POST", self.TOKEN_BALANCES_ENDPOINT, json_data=body)
        if not payload:
            params = {"address": address, "binanceChainId": str(chain_id)}
            payload = self._request("GET", "/api/v1/dex/wallet/token-balances", params=params)
        return self._data(payload)
