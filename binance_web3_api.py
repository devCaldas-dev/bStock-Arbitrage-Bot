"""Cliente autenticado para la API oficial RWA de Binance Web3."""

import base64
import hashlib
import hmac
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional
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
    ) -> Optional[Dict[str, Any]]:
        """Construye la URL y requestPath con /build, y ejecuta la petición."""
        if not self.api_key or not self.api_secret:
            logger.warning("binance_web3_api_credentials_missing", extra={"endpoint": endpoint})
            return None

        clean_endpoint = "/" + endpoint.lstrip("/")
        query = urlencode(params or {}, doseq=True)
        request_path = "/build" + clean_endpoint + (f"?{query}" if query else "")
        self._request_timestamp = self._build_timestamp()
        headers = {
            "X-OC-APIKEY": self.api_key,
            "X-OC-TIMESTAMP": self._request_timestamp,
            "X-OC-SIGN": self._sign(method, request_path),
            "Accept": "application/json",
        }
        url = f"{self.BASE_URL}{clean_endpoint}{f'?{query}' if query else ''}"
        try:
            response = requests.request(
                method.upper(),
                url,
                headers=headers,
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                logger.error("binance_web3_api_invalid_payload", extra={"endpoint": endpoint})
                return None
            if payload.get("code") not in (None, 0, "0") or payload.get("success") is False:
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
