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

## Проверка

```bash
python -m unittest discover -s tests -v
bash -n deployments/yandex_function/deploy.sh
```

После настройки профиля `yc`, Lockbox и service account развёртывание
выполняется так:

```bash
export SERVICE_ACCOUNT_ID=...
export NEST_SECRET_ID=...
export NEST_DEVICE_ACCESS_PROJECT_ID=...
export YDB_DATABASE=...
deployments/yandex_function/deploy.sh
```
