# Mister VPN Bot

Telegram-бот для продажи и управления VPN-подписками через AdaptGroup VPN API.
Проект рассчитан на запуск двумя процессами: бот работает через long polling, а
FastAPI-сервис принимает вебхуки AdaptGroup и будущей платежной системы.

## Возможности

- просмотр динамических тарифов из `POST /plans/list`;
- бесплатный пробный период на 7 дней через отдельный тариф AdaptGroup;
- оформление заказа и mock-оплата;
- выдача `subscription_url` только после подтвержденной оплаты;
- раздел "Мой VPN": статус, срок действия, устройства, трафик, ссылка подключения;
- продление, кастомное продление, апгрейд, покупка трафика;
- заморозка/разморозка подписки с подтверждением;
- удаление устройства для освобождения слота;
- AdaptGroup webhook `POST /webhooks/adaptgroup` с HMAC-SHA256 подписью;
- админ-панель `/admin` для статистики, заказов, повторной выдачи, синхронизации тарифов и рассылки.
- напоминания об окончании подписки: для пробной за 1 день, для обычных за 7/2/1 день.

## Архитектура

- `app/main_bot.py` - точка входа Telegram-бота.
- `app/main_api.py` - FastAPI-приложение для вебхуков.
- `app/clients/adaptgroup.py` - единственный слой HTTP-доступа к AdaptGroup API.
- `app/services/` - бизнес-логика заказов, подписок, тарифов, уведомлений и вебхуков.
- `app/repositories/` - доступ к базе данных.
- `app/db/models/` - SQLAlchemy-модели.
- `alembic/` - миграции.
- `tests/` - базовые тесты безопасности, идемпотентности и интеграционного слоя.

Платежи вынесены за интерфейс `PaymentProvider`. Сейчас используется
`MockPaymentProvider`, чтобы позже подключить реальный шлюз без переписывания
логики VPN.

## AdaptGroup API

Документация: https://docs.adaptgroup.pro/docs/api-vpn/adaptgroup-vpn-api

Базовый URL по умолчанию:

```env
ADAPTGROUP_BASE_URL=https://network-api.adaptgroup.app
```

Авторизация:

- HTTP-заголовок `X-Api-Key`;
- поле `api_key_id` в JSON-теле каждого запроса.

Клиент реализует эндпоинты:

- `POST /plans/list`
- `POST /subs/create`
- `POST /subs/renew`
- `POST /subs/renew/custom`
- `POST /subs/freeze`
- `POST /subs/unfreeze`
- `POST /subs/upgrade`
- `POST /subs/traffic`
- `POST /subs/status`
- `POST /subs/devices`
- `POST /subs/requests`
- `POST /subs/devices/delete`

Создание подписки отправляет `external_user_id` как строковый Telegram ID,
чтобы вебхуки можно было связать с пользователем.

## Подготовка `.env`

Скопируйте пример:

```powershell
Copy-Item .env.example .env
```

Заполните минимум:

```env
BOT_TOKEN=123456:telegram-token
ADMIN_IDS=123456789
DATABASE_URL=postgresql+asyncpg://vpn_user:vpn_password@db:5432/vpn_db
ADAPTGROUP_BASE_URL=https://network-api.adaptgroup.app
ADAPTGROUP_API_KEY=
ADAPTGROUP_API_KEY_ID=
ADAPTGROUP_WEBHOOK_SECRET=
PAYMENT_PROVIDER=mock
TRAFFIC_PRICE_PER_GB=3
ADAPTGROUP_USD_TO_RUB_RATE=76.142857
PLAN_MARKUP_PERCENT=30
MIN_BALANCE_TOPUP=100
MAX_BALANCE_TOPUP=50000
DEV_MODE=false
SUPPORT_URL=https://t.me/your_support
PUBLIC_BASE_URL=https://vpn.example.com
LOG_LEVEL=INFO
```

Секреты нельзя коммитить, выводить в бот-интерфейсе или писать в логи.

`TRAFFIC_PRICE_PER_GB` задает розничную цену 1 ГБ для докупки трафика. Сам
запрос покупки трафика выполняется через AdaptGroup после подтвержденной оплаты.
Если AdaptGroup отдаёт тарифы в USD без `retail_price`, бот рассчитывает цену
для пользователя в RUB по `ADAPTGROUP_USD_TO_RUB_RATE` и `PLAN_MARKUP_PERCENT`.

Для бесплатного пробного периода создайте в AdaptGroup отдельный тариф на 7 дней
и укажите его UUID в `FREE_TRIAL_PLAN_UUID`. Если переменная пустая, бот попробует
сам найти активный 7-дневный тариф с `test`/`тест` в названии. Такая подписка
выдаётся пользователю один раз, стоит `0 RUB` в боте, списывает стоимость только
с баланса AdaptGroup и не продлевается через пользовательский интерфейс.

Платные тарифы удобнее делать отдельными планами в AdaptGroup по количеству
устройств и сроку: например `5 устройств / 30 дней`, `10 устройств / 30 дней`,
`15 устройств / 30 дней`, а затем включать нужные планы в витрине админ-панели
и задавать розничную цену в RUB. Так пользователь выбирает понятный готовый
пакет, а бот не пытается “докупать устройства” поверх тарифа.

## Локальный запуск

Требования:

- Python 3.12;
- PostgreSQL;
- заполненный `.env`.

Установите зависимости:

```powershell
python -m venv .venv
.\.venv\Scripts\pip.exe install -r requirements.txt
```

Примените миграции:

```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head
```

Запустите бота:

```powershell
.\.venv\Scripts\python.exe -m app.main_bot
```

В отдельном терминале запустите API вебхуков:

```powershell
.\.venv\Scripts\python.exe -m app.main_api
```

Healthcheck:

```text
GET http://localhost:8080/health
```

## Docker Compose

Создайте `.env`, затем:

```powershell
docker compose up --build
```

Compose поднимает:

- `db` - PostgreSQL;
- `migrate` - `alembic upgrade head`;
- `bot` - Telegram long polling;
- `api` - FastAPI webhook-сервис.

## Настройка Telegram

1. Создайте бота через `@BotFather`.
2. Запишите токен в `BOT_TOKEN`.
3. Добавьте Telegram ID администраторов в `ADMIN_IDS` через запятую.
4. Запустите `bot` и отправьте `/start`.
5. Админка доступна по `/admin` только ID из `ADMIN_IDS`.

## Настройка вебхуков AdaptGroup

Публичный URL должен указывать на FastAPI-сервис:

```text
https://your-domain.example/webhooks/adaptgroup
```

В AdaptGroup задайте тот же секрет, что и в `ADAPTGROUP_WEBHOOK_SECRET`.
Сервис проверяет `X-Webhook-Signature` как HMAC-SHA256 от сырого тела запроса
через `hmac.compare_digest` до JSON-парсинга.

`ADAPTGROUP_WEBHOOK_ALLOWED_IPS` можно использовать как дополнительный IP
allowlist, но основная защита всегда подпись.

## Оплата

Доступны два провайдера:

- `mock` - тестовый режим без реального списания;
- `rollypay` - реальная оплата через RollyPay.

Пользователь после выбора тарифа видит:

- состав заказа;
- цену;
- кнопку перехода к оплате;
- кнопку проверки оплаты;
- отмену заказа.

Также есть внутренний баланс пользователя. Пользователь может пополнить баланс
через RollyPay, затем оплачивать VPN с баланса бота. Это удобно без домена:
после оплаты пополнения пользователь нажимает `✅ Проверить оплату`, бот
проверяет статус платежа и зачисляет деньги.

Ручное подтверждение mock-оплаты доступно только при `DEV_MODE=true`. В проде
оставляйте `DEV_MODE=false`.

### RollyPay

Документация: https://docs.rollypay.io

Для включения:

```env
PAYMENT_PROVIDER=rollypay
ROLLYPAY_BASE_URL=https://rollypay.io
ROLLYPAY_API_KEY=rpk_live_...
ROLLYPAY_TERMINAL_ID=
ROLLYPAY_SIGNING_SECRET=
ROLLYPAY_PAYMENT_METHOD=
ROLLYPAY_SUCCESS_REDIRECT_URL=
ROLLYPAY_FAIL_REDIRECT_URL=
```

Callback URL в кассе RollyPay:

```text
https://your-domain.example/webhooks/rollypay
```

RollyPay требует заголовки `X-API-Key` и уникальный `X-Nonce` для API-запросов.
Webhook проверяется по `X-Signature` и `X-Timestamp`: подпись HMAC-SHA256 от
строки `timestamp + "." + raw_body` с секретом `ROLLYPAY_SIGNING_SECRET`.
После события `payment.paid` бот помечает заказ оплаченным и запускает
идемпотентную выдачу VPN.

Если домена пока нет, callback URL можно не указывать. В этом режиме оплата
работает через кнопку `✅ Проверить оплату`: пользователь открывает ссылку
RollyPay, оплачивает, возвращается в Telegram и нажимает проверку. Бот сам
делает `GET /api/v1/payments/{payment_id}`, видит статус `paid`, переводит
заказ в `paid` и запускает выдачу VPN. Для такого режима нужен только
`ROLLYPAY_API_KEY`; `ROLLYPAY_SIGNING_SECRET` понадобится позже для webhook.
`ROLLYPAY_TERMINAL_ID` тоже можно оставить пустым: при API key RollyPay
выполняет операции в контексте кассы, к которой привязан ключ.

Чтобы подключить реальный платежный провайдер:

1. Создайте класс, реализующий `PaymentProvider`.
2. Реализуйте `create_payment`, `get_payment_status`, `handle_webhook`.
3. Добавьте провайдера в `app/services/payments/factory.py`.
4. Добавьте endpoint вебхука платежной системы в FastAPI.
5. Сохраняйте идемпотентность по `payment_id` и `idempotency_key`.

## Идемпотентность и ручное восстановление

VPN-подписка создается в AdaptGroup только после подтвержденной оплаты.

Для защиты от дублей:

- заказ имеет статусы `pending`, `paid`, `provisioning`, `completed`, `failed`, `cancelled`;
- выдача VPN берет атомарный lock переводом заказа в `provisioning`;
- повторное нажатие кнопки или повторный платежный вебхук не создают вторую подписку;
- AdaptGroup webhook сохраняется в `webhook_events` и повторно не обрабатывается.

`POST /subs/create` списывает баланс интеграции AdaptGroup. Если во время этого
запроса случился сетевой сбой или timeout, результат неизвестен: подписка могла
создаться на стороне AdaptGroup. Поэтому бот не делает слепой автоповтор.

Безопасный сценарий восстановления:

1. Найдите заказ в админке или базе. Он будет `failed` и `needs_manual_review=true`.
2. Проверьте в кабинете/поддержке AdaptGroup, была ли создана подписка для
   `external_user_id` пользователя.
3. Если подписка создана, внесите/синхронизируйте `subscription_uuid` и
   `subscription_url`, затем пометьте заказ завершенным.
4. Если подписка точно не создана, администратор может повторить выдачу из
   админки без повторной оплаты пользователя.

## Тестирование

```powershell
.\.venv\Scripts\python.exe -m compileall -q app tests
.\.venv\Scripts\python.exe -m pytest -q
```

Тесты покрывают:

- проверку подписи AdaptGroup webhook;
- защиту от повторной обработки webhook;
- создание заказа;
- невозможность повторной выдачи VPN;
- права администратора;
- форматирование трафика;
- обработку ошибок AdaptGroup;
- mock HTTP-ответы внешнего API.

## Известные ограничения

- Реальный платежный шлюз не подключен, используется mock-реализация.
- Тарифы и цены приходят из AdaptGroup; бот не должен хардкодить их в коде.
- Пробные тарифы через API не продаются.
- Для production нужен публичный HTTPS URL для `/webhooks/adaptgroup`.
