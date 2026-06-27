"""Helpers for branded photo screens."""
from __future__ import annotations

from pathlib import Path

from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    Message,
)

ASSETS_DIR = Path(__file__).resolve().parents[1] / "assets"
MAX_PHOTO_CAPTION = 1024

MAIN_IMAGE = ASSETS_DIR / "main.png"
BUY_IMAGE = ASSETS_DIR / "buy.png"
PROFILE_IMAGE = ASSETS_DIR / "profile.png"
TOPUP_IMAGE = ASSETS_DIR / "topup.png"
SUBSCRIPTIONS_IMAGE = ASSETS_DIR / "subscriptions.png"
TRANSACTIONS_IMAGE = ASSETS_DIR / "transactions.png"
PROMOCODE_IMAGE = ASSETS_DIR / "promocode.png"


async def answer_photo_screen(
    message: Message,
    image_path: Path,
    caption: str,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> Message:
    return await message.answer_photo(
        FSInputFile(image_path),
        caption=_clip_caption(caption),
        reply_markup=reply_markup,
    )


async def replace_with_photo_screen(
    callback: CallbackQuery,
    image_path: Path,
    caption: str,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> Message | None:
    """Replace callback message with a photo screen, editing in place when possible."""
    message = callback.message
    if message is None:
        return None
    media = InputMediaPhoto(media=FSInputFile(image_path), caption=_clip_caption(caption))
    if message.photo:
        try:
            await message.edit_media(media=media, reply_markup=reply_markup)
            return message
        except Exception:  # noqa: BLE001
            pass
    try:
        await message.edit_media(media=media, reply_markup=reply_markup)
        return message
    except Exception:  # noqa: BLE001
        try:
            await message.delete()
        except Exception:  # noqa: BLE001
            pass
        return await message.answer_photo(
            FSInputFile(image_path),
            caption=_clip_caption(caption),
            reply_markup=reply_markup,
        )


async def replace_with_text_screen(
    callback: CallbackQuery,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    """Replace callback message with text, editing caption for media messages."""
    message = callback.message
    if message is None:
        return
    is_media = bool(message.photo or message.video or message.animation or message.document)
    if is_media and len(text) > MAX_PHOTO_CAPTION:
        await _delete_and_answer(message, text, reply_markup)
        return
    try:
        await message.edit_text(text, reply_markup=reply_markup)
    except Exception:  # noqa: BLE001
        if is_media:
            try:
                await message.edit_caption(
                    caption=text,
                    reply_markup=reply_markup,
                )
                return
            except Exception:  # noqa: BLE001
                pass
        await _delete_and_answer(message, text, reply_markup)


def _clip_caption(caption: str) -> str:
    if len(caption) <= MAX_PHOTO_CAPTION:
        return caption
    return caption[: MAX_PHOTO_CAPTION - 20].rstrip() + "\n\n..."


async def _delete_and_answer(
    message: Message,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    try:
        await message.delete()
    except Exception:  # noqa: BLE001
        pass
    await message.answer(text, reply_markup=reply_markup)
