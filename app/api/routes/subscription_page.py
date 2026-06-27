"""Public subscription management page.

The page treats the subscription UUID as a bearer link. It never exposes the
AdaptGroup API key to the browser: device listing/deletion happens server-side.
"""
from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.clients.adaptgroup import _first
from app.db.database import async_session_factory
from app.db.models.subscription import VPNSubscription
from app.repositories.subscriptions import SubscriptionRepository
from app.services.subscriptions import SubscriptionService
from app.utils.formatting import format_date, format_gb_used

router = APIRouter()


@router.get("/s/{subscription_uuid}", response_class=HTMLResponse)
async def subscription_page(request: Request, subscription_uuid: str) -> HTMLResponse:
    deleted = request.query_params.get("deleted") == "1"
    error = request.query_params.get("error") or ""
    async with async_session_factory() as session:
        service = SubscriptionService(session, request.app.state.adaptgroup_client)
        sub = await SubscriptionRepository(session).get_by_uuid(subscription_uuid)
        if sub is None:
            sub = VPNSubscription(subscription_uuid=subscription_uuid, user_id=0)
        try:
            status = await request.app.state.adaptgroup_client.get_status(subscription_uuid)
            service.apply_status_payload(sub, status)
            if sub.id:
                await session.commit()
        except Exception:  # noqa: BLE001
            pass
        try:
            devices = await service.get_devices(sub)
        except Exception:  # noqa: BLE001
            devices = []
            if not error:
                error = "Не удалось загрузить устройства. Попробуйте позже."

    return HTMLResponse(_render_page(sub, devices, deleted=deleted, error=error))


@router.post("/s/{subscription_uuid}/devices/{device_id}/delete")
async def delete_subscription_device(
    request: Request,
    subscription_uuid: str,
    device_id: int,
) -> RedirectResponse:
    async with async_session_factory() as session:
        service = SubscriptionService(session, request.app.state.adaptgroup_client)
        sub = await SubscriptionRepository(session).get_by_uuid(subscription_uuid)
        if sub is None:
            sub = VPNSubscription(subscription_uuid=subscription_uuid, user_id=0)
        try:
            await service.delete_device(sub, str(device_id))
        except Exception:  # noqa: BLE001
            url = f"/s/{quote(subscription_uuid)}?error={quote('Не удалось удалить устройство')}"
            return RedirectResponse(url, status_code=303)
    return RedirectResponse(f"/s/{quote(subscription_uuid)}?deleted=1", status_code=303)


def _render_page(
    sub: VPNSubscription,
    devices: list[dict[str, Any]],
    *,
    deleted: bool,
    error: str,
) -> str:
    sub_url = _safe_url(sub.subscription_url) or ""
    status = (
        "Истекла"
        if sub.is_expired
        else "Заморожена"
        if sub.is_frozen
        else "Активна"
        if sub.is_active
        else "Неактивна"
    )
    days_left = _days_left(sub.expires_at)
    used_devices = len(devices)
    max_devices = sub.max_devices or used_devices or 0
    free_devices = max(max_devices - used_devices, 0) if max_devices else 0
    qr_url = (
        "https://api.qrserver.com/v1/create-qr-code/?size=260x260&data="
        + quote(sub_url)
        if sub_url
        else ""
    )
    device_rows = "".join(_render_device_row(sub.subscription_uuid, d) for d in devices)
    if not device_rows:
        device_rows = '<p class="muted">Пока нет подключённых устройств.</p>'

    flash = ""
    if deleted:
        flash = '<div class="flash ok">Устройство удалено. Слот освобождён.</div>'
    elif error:
        flash = f'<div class="flash err">{_e(error)}</div>'

    return f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Mister VPN - подписка</title>
  <style>
    :root {{
      color-scheme: dark;
      --bg:#050505; --card:#101010; --soft:#181818; --line:#2a2a2a;
      --text:#f4f4f4; --muted:#8d8d8d; --ok:#16c784; --danger:#ef4444;
    }}
    * {{ box-sizing:border-box }}
    body {{
      margin:0; background:var(--bg); color:var(--text);
      font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif;
      overflow-x:hidden;
    }}
    body::before {{
      content:""; position:fixed; inset:0; pointer-events:none; z-index:-3;
      background:
        radial-gradient(circle at 14% 84%, rgba(255,255,255,.08), transparent 24%),
        radial-gradient(circle at 88% 80%, rgba(255,255,255,.07), transparent 22%);
    }}
    .wrap {{ width:min(620px,100%); margin:0 auto; padding:24px 14px 38px }}
    .brand {{ display:flex; align-items:center; gap:12px; margin-bottom:28px; font-weight:800 }}
    .logo {{ width:40px; height:40px; border-radius:12px; display:grid; place-items:center;
      background:linear-gradient(180deg,#fff,#8b8b8b); color:#050505; font-weight:900 }}
    .hero {{ text-align:center; padding:8px 0 26px }}
    .mark {{ width:70px; height:70px; margin:0 auto 16px; border-radius:22px; display:grid;
      place-items:center; background:radial-gradient(circle,#3b3b3b,#111);
      box-shadow:0 0 44px rgba(255,255,255,.14); color:#fff; font-size:30px }}
    h1 {{ margin:0; font-size:38px; line-height:1.04; letter-spacing:-.01em }}
    .subtitle {{ color:var(--muted); margin:10px 0 0; line-height:1.45 }}
    .card {{
      border:1px solid var(--line); border-radius:20px; background:var(--card);
      padding:22px 24px; margin:14px 0;
    }}
    .card h2 {{ margin:0 0 16px; font-size:14px; color:var(--muted);
      text-transform:uppercase; letter-spacing:.08em }}
    .status {{ display:inline-flex; padding:7px 12px; border-radius:999px;
      background:rgba(22,199,132,.12); color:var(--ok); font-weight:800; font-size:13px }}
    .big {{ display:block; margin:8px 0 4px; font-size:40px; font-weight:900 }}
    .muted {{ color:var(--muted) }}
    .stats {{ display:grid; grid-template-columns:1fr 1fr; gap:12px }}
    .mini {{ border:1px solid var(--line); border-radius:16px; background:var(--soft); padding:14px }}
    .mini b {{ display:block; font-size:24px; margin-top:5px }}
    .copybox {{ border:1px solid var(--line); border-radius:14px; background:#080808;
      padding:14px; min-height:50px; word-break:break-all; font:13px ui-monospace,Consolas,monospace }}
    .btn {{ width:100%; min-height:48px; border:1px solid #3a3a3a; border-radius:14px;
      background:#1a1a1a; color:#fff; font-weight:850; cursor:pointer; text-decoration:none;
      display:flex; align-items:center; justify-content:center; gap:8px; margin-top:10px }}
    .btn.primary {{ background:linear-gradient(180deg,#fff,#b7b7b7); color:#050505 }}
    .btn.danger {{ background:rgba(239,68,68,.12); border-color:rgba(239,68,68,.35); color:#ffb4b4 }}
    .tabs {{ display:flex; gap:8px; flex-wrap:wrap; margin:0 0 14px }}
    .tab {{
      border:1px solid var(--line); background:var(--soft); color:var(--muted);
      min-height:42px; border-radius:13px; padding:0 14px; font-weight:850; cursor:pointer;
    }}
    .tab.active {{ background:#f5f5f5; color:#050505; border-color:#f5f5f5 }}
    .app-layout {{ display:grid; grid-template-columns:170px 1fr; gap:14px; align-items:start }}
    .app-list {{ display:grid; gap:8px }}
    .app-choice {{
      border:1px solid var(--line); background:var(--soft); color:#fff; border-radius:14px;
      min-height:46px; padding:0 13px; font-weight:850; text-align:left; cursor:pointer;
    }}
    .app-choice.active {{ background:#f5f5f5; color:#050505; border-color:#f5f5f5 }}
    .app-panel {{ border:1px solid var(--line); border-radius:16px; background:var(--soft); padding:17px }}
    .app-panel h3 {{ margin:0; font-size:21px }}
    .steps {{ margin:10px 0 0; padding:0; list-style:none; color:var(--muted); line-height:1.7 }}
    .steps li::before {{ content:counter(step); counter-increment:step; display:inline-grid;
      place-items:center; width:20px; height:20px; margin-right:10px; border:1px solid var(--line);
      border-radius:50%; font-size:12px; color:#bdbdbd }}
    .steps {{ counter-reset:step }}
    .device {{ border-top:1px solid var(--line); padding:14px 0 }}
    .device:first-child {{ border-top:0; padding-top:0 }}
    .device-title {{ display:flex; justify-content:space-between; gap:12px; font-weight:850 }}
    .flash {{ border-radius:14px; padding:12px 14px; margin:0 0 14px; font-weight:800 }}
    .flash.ok {{ background:rgba(22,199,132,.12); color:#a9ffd9 }}
    .flash.err {{ background:rgba(239,68,68,.12); color:#ffc1c1 }}
    .qr {{ display:grid; place-items:center; padding:14px; border:1px solid var(--line);
      border-radius:16px; background:#fff; margin-top:12px }}
    .qr img {{ width:min(220px,100%); display:block }}
    @media (max-width:540px) {{
      .stats {{ grid-template-columns:1fr }} h1 {{ font-size:32px }} .card {{ padding:18px }}
      .app-layout {{ grid-template-columns:1fr }}
      .app-list {{ grid-template-columns:1fr 1fr }}
    }}
  </style>
</head>
<body>
  <main class="wrap">
    <div class="brand"><div class="logo">M</div><div>mistervpn</div></div>
    {flash}
    <section class="hero">
      <div class="mark">◆</div>
      <p class="muted">Подписка активна до <b>{_e(format_date(sub.expires_at))}</b></p>
      <h1>Выберите приложение</h1>
      <p class="subtitle">Скопируйте ключ или добавьте его в приложение вручную. Ниже есть QR-код и управление устройствами.</p>
    </section>

    <section class="card">
      <div style="display:flex;justify-content:space-between;gap:12px;align-items:start">
        <div>
          <h2>Подписка</h2>
          <div class="muted">{_e(sub.plan_name or 'VPN')}</div>
          <span class="big">{_e(_date_short(sub.expires_at))}</span>
          <div class="muted">{_e(days_left)} осталось</div>
        </div>
        <span class="status">{_e(status)}</span>
      </div>
    </section>

    <section class="card">
      <h2>Ссылка</h2>
      <div class="copybox" id="subUrl">{_e(sub_url or 'Ссылка пока недоступна')}</div>
      <button class="btn primary" onclick="copySub()">Скопировать ссылку</button>
      {f'<div class="qr"><img src="{qr_url}" alt="QR-код подписки"></div>' if qr_url else ''}
    </section>

    <section class="card stats">
      <div class="mini"><span class="muted">Устройства</span><b>{used_devices} / {max_devices or '—'}</b></div>
      <div class="mini"><span class="muted">Свободно</span><b>{free_devices if max_devices else '—'}</b></div>
      <div class="mini"><span class="muted">Трафик</span><b>{_e(format_gb_used(sub.traffic_used_bytes, sub.traffic_limit_bytes))}</b></div>
      <div class="mini"><span class="muted">Статус</span><b>{_e(status)}</b></div>
    </section>

    <section class="card">
      <h2>Устройства</h2>
      {device_rows}
    </section>

    <section class="card">
      <h2>Приложения</h2>
      {_apps_section()}
    </section>
  </main>
  <script>
    const subUrl = {json.dumps(sub_url)};
    async function copySub() {{
      if (!subUrl) return;
      try {{
        await navigator.clipboard.writeText(subUrl);
        toast("Ссылка скопирована");
      }} catch (e) {{
        prompt("Скопируйте ссылку:", subUrl);
      }}
    }}
    function toast(text) {{
      const el = document.createElement("div");
      el.textContent = text;
      el.style.cssText = "position:fixed;left:50%;bottom:22px;transform:translateX(-50%);padding:11px 15px;border-radius:999px;background:#fff;color:#000;font-weight:850;z-index:50";
      document.body.appendChild(el);
      setTimeout(() => el.remove(), 1600);
    }}
    const apps = {_apps_json()};
    let currentPlatform = "iphone";
    let currentApp = 0;
    function renderApps() {{
      const platform = apps[currentPlatform];
      const platformTabs = document.getElementById("platformTabs");
      const appTabs = document.getElementById("appTabs");
      const panel = document.getElementById("appPanel");
      platformTabs.innerHTML = Object.entries(apps).map(([key, value]) =>
        `<button class="tab ${{key === currentPlatform ? "active" : ""}}" onclick="currentPlatform='${{key}}';currentApp=0;renderApps()">${{value.label}}</button>`
      ).join("");
      appTabs.innerHTML = platform.items.map((item, index) =>
        `<button class="app-choice ${{index === currentApp ? "active" : ""}}" onclick="currentApp=${{index}};renderApps()">${{item.name}}</button>`
      ).join("");
      const app = platform.items[currentApp] || platform.items[0];
      panel.innerHTML = `
        <h3>${{app.name}}</h3>
        <p class="muted">${{app.lead}}</p>
        <ol class="steps">${{app.steps.map(step => `<li>${{step}}</li>`).join("")}}</ol>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:14px">
          <button class="btn primary" onclick="copySub()">Скопировать ссылку</button>
          <a class="btn" href="${{app.download}}" target="_blank" rel="noopener">Скачать</a>
        </div>
      `;
    }}
    renderApps();
  </script>
</body>
</html>"""


def _render_device_row(subscription_uuid: str, device: dict[str, Any]) -> str:
    raw_id = _first(device, "id", "device_id", default="")
    try:
        device_id = int(raw_id)
    except (TypeError, ValueError):
        device_id = 0
    name = _e(device.get("name") or device.get("device_model") or "Устройство")
    os_name = _e(device.get("device_os") or "—")
    ip = _e(device.get("ip_address") or "—")
    last_seen = _e(device.get("last_seen") or "—")
    button = ""
    if device_id:
        action = f"/s/{quote(subscription_uuid)}/devices/{device_id}/delete"
        button = f"""
        <form method="post" action="{action}" onsubmit="return confirm('Удалить это устройство?')">
          <button class="btn danger" type="submit">Удалить устройство</button>
        </form>"""
    return f"""
      <div class="device">
        <div class="device-title"><span>{name}</span><span class="muted">{os_name}</span></div>
        <div class="muted">IP: {ip}<br>Последняя активность: {last_seen}</div>
        {button}
      </div>"""


def _apps_section() -> str:
    return """
      <div class="tabs" id="platformTabs"></div>
      <div class="app-layout">
        <div class="app-list" id="appTabs"></div>
        <div class="app-panel" id="appPanel"></div>
      </div>"""


def _apps_json() -> str:
    return json.dumps(
        {
            "iphone": {
                "label": "iPhone",
                "items": [
                    {
                        "name": "Happ",
                        "lead": "Самый быстрый вариант для iPhone, если приложение уже установлено.",
                        "download": "https://apps.apple.com/search?term=Happ%20Proxy%20Utility",
                        "steps": [
                            "Нажмите «Скопировать ссылку» на этой странице.",
                            "Откройте Happ и нажмите кнопку «+».",
                            "Выберите импорт из буфера обмена или вставьте ссылку вручную.",
                            "Обновите профиль и подключитесь к подходящему серверу.",
                        ],
                    },
                    {
                        "name": "Incy",
                        "lead": "Удобный клиент для импорта подписки по ссылке.",
                        "download": "https://apps.apple.com/search?term=Incy%20VPN",
                        "steps": [
                            "Скопируйте ссылку подписки.",
                            "Откройте Incy и выберите добавление новой подписки.",
                            "Вставьте ссылку из буфера обмена.",
                            "Сохраните профиль, обновите список серверов и подключитесь.",
                        ],
                    },
                    {
                        "name": "V2RayTun",
                        "lead": "Подходит, если нужен простой импорт подписки и быстрый старт.",
                        "download": "https://apps.apple.com/search?term=V2RayTun",
                        "steps": [
                            "Скопируйте ссылку подписки.",
                            "Откройте V2RayTun и нажмите добавление профиля.",
                            "Выберите импорт из буфера обмена или URL.",
                            "Обновите подписку и включите VPN.",
                        ],
                    },
                    {
                        "name": "Karing",
                        "lead": "Хороший вариант, если другие приложения не импортируют ссылку.",
                        "download": "https://apps.apple.com/search?term=Karing",
                        "steps": [
                            "Скопируйте ссылку подписки.",
                            "Откройте Karing и добавьте профиль по URL.",
                            "Вставьте ссылку, сохраните и обновите профиль.",
                            "Выберите сервер и подключитесь.",
                        ],
                    },
                ],
            },
            "android": {
                "label": "Android",
                "items": [
                    {
                        "name": "Happ",
                        "lead": "Простой вариант для Android с импортом из буфера.",
                        "download": "https://play.google.com/store/search?q=Happ%20Proxy%20Utility&c=apps",
                        "steps": [
                            "Скопируйте ссылку подписки.",
                            "Откройте Happ и нажмите «Добавить».",
                            "Импортируйте ссылку из буфера обмена.",
                            "Обновите профиль и подключитесь.",
                        ],
                    },
                    {
                        "name": "V2RayTun",
                        "lead": "Удобный Android-клиент для подписок.",
                        "download": "https://play.google.com/store/search?q=V2RayTun&c=apps",
                        "steps": [
                            "Скопируйте ссылку подписки.",
                            "Откройте V2RayTun и нажмите «+».",
                            "Выберите импорт из буфера или URL подписки.",
                            "Обновите подписку и включите VPN.",
                        ],
                    },
                    {
                        "name": "Karing",
                        "lead": "Кроссплатформенный клиент с ручным добавлением URL.",
                        "download": "https://github.com/KaringX/karing/releases",
                        "steps": [
                            "Скачайте APK или установите приложение из магазина.",
                            "Скопируйте ссылку подписки.",
                            "Добавьте новый профиль по URL.",
                            "Обновите профиль и подключитесь.",
                        ],
                    },
                ],
            },
            "pc": {
                "label": "ПК",
                "items": [
                    {
                        "name": "Karing",
                        "lead": "Простой вариант для Windows/macOS с импортом URL.",
                        "download": "https://github.com/KaringX/karing/releases",
                        "steps": [
                            "Скачайте версию для вашей системы.",
                            "Скопируйте ссылку подписки на этой странице.",
                            "Добавьте новый профиль по URL.",
                            "Обновите профиль, выберите сервер и подключитесь.",
                        ],
                    },
                    {
                        "name": "Nekoray",
                        "lead": "Продвинутый клиент для Windows и Linux.",
                        "download": "https://github.com/MatsuriDayo/nekoray/releases",
                        "steps": [
                            "Скачайте архив Nekoray и запустите программу.",
                            "Скопируйте ссылку подписки.",
                            "Добавьте профиль подписки по URL.",
                            "Обновите группу серверов и включите нужный режим.",
                        ],
                    },
                ],
            },
        },
        ensure_ascii=False,
    )


def _safe_url(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    if value in {"-", "—"} or not value.startswith(("http://", "https://")):
        return None
    return value


def _days_left(dt: datetime | None) -> str:
    if dt is None:
        return "—"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    days = max((dt.astimezone(timezone.utc) - datetime.now(timezone.utc)).days, 0)
    return f"{days} дн."


def _date_short(dt: datetime | None) -> str:
    if dt is None:
        return "—"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%d.%m.%Y")


def _e(value: object) -> str:
    return html.escape(str(value), quote=True)
