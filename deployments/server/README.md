# Недельный отчёт климата

Каждый понедельник в 08:00 по Москве служба строит квадратный PNG по варианту 3
и отправляет его в приватный чат администратора управляющего бота. Период отчёта:
ровно последние 7 суток до момента запуска. Поэтому ручная команда не привязана к
границам календарной недели. Крупные значения в
карточках подписаны «Среднее за период»; ниже показаны минимум, максимум и доля
полученных пятиминутных измерений.

Служба использует отдельное окружение `/opt/nest-climate-report/venv`. Токен и
адресат берутся из закрытого `/etc/tg-server-control/bot.env`: при наличии
`TELEGRAM_REPORT_CHAT_IDS` он имеет приоритет, иначе используются
`TELEGRAM_ADMIN_USER_IDS`. YDB-ключ передаётся DynamicUser через systemd
`LoadCredential`; копия секрета не создаётся.

Установка на Linux x86_64. На CPython 3.12 зависимости ставятся из
`requirements.lock` с хешами, на другой версии Python — из `requirements.txt`
(диапазоны версий) без проверки хешей.

Если Telegram доступен напрямую, а `127.0.0.1:1079` ведёт в другой регион
(`tg-vpn-failover` в режиме `ru`), прокси отключается drop-in:

```bash
sudo mkdir -p /etc/systemd/system/nest-climate-report.service.d
printf '[Service]\nUnsetEnvironment=ALL_PROXY all_proxy\n' | \
  sudo tee /etc/systemd/system/nest-climate-report.service.d/direct-telegram.conf
```

Установка:

```bash
sudo env ENABLE_TIMER=1 bash deployments/server/install.sh
```

Для установки из заранее сохранённого wheelhouse:

```bash
sudo env WHEELHOUSE=/path/to/wheelhouse ENABLE_TIMER=1 bash deployments/server/install.sh
```

Проверка кода без Telegram после загрузки переменных YDB:

```bash
/opt/nest-climate-report/venv/bin/python -B -m nest_climate.report \
  --end 2026-09-07T08:00 --output /tmp/climate-weekly.png
systemctl list-timers nest-climate-report.timer --no-pager
```

При ручном запуске production unit отчёт будет отправлен. Для локальной проверки
используйте модуль с `--output` без `--send`. Если данных нет на обоих этажах,
изображение не отправляется и unit завершается с ошибкой. При наличии данных
только одного этажа отчёт отправляется, второй этаж отмечается как недоступный.
