"""AdaptGroup VPN API client.

Encapsulates ALL communication with the AdaptGroup network API. No other
layer talks to the external service directly.

Important conventions (verified from docs):
  * Base URL:            settings.adaptgroup_base_url
  * Auth header:         X-Api-Key: <api_key>
  * Integration id:      api_key_id sent in the JSON body of every request
  * Subscription URL:    {base}/sub/{subscription_uuid}
  * Rate limit:          100 requests / 60s per api_key_id → 429

Field-name handling follows the official OpenAPI schema published from the
documentation page. A few legacy aliases remain in response parsing so old
tests/mocks and previously persisted payloads continue to work.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


# ── Exceptions ───────────────────────────────────────────────
class AdaptGroupError(Exception):
    """Base class for AdaptGroup API errors."""

    def __init__(self, message: str, status_code: int | None = None, payload: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload


class AdaptGroupBadRequest(AdaptGroupError):
    """400 — invalid request / inappropriate subscription state."""


class AdaptGroupAuthError(AdaptGroupError):
    """401 — bad API key."""


class AdaptGroupInsufficientFunds(AdaptGroupError):
    """402 — not enough balance on the integration."""


class AdaptGroupForbidden(AdaptGroupError):
    """403 — plan does not belong to this integration."""


class AdaptGroupNotFound(AdaptGroupError):
    """404 — object not found."""


class AdaptGroupValidationError(AdaptGroupError):
    """422 — invalid parameters."""


class AdaptGroupRateLimited(AdaptGroupError):
    """429 — rate limit exceeded."""


class AdaptGroupUnavailable(AdaptGroupError):
    """503 — external service temporarily unavailable."""


class AdaptGroupNetworkError(AdaptGroupError):
    """Network/timeout error — outcome of the request is UNKNOWN.

    For create/charge operations this MUST NOT be retried blindly because the
    request may have succeeded on the remote side.
    """


MIN_CUSTOM_RENEW_DAYS = 3


_STATUS_EXC: dict[int, type[AdaptGroupError]] = {
    400: AdaptGroupBadRequest,
    401: AdaptGroupAuthError,
    402: AdaptGroupInsufficientFunds,
    403: AdaptGroupForbidden,
    404: AdaptGroupNotFound,
    422: AdaptGroupValidationError,
    429: AdaptGroupRateLimited,
    503: AdaptGroupUnavailable,
}


# ── Helpers ──────────────────────────────────────────────────
def _first(data: dict[str, Any], *keys: str, default: Any = None) -> Any:
    """Return the first present, non-None value among candidate keys."""
    for k in keys:
        if k in data and data[k] is not None:
            return data[k]
    return default


@dataclass(slots=True)
class PlanDTO:
    """Normalized plan parsed tolerantly from /plans/list."""

    plan_uuid: str
    name: str
    purchase_price: float | None
    retail_price: float | None
    currency: str
    duration_days: int | None
    max_devices: int | None
    traffic_limit_bytes: int | None
    is_trial: bool
    is_active: bool
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def is_unlimited_traffic(self) -> bool:
        return self.traffic_limit_bytes is None or self.traffic_limit_bytes <= 0


# ── Client ───────────────────────────────────────────────────
class AdaptGroupVPNClient:
    """Async HTTP client for the AdaptGroup VPN API."""

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        api_key_id: str | None = None,
        timeout: float | None = None,
    ) -> None:
        self._base_url = (base_url or settings.adaptgroup_base_url).rstrip("/")
        self._api_key = api_key or settings.adaptgroup_api_key
        self._api_key_id = api_key_id or settings.adaptgroup_api_key_id
        self._timeout = timeout or settings.adaptgroup_timeout
        self._client: httpx.AsyncClient | None = None

    # ── lifecycle ────────────────────────────────────────────
    async def __aenter__(self) -> "AdaptGroupVPNClient":
        await self.start()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    async def start(self) -> None:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=httpx.Timeout(self._timeout),
                headers={"X-Api-Key": self._api_key, "Content-Type": "application/json"},
            )

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _ensure(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("AdaptGroupVPNClient is not started. Use 'async with' or start().")
        return self._client

    @property
    def _api_key_id_value(self) -> int | str:
        """OpenAPI declares api_key_id as integer; keep non-numeric test values usable."""
        try:
            return int(self._api_key_id)
        except (TypeError, ValueError):
            return self._api_key_id

    # ── low-level request ────────────────────────────────────
    async def _request(
        self,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        safe_retry: bool = False,
        max_attempts: int = 3,
    ) -> dict[str, Any]:
        """POST a JSON request, injecting api_key_id into the body.

        ``safe_retry`` enables a small bounded retry with backoff ONLY for
        idempotent read operations (status/list/devices). It is never enabled
        for create/charge operations — for those a network error surfaces as
        :class:`AdaptGroupNetworkError` with an UNKNOWN outcome.
        """
        client = self._ensure()
        body: dict[str, Any] = {"api_key_id": self._api_key_id_value}
        if payload:
            body.update(payload)

        attempt = 0
        while True:
            attempt += 1
            try:
                resp = await client.post(path, json=body)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                if safe_retry and attempt < max_attempts:
                    await asyncio.sleep(0.5 * attempt)
                    continue
                # Do not log payload (may carry external ids); never log keys.
                logger.warning("AdaptGroup network error on %s: %s", path, type(exc).__name__)
                raise AdaptGroupNetworkError(
                    f"Сетевая ошибка при обращении к AdaptGroup ({path})"
                ) from exc

            if resp.status_code == 429 and safe_retry and attempt < max_attempts:
                retry_after = float(resp.headers.get("Retry-After", "1") or 1)
                await asyncio.sleep(min(retry_after, 5.0))
                continue

            if resp.status_code in (200, 201):
                try:
                    return resp.json() if resp.content else {}
                except ValueError:
                    return {}

            self._raise_for_status(resp)

    def _raise_for_status(self, resp: httpx.Response) -> None:
        try:
            payload = resp.json()
        except ValueError:
            payload = resp.text
        message = self._extract_error_message(payload, resp.status_code)
        exc_cls = _STATUS_EXC.get(resp.status_code, AdaptGroupError)
        logger.warning("AdaptGroup API %s on %s", resp.status_code, resp.request.url.path)
        raise exc_cls(message, status_code=resp.status_code, payload=payload)

    @staticmethod
    def _extract_error_message(payload: Any, status_code: int) -> str:
        if isinstance(payload, dict):
            for key in ("message", "error", "detail", "title"):
                if payload.get(key):
                    return str(payload[key])
        return f"AdaptGroup API error (HTTP {status_code})"

    # ── public methods ───────────────────────────────────────
    async def list_plans(self) -> list[PlanDTO]:
        """POST /plans/list — returns all plans available to the integration."""
        data = await self._request("/plans/list", {}, safe_retry=True)
        items = self._extract_plan_items(data)
        return [self._parse_plan(item) for item in items]

    async def create_subscription(
        self, plan_uuid: str, external_user_id: str, idempotency_key: str
    ) -> dict[str, Any]:
        """POST /subs/create — charges the integration balance.

        NOT retried on network error (outcome unknown). The idempotency_key is
        sent as a header. The JSON body follows the official OpenAPI schema.
        """
        client = self._ensure()
        body = {
            "api_key_id": self._api_key_id_value,
            "plan_uuid": plan_uuid,
            "external_user_id": str(external_user_id),
        }
        try:
            resp = await client.post(
                "/subs/create",
                json=body,
                headers={"Idempotency-Key": idempotency_key},
            )
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            logger.warning("AdaptGroup network error on /subs/create: %s", type(exc).__name__)
            raise AdaptGroupNetworkError(
                "Сетевая ошибка при создании подписки — результат неизвестен"
            ) from exc
        if resp.status_code in (200, 201):
            return resp.json() if resp.content else {}
        self._raise_for_status(resp)
        return {}  # pragma: no cover

    async def renew_subscription(self, subscription_uuid: str, plan_uuid: str | None = None) -> dict[str, Any]:
        """POST /subs/renew — renew on the same (or given) plan."""
        payload: dict[str, Any] = {"subscription_uuid": subscription_uuid}
        if plan_uuid:
            payload["plan_uuid"] = plan_uuid
        return await self._charge_request("/subs/renew", payload)

    async def renew_subscription_custom(self, subscription_uuid: str, days: int) -> dict[str, Any]:
        """POST /subs/renew/custom — renew for a custom number of days."""
        if days < MIN_CUSTOM_RENEW_DAYS:
            raise AdaptGroupValidationError(
                f"Кастомное продление доступно минимум от {MIN_CUSTOM_RENEW_DAYS} дней",
                status_code=422,
            )
        payload = {"subscription_uuid": subscription_uuid, "custom_days": int(days)}
        return await self._charge_request("/subs/renew/custom", payload)

    async def upgrade_subscription(self, subscription_uuid: str, plan_uuid: str) -> dict[str, Any]:
        """POST /subs/upgrade — switch to a different plan."""
        payload = {"subscription_uuid": subscription_uuid, "new_plan_uuid": plan_uuid}
        return await self._charge_request("/subs/upgrade", payload)

    async def purchase_traffic(self, subscription_uuid: str, amount_gb: int) -> dict[str, Any]:
        """POST /subs/traffic — buy additional traffic."""
        payload = {"subscription_uuid": subscription_uuid, "gb_amount": int(amount_gb)}
        return await self._charge_request("/subs/traffic", payload)

    async def freeze_subscription(self, subscription_uuid: str) -> dict[str, Any]:
        """POST /subs/freeze."""
        return await self._request("/subs/freeze", {"subscription_uuid": subscription_uuid})

    async def unfreeze_subscription(self, subscription_uuid: str) -> dict[str, Any]:
        """POST /subs/unfreeze."""
        return await self._request("/subs/unfreeze", {"subscription_uuid": subscription_uuid})

    async def get_status(self, subscription_uuid: str) -> dict[str, Any]:
        """POST /subs/status — current subscription state."""
        return await self._request(
            "/subs/status", {"subscription_uuid": subscription_uuid}, safe_retry=True
        )

    async def get_devices(self, subscription_uuid: str) -> list[dict[str, Any]]:
        """POST /subs/devices — connected devices."""
        data = await self._request(
            "/subs/devices", {"subscription_uuid": subscription_uuid}, safe_retry=True
        )
        return self._extract_list(data, "devices", "items", "data")

    async def get_requests(
        self, subscription_uuid: str, page: int = 1, per_page: int = 20
    ) -> dict[str, Any]:
        """POST /subs/requests — connection request history (paginated)."""
        offset = max(page - 1, 0) * per_page
        return await self._request(
            "/subs/requests",
            {"subscription_uuid": subscription_uuid, "offset": offset, "limit": per_page},
            safe_retry=True,
        )

    async def delete_device(self, subscription_uuid: str, device_id: str | int) -> dict[str, Any]:
        """POST /subs/devices/delete — remove a device, freeing a slot."""
        return await self._request(
            "/subs/devices/delete",
            {"subscription_uuid": subscription_uuid, "device_id": int(device_id)},
        )

    # ── charge operations (no blind retry) ───────────────────
    async def _charge_request(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        """A balance-charging operation. Network errors are surfaced, never retried."""
        client = self._ensure()
        body = {"api_key_id": self._api_key_id_value, **payload}
        try:
            resp = await client.post(path, json=body)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            logger.warning("AdaptGroup network error on %s: %s", path, type(exc).__name__)
            raise AdaptGroupNetworkError(
                f"Сетевая ошибка при операции {path} — результат неизвестен"
            ) from exc
        if resp.status_code in (200, 201):
            return resp.json() if resp.content else {}
        self._raise_for_status(resp)
        return {}  # pragma: no cover

    # ── parsing helpers ──────────────────────────────────────
    @staticmethod
    def _extract_list(data: Any, *keys: str) -> list[dict[str, Any]]:
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for k in keys:
                v = data.get(k)
                if isinstance(v, list):
                    return v
        return []

    @classmethod
    def _extract_plan_items(cls, data: Any) -> list[dict[str, Any]]:
        return cls._extract_list(data, "plans", "items", "data", "result")

    @staticmethod
    def _parse_plan(item: dict[str, Any]) -> PlanDTO:
        """Map a raw OpenAPI PlanItem to PlanDTO, keeping legacy aliases."""
        plan_uuid = str(
            _first(item, "uuid", "id", "plan_id", "plan_uuid", default="")
        )
        name = str(_first(item, "name", "title", "plan_name", default="Тариф"))

        retail = _first(
            item, "retail_price_usd", "retail_price", "price", "sell_price", "user_price", "amount"
        )
        purchase = _first(item, "price_usd", "purchase_price", "cost", "buy_price", "base_price")
        currency = str(_first(item, "currency", "currency_code", default="USD"))

        duration = _first(item, "duration_days", "days", "period_days", "duration", "period")
        devices = _first(item, "max_devices", "devices", "device_limit", "devices_limit")

        # Traffic limit: try bytes first, else GB → bytes. None/0 = unlimited.
        traffic_bytes = _first(item, "traffic_limit_bytes", "traffic_bytes", "data_limit_bytes")
        if traffic_bytes is None:
            traffic_gb = _first(item, "traffic_limit_gb", "traffic_gb", "data_limit_gb", "traffic")
            if traffic_gb is not None:
                try:
                    traffic_bytes = int(float(traffic_gb) * (1024 ** 3))
                except (TypeError, ValueError):
                    traffic_bytes = None

        is_trial = bool(_first(item, "is_trial", "trial", "is_test", default=False))
        is_active = bool(_first(item, "is_active", "active", "enabled", default=True))

        def _to_float(v: Any) -> float | None:
            try:
                return float(v) if v is not None else None
            except (TypeError, ValueError):
                return None

        def _to_int(v: Any) -> int | None:
            try:
                return int(v) if v is not None else None
            except (TypeError, ValueError):
                return None

        return PlanDTO(
            plan_uuid=plan_uuid,
            name=name,
            purchase_price=_to_float(purchase),
            retail_price=_to_float(retail),
            currency=currency,
            duration_days=_to_int(duration),
            max_devices=_to_int(devices),
            traffic_limit_bytes=_to_int(traffic_bytes),
            is_trial=is_trial,
            is_active=is_active,
            raw=item,
        )


def build_client() -> AdaptGroupVPNClient:
    """Factory for a configured (not-yet-started) client."""
    return AdaptGroupVPNClient()
