"""AdaptGroup webhook route.

Security pipeline:
  1. (optional) IP allowlist check — a defence-in-depth layer, NOT the only one.
  2. HMAC-SHA256 signature verification over the RAW body, BEFORE JSON parsing,
     using hmac.compare_digest.
  3. Parse JSON, extract event type.
  4. Idempotent processing via WebhookService (dedup by event_key).
  5. Fast 200 response; user notifications dispatched after processing.
"""
from __future__ import annotations

from fastapi import APIRouter, Header, Request, Response

from app.bot.deps import get_payments
from app.core.config import settings
from app.core.enums import OrderStatus, PaymentStatus
from app.core.logging import get_logger
from app.core.security import verify_webhook_signature
from app.db.database import async_session_factory
from app.services.notifications import NotificationService
from app.services.orders import OrderService
from app.services.webhooks import WebhookService

logger = get_logger(__name__)

router = APIRouter()


def _client_ip(request: Request) -> str | None:
    # Honor X-Forwarded-For when behind a proxy; else peer address.
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else None


@router.post("/webhooks/adaptgroup")
async def adaptgroup_webhook(
    request: Request,
    x_webhook_signature: str | None = Header(default=None),
) -> Response:
    # 1. Optional IP allowlist (defence in depth, not sole protection).
    if settings.adaptgroup_webhook_allowed_ips:
        ip = _client_ip(request)
        if ip not in settings.adaptgroup_webhook_allowed_ips:
            logger.warning("Webhook rejected: IP %s not allowlisted", ip)
            return Response(status_code=403)

    # 2. Verify signature over the RAW body before parsing.
    raw_body = await request.body()
    if not verify_webhook_signature(
        settings.adaptgroup_webhook_secret, raw_body, x_webhook_signature
    ):
        logger.warning("Webhook rejected: invalid signature")
        return Response(status_code=401)

    # 3. Parse JSON.
    try:
        import json

        payload = json.loads(raw_body.decode("utf-8"))
    except Exception:  # noqa: BLE001
        logger.warning("Webhook rejected: invalid JSON")
        return Response(status_code=400)

    event_type = str(payload.get("event", "")) if isinstance(payload, dict) else ""
    if not event_type:
        return Response(status_code=400)

    # 4. Idempotent processing.
    bot = request.app.state.bot
    client = request.app.state.adaptgroup_client
    async with async_session_factory() as session:
        service = WebhookService(session, client)
        result, intent = await service.process(event_type, payload, raw_body)

        # 5. Dispatch user notification (only for freshly-processed events).
        if intent is not None and bot is not None:
            notifier = NotificationService(bot)
            await notifier.notify_event(
                intent.telegram_id,
                intent.event_type,
                intent.details,
            )

    logger.info("Webhook %s → %s", event_type, result)
    return Response(status_code=200)


@router.post("/webhooks/rollypay")
async def rollypay_webhook(request: Request) -> Response:
    raw_body = await request.body()
    provider = get_payments()
    try:
        result = await provider.handle_webhook(raw_body, dict(request.headers))
    except Exception as exc:  # noqa: BLE001
        logger.warning("RollyPay webhook rejected: %s", exc)
        return Response(status_code=403)

    if result.status != PaymentStatus.SUCCEEDED:
        logger.info("RollyPay webhook ignored: %s %s", result.event_type, result.status)
        return Response(status_code=200)

    bot = request.app.state.bot
    client = request.app.state.adaptgroup_client
    async with async_session_factory() as session:
        order_service = OrderService(session, client, provider)
        order = await order_service.orders.get_by_payment_id(result.payment_id)
        if order is None and result.order_uuid:
            order = await order_service.orders.get_by_uuid(result.order_uuid)
            if order is not None and not order.payment_id:
                order.payment_id = result.payment_id
                await session.flush()
        if order is None:
            logger.warning("RollyPay webhook for unknown payment %s", result.payment_id)
            return Response(status_code=200)

        if order.status == OrderStatus.PENDING:
            await order_service.orders.mark_paid(order, result.payment_id)
            await session.commit()

        outcome = await order_service.provision(order)
        if bot is not None and (outcome.provisioned or outcome.already_done):
            try:
                text = "✅ Оплата получена. VPN активирован."
                if outcome.subscription and outcome.subscription.subscription_url:
                    text += f"\n\n<code>{outcome.subscription.subscription_url}</code>"
                await bot.send_message(order.user.telegram_id, text)
            except Exception as exc:  # noqa: BLE001
                logger.info("Could not notify user about RollyPay payment: %s", exc)

    return Response(status_code=200)


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
