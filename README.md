# py-tg-moder

[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Docker](https://github.com/jtprogru/py-tg-moder/actions/workflows/docker-publish.yml/badge.svg)](https://github.com/jtprogru/py-tg-moder/actions/workflows/docker-publish.yml)
[![Testing](https://github.com/jtprogru/py-tg-moder/actions/workflows/testing.yml/badge.svg?branch=develop)](https://github.com/jtprogru/py-tg-moder/actions/workflows/testing.yml)
[![Deploy](https://github.com/jtprogru/py-tg-moder/actions/workflows/deploy-k8s.yml/badge.svg)](https://github.com/jtprogru/py-tg-moder/actions/workflows/deploy-k8s.yml)
[![GitHub stars](https://img.shields.io/github/stars/jtprogru/py-tg-moder.svg)](https://github.com/jtprogru/py-tg-moder/stargazers)
[![GitHub issues](https://img.shields.io/github/issues-raw/jtprogru/py-tg-moder)](https://github.com/jtprogru/py-tg-moder/issues)
[![GitHub release (latest by date)](https://img.shields.io/github/v/release/jtprogru/py-tg-moder)](https://github.com/jtprogru/py-tg-moder/releases/latest)
[![GitHub](https://img.shields.io/github/license/jtprogru/py-tg-moder)](https://github.com/jtprogru/py-tg-moder/)
[![Wiki](https://img.shields.io/badge/Wiki-READ-success)](https://github.com/jtprogru/py-tg-moder/wiki)

Бот-модератор для чата [@jtprogru_chat](https://t.me/jtprogru_chat). Работает на [python-telegram-bot](https://python-telegram-bot.org/) 22 (async), собирается через [uv](https://docs.astral.sh/uv/), состояние хранит в SQLite.

## Возможности

- **Allowlist чатов** — бот реагирует только в чатах из `config.yaml`, из чужих молча выходит.
- **Капча на входе** — новый участник замьючен до нажатия кнопки; не прошёл за таймаут → кик/бан. Плюс проверка по [CAS](https://cas.chat/).
- **Модерация сообщений новичков** — ссылки/форварды/@-меншены/инвайты у «новичков» (первые N сообщений или первые сутки) удаляются/мьютятся/варнятся; правки сообщений перепроверяются.
- **Флуд-контроль** — > N сообщений за окно времени → временный мьют.
- **Anti-raid режим** — всплеск вступлений (порог/окно в конфиге) временно ужесточает проверки: таймаут капчи вдвое короче, провал капчи = бан вместо кика, нарушения новичков эскалируются до мьюта. Начало и конец рейда видны в журнале и на дашборде.
- **Управляемое удаление медиа** — настраиваемый список типов (голос/видео/кружки/локации) удаляется у не-админов, с опциональным самоудаляющимся уведомлением.
- **Команды модерации** — `/ban`, `/unban`, `/kick`, `/mute`, `/unmute` с временными сроками (`/mute 1h`, `/ban 1d`), таргетинг по reply, `@username` или числовому id.
- **Система варнов** — `/warn`, `/warns`, `/unwarn`; при достижении порога — авто-мьют/бан.
- **Защита целей** — админов, владельца и самого бота нельзя забанить/замьютить.
- **Персистентное состояние** — варны, мьюты, «новизна» юзеров и кэш `@username → id` переживают рестарт (SQLite).
- **Audit-log и статистика** — все действия модерации (с причинами), вступления/выходы, исходы капчи и подневная статистика сообщений пишутся в БД; история старше `storage.retention.days` (по умолчанию год) чистится ежедневной джобой.
- **Веб-панель** — дашборд аналитики (участники, сообщения, капча, действия модерации, журнал с причинами) на том же процессе, что и бот. Вход через Telegram Login Widget, доступ по списку `admin_ids`. Из панели можно банить/кикать/мьютить (действия аудируются с указанием, кто и за что) и принудительно компактить БД с предпросмотром того, что будет удалено.
- **Экспорт и бэкап** — статистика в CSV (журнал действий с учётом фильтров, сообщения по дням, участники; открывается в Excel), выгрузка `config.yaml`, чек-лист env-переменных без значений секретов и консистентный снапшот всей БД (`VACUUM INTO`) — всё, чтобы пережить передеплой без потерь.
- **Автобэкапы по расписанию** — ежедневный снапшот БД в каталог с ротацией (хранятся последние N) и опциональной выгрузкой в S3-совместимое хранилище (без boto3 — собственный SigV4-клиент); ручной бэкап — кнопкой из панели.

Полный статус фич — в [ROADMAP.md](./ROADMAP.md).

## Конфигурация

Поведение модерации настраивается в [`src/config.yaml`](./src/config.yaml): список разрешённых чатов, пороги флуд-контроля, параметры капчи, фильтра новичков и удаления медиа, путь к БД. Файл документирован комментариями.

Секреты и рантайм-параметры передаются через переменные окружения:

| Переменная            | Обязательна | Назначение                                                                 |
|-----------------------|:-----------:|----------------------------------------------------------------------------|
| `TELEGRAM_BOT_TOKEN`  | да          | Токен бота от [@BotFather](https://t.me/BotFather).                         |
| `DB_PATH`             | нет         | Путь к файлу SQLite. Переопределяет `storage.path` из `config.yaml`. Указывай на смонтированный том, чтобы состояние переживало рестарт. |
| `SENTRY_DSN`          | нет         | DSN для отправки ошибок в Sentry.                                           |
| `DEBUG`               | нет         | `true`/`1`/`yes`/`on` включает debug-логирование.                          |
| `WEB_ENABLED`         | нет         | Включает веб-панель (или `web.enabled` в `config.yaml`).                    |
| `WEB_SESSION_SECRET`  | при вебе    | Длинная случайная строка для подписи сессионных кук панели.                 |
| `RETENTION_DAYS`      | нет         | Сколько дней хранить историю (audit-log, статистику). По умолчанию 365.     |
| `BACKUP_ENABLED`      | нет         | Включает ежедневные автобэкапы (или `storage.backup.enabled` в `config.yaml`). |
| `BACKUP_DIR`          | нет         | Каталог для снапшотов. Указывай на смонтированный том. По умолчанию `backups`. |
| `S3_ACCESS_KEY` / `S3_SECRET_KEY` | при S3 | Креды S3-совместимого хранилища для выгрузки бэкапов (endpoint/bucket — в `storage.backup.s3` или env `S3_ENDPOINT`/`S3_BUCKET`). |

Для локального запуска создай `src/.env` (используется `make run` и `docker compose`):

```ini
export TELEGRAM_BOT_TOKEN='1234567890:qwertyuiopHGVBNVJHVJVMNBVMNBVposdfghi'
export SENTRY_DSN="https://xxxx@o444444.ingest.sentry.io/1234567"
export DEBUG=false
```

> Токен читается **только из окружения** и в образ не запекается — один и тот же публичный образ безопасно использовать в любом окружении.

## Варианты запуска

### 1. Локально (uv)

```bash
make sync-dev   # установить зависимости (вкл. dev-группу)
make run        # cd src && source ./.env && uv run python bot.py
```

### 2. Docker Compose

Персистит SQLite в именованном томе `moder-data`:

```bash
docker compose up -d
```

Использует готовый образ `ghcr.io/jtprogru/py-tg-moder:latest` и `src/.env` как `env_file`.

### 3. Kubernetes

Манифесты и подробная инструкция — в [`.k8s/README.md`](./.k8s/README.md). Кратко:

```bash
kubectl apply -f .k8s/secrets.yaml       # секрет с токеном (base64)
kubectl apply -f .k8s/deployment.yaml    # Deployment + PVC для SQLite
```

Деплой одноподовый (`strategy: Recreate`, `replicas: 1`) — SQLite-файл принадлежит одному поду, две реплики одновременно поднимать нельзя.

## Веб-панель

Дашборд поднимается в том же процессе, что и бот (`web.enabled: true` в `config.yaml` или `WEB_ENABLED=true`), слушает `web.port` (8080). Что нужно для входа:

1. `admin_ids` в `config.yaml` — Telegram user id тех, кому разрешён вход.
2. `WEB_SESSION_SECRET` в окружении — подпись сессионных кук.
3. Публичный HTTPS-домен для Telegram Login Widget: привяжи его к боту через @BotFather → `/setdomain` и пропиши в `web.public_url`.

Для локальной разработки без домена есть dev-вход: при `DEBUG=true` открой `/auth/dev?user_id=<твой id>`. Эндпоинт `GET /healthz` отдаёт `{"status": "ok"}` без аутентификации — для проб k8s.

## Разработка

```bash
make sync-dev      # зависимости
make lint          # ruff format --check + ruff check
make fmt           # авто-формат и авто-фиксы
make pytest        # тесты
make test-full     # lint + tests
make build-img     # собрать и затегать Docker-образ
```

`make help` покажет все цели.

## CI/CD

- **Testing** (`testing.yml`) — ruff + pytest на каждый push в ветку, кроме `main`.
- **Docker** (`docker-publish.yml`) — сборка и публикация образа в `ghcr.io` по тегу `v*.*.*`.
- **Deploy** (`deploy-k8s.yml`) — на GitHub Release раскатывает `.k8s/deployment.yaml` на self-hosted раннере.

## Documentation

Дополнительная документация и «хотелки на перспективу» — в [Wiki](https://github.com/jtprogru/py-tg-moder/wiki) и [ROADMAP.md](./ROADMAP.md).

## Feedback

Если начал использовать и есть фидбэк — создай [issue](https://github.com/jtprogru/py-tg-moder/issues) или напиши в чат [@jtprogru_chat](https://t.me/jtprogru_chat).

## Authors

- Michael Savin
  - :octocat: [@jtprogru](https://www.github.com/jtprogru)
  - :bird: [@jtprogru](https://www.twitter.com/jtprogru)
  - :moneybag: [savinmi.ru](https://savinmi.ru)
