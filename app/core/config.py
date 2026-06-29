"""Application configuration via pydantic-settings.

All secrets are loaded from environment / .env and never logged.
"""
from __future__ import annotations

from decimal import Decimal
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8-sig",
        extra="ignore",
        case_sensitive=False,
    )

    # ── Telegram ──────────────────────────────────────────────
    bot_token: str = Field(default="", alias="BOT_TOKEN")
    # Comma-separated env value; parsed lists are exposed via properties below.
    admin_ids_raw: str = Field(default="", alias="ADMIN_IDS")

    # ── Database ─────────────────────────────────────────────
    database_url: str = Field(
        default="postgresql+asyncpg://vpn_user:vpn_password@db:5432/vpn_db",
        alias="DATABASE_URL",
    )

    # ── AdaptGroup ───────────────────────────────────────────
    adaptgroup_base_url: str = Field(
        default="https://network-api.adaptgroup.app", alias="ADAPTGROUP_BASE_URL"
    )
    adaptgroup_api_key: str = Field(default="", alias="ADAPTGROUP_API_KEY")
    adaptgroup_api_key_id: str = Field(default="", alias="ADAPTGROUP_API_KEY_ID")
    adaptgroup_webhook_secret: str = Field(default="", alias="ADAPTGROUP_WEBHOOK_SECRET")
    adaptgroup_timeout: float = Field(default=20.0, alias="ADAPTGROUP_TIMEOUT")
    adaptgroup_webhook_allowed_ips_raw: str = Field(
        default="", alias="ADAPTGROUP_WEBHOOK_ALLOWED_IPS"
    )

    # ── Payments ─────────────────────────────────────────────
    payment_provider: str = Field(default="mock", alias="PAYMENT_PROVIDER")
    currency: str = Field(default="RUB", alias="CURRENCY")
    traffic_price_per_gb: Decimal = Field(default=Decimal("3"), alias="TRAFFIC_PRICE_PER_GB")
    adaptgroup_usd_to_rub_rate: Decimal = Field(
        default=Decimal("76.142857"), alias="ADAPTGROUP_USD_TO_RUB_RATE"
    )
    plan_markup_percent: Decimal = Field(default=Decimal("30"), alias="PLAN_MARKUP_PERCENT")
    min_balance_topup: Decimal = Field(default=Decimal("100"), alias="MIN_BALANCE_TOPUP")
    max_balance_topup: Decimal = Field(default=Decimal("50000"), alias="MAX_BALANCE_TOPUP")
    required_channel_id: str = Field(default="", alias="REQUIRED_CHANNEL_ID")
    required_channel_url: str = Field(default="", alias="REQUIRED_CHANNEL_URL")
    free_trial_plan_uuid: str = Field(default="", alias="FREE_TRIAL_PLAN_UUID")
    reminder_check_interval_seconds: int = Field(
        default=21600, alias="REMINDER_CHECK_INTERVAL_SECONDS"
    )
    device_monitor_interval_seconds: int = Field(
        default=60, alias="DEVICE_MONITOR_INTERVAL_SECONDS"
    )

    # ── RollyPay ─────────────────────────────────────────────
    rollypay_base_url: str = Field(default="https://rollypay.io", alias="ROLLYPAY_BASE_URL")
    rollypay_api_key: str = Field(default="", alias="ROLLYPAY_API_KEY")
    rollypay_terminal_id: str = Field(default="", alias="ROLLYPAY_TERMINAL_ID")
    rollypay_signing_secret: str = Field(default="", alias="ROLLYPAY_SIGNING_SECRET")
    rollypay_payment_method: str = Field(default="", alias="ROLLYPAY_PAYMENT_METHOD")
    rollypay_success_redirect_url: str = Field(default="", alias="ROLLYPAY_SUCCESS_REDIRECT_URL")
    rollypay_fail_redirect_url: str = Field(default="", alias="ROLLYPAY_FAIL_REDIRECT_URL")
    rollypay_timeout: float = Field(default=20.0, alias="ROLLYPAY_TIMEOUT")

    # ── YooKassa ─────────────────────────────────────────────
    yookassa_base_url: str = Field(default="https://api.yookassa.ru", alias="YOOKASSA_BASE_URL")
    yookassa_shop_id: str = Field(default="", alias="YOOKASSA_SHOP_ID")
    yookassa_secret_key: str = Field(default="", alias="YOOKASSA_SECRET_KEY")
    yookassa_return_url: str = Field(default="", alias="YOOKASSA_RETURN_URL")
    yookassa_timeout: float = Field(default=20.0, alias="YOOKASSA_TIMEOUT")

    # ── App ──────────────────────────────────────────────────
    dev_mode: bool = Field(default=False, alias="DEV_MODE")
    support_url: str = Field(default="https://t.me/your_support", alias="SUPPORT_URL")
    public_base_url: str = Field(default="", alias="PUBLIC_BASE_URL")
    webhook_host: str = Field(default="0.0.0.0", alias="WEBHOOK_HOST")
    webhook_port: int = Field(default=8080, alias="WEBHOOK_PORT")
    plans_cache_ttl: int = Field(default=300, alias="PLANS_CACHE_TTL")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    @staticmethod
    def _split_csv(value: object) -> list[str]:
        if value is None or value == "":
            return []
        if isinstance(value, (list, tuple)):
            return [str(x).strip() for x in value if str(x).strip()]
        return [p.strip() for p in str(value).split(",") if p.strip()]

    @property
    def admin_ids(self) -> list[int]:
        """Telegram admin IDs parsed from comma-separated ADMIN_IDS."""
        ids: list[int] = []
        for item in self._split_csv(self.admin_ids_raw):
            try:
                ids.append(int(item))
            except ValueError:
                continue
        return ids

    @property
    def adaptgroup_webhook_allowed_ips(self) -> list[str]:
        """Optional IP allowlist for AdaptGroup webhooks."""
        return self._split_csv(self.adaptgroup_webhook_allowed_ips_raw)

    @property
    def is_admin_configured(self) -> bool:
        return bool(self.admin_ids)

    def is_admin(self, telegram_id: int) -> bool:
        return telegram_id in self.admin_ids


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton."""
    return Settings()  # type: ignore[call-arg]


settings = get_settings()
