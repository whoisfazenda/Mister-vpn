"""Inline keyboard factories with optional colored ButtonStyle support.

aiogram added ``InlineKeyboardButton.style`` / ``ButtonStyle`` in newer Bot API
versions. We probe for availability once and degrade gracefully to plain
buttons if the running aiogram/Bot API does not support styles, so the bot
never crashes on environments without the feature.
"""
from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.bot.premium_emoji import EMOJI_IDS

# ── Detect ButtonStyle support ───────────────────────────────
try:  # pragma: no cover - depends on aiogram version
    from aiogram.enums import ButtonStyle  # type: ignore

    _STYLE_MAP = {
        "primary": ButtonStyle.PRIMARY,
        "success": ButtonStyle.SUCCESS,
        "danger": ButtonStyle.DANGER,
    }
except Exception:  # noqa: BLE001
    ButtonStyle = None  # type: ignore
    _STYLE_MAP = {}

# Does InlineKeyboardButton actually accept a 'style' field?
_BUTTON_SUPPORTS_STYLE = "style" in getattr(
    InlineKeyboardButton, "model_fields", {}
)
_BUTTON_SUPPORTS_CUSTOM_ICON = "icon_custom_emoji_id" in getattr(
    InlineKeyboardButton, "model_fields", {}
)
_BUTTON_ICON_BY_FALLBACK = {fallback: emoji_id for fallback, emoji_id in EMOJI_IDS.values()}
_MULTI_CHAR_EMOJI = sorted(_BUTTON_ICON_BY_FALLBACK, key=len, reverse=True)


def make_button(
    text: str, callback_data: str, style: str | None = None
) -> InlineKeyboardButton:
    """Create an inline button, applying a color style when supported.

    ``style`` is one of 'primary' | 'success' | 'danger' | None.
    """
    clean_text, icon_custom_emoji_id = _extract_button_icon(text)
    kwargs = {
        "text": clean_text,
        "callback_data": callback_data,
    }
    if icon_custom_emoji_id:
        kwargs["icon_custom_emoji_id"] = icon_custom_emoji_id
    if style and _BUTTON_SUPPORTS_STYLE and style in _STYLE_MAP:
        try:
            return InlineKeyboardButton(**kwargs, style=_STYLE_MAP[style])
        except Exception:  # noqa: BLE001 - never fail on style issues
            pass
    return InlineKeyboardButton(**kwargs)


def make_url_button(text: str, url: str) -> InlineKeyboardButton:
    clean_text, icon_custom_emoji_id = _extract_button_icon(text)
    kwargs = {"text": clean_text, "url": url}
    if icon_custom_emoji_id:
        kwargs["icon_custom_emoji_id"] = icon_custom_emoji_id
    return InlineKeyboardButton(**kwargs)


def make_copy_button(text: str, payload: str) -> InlineKeyboardButton:
    """A 'copy text' button when supported, else a no-op-style fallback.

    Telegram Bot API 7.x added ``copy_text``. If unsupported by the installed
    aiogram, we fall back to a callback button that re-sends the value.
    """
    copy_supported = "copy_text" in getattr(InlineKeyboardButton, "model_fields", {})
    if copy_supported:
        try:
            from aiogram.types import CopyTextButton  # type: ignore

            clean_text, icon_custom_emoji_id = _extract_button_icon(text)
            kwargs = {"text": clean_text, "copy_text": CopyTextButton(text=payload)}
            if icon_custom_emoji_id:
                kwargs["icon_custom_emoji_id"] = icon_custom_emoji_id
            return InlineKeyboardButton(**kwargs)
        except Exception:  # noqa: BLE001
            pass
    return make_button(text, "noop:copy")


def inline_keyboard(rows: list) -> InlineKeyboardMarkup:
    """Build a markup from a compact spec.

    Each row is a list of tuples ``(text, callback_data[, style])``.
    """
    kb_rows: list[list[InlineKeyboardButton]] = []
    for row in rows:
        kb_row: list[InlineKeyboardButton] = []
        for item in row:
            text = item[0]
            data = item[1]
            style = item[2] if len(item) > 2 else None
            kb_row.append(make_button(text, data, style))
        kb_rows.append(kb_row)
    return InlineKeyboardMarkup(inline_keyboard=kb_rows)


def _extract_button_icon(text: str) -> tuple[str, str | None]:
    """Move a leading known emoji into Bot API's custom button icon field."""
    if not _BUTTON_SUPPORTS_CUSTOM_ICON:
        return text, None
    stripped = text.lstrip()
    prefix_spaces = len(text) - len(stripped)
    for emoji in _MULTI_CHAR_EMOJI:
        if stripped.startswith(emoji):
            clean = stripped[len(emoji):].lstrip()
            if not clean:
                clean = stripped
            if prefix_spaces:
                clean = text[:prefix_spaces] + clean
            return clean, _BUTTON_ICON_BY_FALLBACK[emoji]
    return text, None
