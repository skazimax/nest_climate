# Nest Climate

Сбор температуры и влажности с двух Nest Thermostat в Румянцево и сохранение
пятиминутной истории в существующей YDB Serverless.

## Поток данных

```text
Nest SDM API → Yandex Cloud Function → nest_environment_readings (YDB)
                                             ↓
                                      tg-server-control
```

Коллектор одним вызовом `devices.list` получает оба термостата и сопоставляет
их по комнатам Nest:

- `Первый этаж` → `floor_1`;
- `Второй этаж` → `floor_2`.

Время округляется вниз до пятиминутной границы. Повторный запуск в том же
интервале выполняет `UPSERT` в тот же ключ и не создаёт дубликат.

## Таблица

Таблица `nest_environment_readings` имеет ключ `(location, measured_at)` и поля
`device_id`, `temperature_c`, `humidity_percent`, `online`. Время хранится в UTC.

## Безопасность

OAuth Client ID, Client Secret и постоянный refresh token передаются функции из
Yandex Lockbox. Сервисный аккаунт функции получает доступ к Lockbox и право
записи в существующую YDB. Секреты не хранятся в Git и не выводятся в логи.

## Развёрнутые ресурсы

- Cloud Function: `nest-environment-collector`;
- timer trigger: `nest-environment-collector-5m`, запуск каждые 5 минут;
- service account: `nest-climate-collector`;
- Lockbox secret: `nest-climate-oauth`;
- YDB: `we-vsp-bot-ydb`;
- table: `nest_environment_readings`.

При холодном старте функция сама проверяет схему и создаёт таблицу,
если её ещё нет. Для обычной эксплуатации ручной запуск не требуется.

## Проверка

```bash
python -m unittest discover -s tests -v
bash -n deployments/yandex_function/deploy.sh
```

## Недельный отчёт

Server-развёртывание в [`deployments/server`](deployments/server/README.md)
формирует квадратный отчёт температуры и влажности по обоим этажам и отправляет
его каждый понедельник в 08:00 Europe/Moscow. Окно отчёта всегда
скользящее: ровно последние 7 суток до момента запуска, в том числе для
ручного вызова из Telegram-бота.

После настройки профиля `yc`, Lockbox и service account развёртывание
выполняется так:

```bash
export SERVICE_ACCOUNT_ID=...
export NEST_SECRET_ID=...
export NEST_DEVICE_ACCESS_PROJECT_ID=...
export YDB_DATABASE=...
deployments/yandex_function/deploy.sh
```
