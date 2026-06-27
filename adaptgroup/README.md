# Mister VPN custom subscription page

File: `mister_vpn_subscription_page.html`

Where to paste it in AdaptGroup:

`Browser page -> Custom HTML`

Steps:

1. Open `mister_vpn_subscription_page.html`.
2. Copy the whole HTML.
3. Paste it into the Custom HTML editor in AdaptGroup.
4. Save.

AdaptGroup variables used by the page:

- `{{sub_uuid}}`
- `{{sub_end_date}}`
- `{{sub_end_date_full}}`
- `{{sub_days_left_text}}`
- `{{sub_devices}}`
- `{{sub_devices_used}}`
- `{{sub_traffic_limit_gb}}`
- `{{sub_traffic_used_gb}}`
- `{{sub_status}}`
- `{{plan_name}}`

Subscription URL:

- The page uses `{{sub_url}}` if AdaptGroup provides it.
- If not, it falls back to `window.location.href`.

Apps shown on the page:

- Happ
- Incy
- V2RayTun
- Karing

The app section is split into iPhone and Android instructions.

Add-to-app buttons:

- Happ: `happ://import?url=` and fallback `happ://install-config?url=`
- Incy: `incy://import?url=`, `incy://install-config?url=`,
  `incy://import-sub?url=`
- V2RayTun: `v2raytun://import-sub?url=` and fallback
  `v2raytun://install-config?url=`
- Karing: `karing://install-config?url=` and fallback `karing://import?url=`

Every button first copies the subscription URL. If Telegram/browser/app blocks
the automatic import, the user can open the app and paste the copied URL
manually.

Device deletion:

- Without a public backend, direct device deletion from static HTML is unsafe.
- The page links users to the Telegram bot, where device deletion is handled
  through the AdaptGroup API without exposing the API key.
