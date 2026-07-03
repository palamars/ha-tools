# InfluxDB MCP Server

Минимальный read-only MCP server для InfluxDB 2.x / InfluxDB Cloud.

Проект сделан так, чтобы **не хранить секреты в коде и репозитории**:

- реальные `.env` и `settings.yaml` добавлены в `.gitignore`;
- в Git лежат только `.env.example` и `settings.yaml.example`;
- токен InfluxDB читается из `INFLUXDB_TOKEN`, `INFLUXDB_TOKEN_FILE` или из локального `settings.yaml`;
- по умолчанию разрешены только read-only инструменты;
- raw Flux-запросы выключены настройкой `allow_raw_flux: false`.

## Что умеет

MCP tools:

- `health` — проверка подключения к InfluxDB;
- `list_buckets` — список доступных buckets;
- `list_measurements` — список measurements;
- `list_field_keys` — поля measurement;
- `list_tag_keys` — tags measurement;
- `list_tag_values` — значения конкретного tag;
- `query_measurement` — безопасный шаблонный запрос по measurement, fields, tags и диапазону времени;
- `run_flux_query` — произвольный Flux, только если явно включить `allow_raw_flux`.

## Быстрый старт через Docker

```bash
cp .env.example .env
cp settings.yaml.example settings.yaml
```

Отредактируй локальные файлы:

```bash
nano .env
nano settings.yaml
```

Запуск:

```bash
docker compose up -d --build
```

Проверка логов:

```bash
docker compose logs -f influxdb-mcp
```

## Локальный запуск без Docker

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"

cp .env.example .env
cp settings.yaml.example settings.yaml

influxdb-mcp-server --transport stdio
```

Для HTTP/SSE транспорта:

```bash
influxdb-mcp-server --transport sse --host 0.0.0.0 --port 8000
```

## Настройки

Путь к YAML-файлу можно задать переменной:

```bash
export INFLUXDB_MCP_SETTINGS=/path/to/settings.yaml
```

Переменные окружения имеют приоритет над `settings.yaml`.

Основные переменные:

```env
INFLUXDB_URL=http://localhost:8086
INFLUXDB_ORG=home
INFLUXDB_BUCKET=homeassistant
INFLUXDB_TOKEN=put-token-here
```

Для Docker secrets можно использовать файл:

```env
INFLUXDB_TOKEN_FILE=/run/secrets/influxdb_token
```

## Пример settings.yaml

```yaml
server:
  name: influxdb-mcp-server
  host: 0.0.0.0
  port: 8000

influxdb:
  url: http://localhost:8086
  org: home
  bucket: homeassistant
  timeout_seconds: 20
  verify_ssl: true

security:
  allow_raw_flux: false
  max_records: 1000
  max_query_chars: 10000
  allowed_buckets:
    - homeassistant

defaults:
  range_start: -24h
```

## Пример запроса через MCP

Попроси ассистента:

> Покажи среднюю мощность `sensor.zigbee_power` за последние 24 часа.

Обычно для Home Assistant в InfluxDB удобнее сначала вызвать:

1. `list_measurements`
2. `list_field_keys`
3. `list_tag_keys`
4. `query_measurement`

## Безопасность

Этот сервер не записывает данные в InfluxDB и не удаляет их. Однако чтение из InfluxDB тоже может раскрывать чувствительные данные, поэтому:

- не публикуй сервер в интернет без HTTPS и внешней авторизации;
- токен InfluxDB выдавай с минимальными правами, желательно read-only;
- оставляй `allow_raw_flux: false`, если сервером будут пользоваться не только администраторы;
- ограничивай buckets через `allowed_buckets`;
- не коммить `.env` и `settings.yaml`.
