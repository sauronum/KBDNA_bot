# Telegram Bot + Google Sheets

Проект находится в папке: `M:\CODEX\KBDNAbot`.

## Быстрый запуск

Открой PowerShell и выполни:

```powershell
cd M:\CODEX\KBDNAbot
.\.venv\Scripts\Activate.ps1
python .\bot.py
```

Если окружение еще не установлено:

```powershell
cd M:\CODEX\KBDNAbot
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python .\bot.py
```

## Настройки

Файл настроек: `M:\CODEX\KBDNAbot\.env`

Пример:

```env
BOT_TOKEN=your_telegram_bot_token
GOOGLE_SHEETS_ID=11HwioymAIrw47E_E6qDYi9aFzkfaR0BU_tglrwSvy0U
GOOGLE_SHEETS_WORKSHEET=
GOOGLE_CREDENTIALS_PATH=service_account.json
```

JSON-ключ сервисного аккаунта должен лежать в:
`M:\CODEX\KBDNAbot\service_account.json`

## Использование в Telegram

- Можно писать фамилию обычным текстом (без `/get`).
- `/get <Фамилия>` тоже работает.
- `/build` показывает версию запущенного бота.

## Проверка перед запуском

Перед обновлением сервера прогоняй локально:

```powershell
cd M:\CODEX\KBDNAbot
.\.venv\Scripts\python.exe -m unittest discover -s tests
.\.venv\Scripts\python.exe -m compileall bot.py app g25_core handlers ui features clients stores render
```

На сервере Linux то же самое выполняется так:

```bash
cd /opt/kbdnabot
./.venv/bin/python -m unittest discover -s tests
./.venv/bin/python -m compileall bot.py app g25_core handlers ui features clients stores render
```

Обе команды должны завершиться без ошибок.

## Файлы для сервера

После рефакторинга вместе с `bot.py` нужны папки:

- `handlers/`
- `ui/`
- `features/`
- `clients/`
- `stores/`
- `render/`
- `app/`
- `g25_core/`
- `tests/`

Папку `tests` стоит держать и на сервере, чтобы быстро проверить обновление перед перезапуском бота.

Старые корневые модули `*_handlers.py`, `*_ui.py`, `*_feature.py`, `sheets_client.py`, `usage_store.py`, `vahaduo_store.py`, `analytics_render.py`, `untested_surnames.py` больше не используются и после загрузки новых папок их можно удалить с сервера.

Старый пользовательский PCA-движок удален. На сервере после загрузки нового кода нужно удалить:

```bash
rm -rf /opt/kbdnabot/g25_feature
rm -f /opt/kbdnabot/handlers/g25.py
rm -f /opt/kbdnabot/ui/g25.py
rm -f /opt/kbdnabot/tests/test_g25_handlers.py
rm -f /opt/kbdnabot/tests/test_g25_ui.py
```

## Порядок обновления сервера Linux

Рабочая папка объединенного бота: `/opt/kbdnabot`. Отдельный `/opt/DNA_multitool` после слияния не запускается.

1. Остановить сервис:

```bash
sudo systemctl stop kbdnabot
```

2. Сделать быстрый backup пользовательских данных и локальных настроек:

```bash
cd /opt/kbdnabot
tar -czf /root/kbdnabot-backup-$(date +%F-%H%M).tar.gz .env service_account.json storage vahaduo_sources vahaduo_targets g25_access.json *.sqlite3 2>/dev/null
```

3. Загрузить обновленный код в `/opt/kbdnabot`: `bot.py`, `requirements.txt`, `README.md`, папки `app/`, `g25_core/`, `handlers/`, `ui/`, `features/`, `clients/`, `stores/`, `render/`, `tests/`.

4. Не затирать серверные `.env`, `service_account.json`, `storage/`, `vahaduo_sources/`, `vahaduo_targets/`, `g25_access.json`, `*.sqlite3` и `g25_core/runs/`, если специально не делаешь миграцию или очистку временных расчетов.

5. Обновить зависимости:

```bash
cd /opt/kbdnabot
./.venv/bin/python -m pip install -r requirements.txt
```

6. Выполнить проверки:

```bash
cd /opt/kbdnabot
./.venv/bin/python -m unittest discover -s tests
./.venv/bin/python -m compileall bot.py app g25_core handlers ui features clients stores render
```

7. Удалить legacy PCA-файлы, если они еще остались после загрузки:

```bash
rm -rf /opt/kbdnabot/g25_feature
rm -f /opt/kbdnabot/handlers/g25.py /opt/kbdnabot/ui/g25.py
rm -f /opt/kbdnabot/tests/test_g25_handlers.py /opt/kbdnabot/tests/test_g25_ui.py
```

8. Проверить, что не остался второй Telegram polling-процесс:

```bash
ps aux | grep -E 'bot.py|DNA_multitool|app/bot_app.py' | grep -v grep
```

Должен остаться только процесс KBDNA после запуска. Если виден старый `DNA_multitool` или `app/bot_app.py`, его нужно остановить.

9. Запустить сервис и посмотреть лог:

```bash
sudo systemctl start kbdnabot
sudo journalctl -u kbdnabot -n 80 --no-pager
```

10. В Telegram проверить:

- `/build`
- `/menu`
- reply-кнопки: `Поиск по фамилии`, `Аналитика`, `DNA Lab`, `Настройки`, `Прочее`
- `/menu → Настройки → Язык`
- `Прочее → Инструкция` и один раздел справки
- `Прочее → Получить G25 координаты`
- `Прочее → Словарь`
- `DNA Lab → My DNA`
- `DNA Lab → Vahaduo Lab`
- `DNA Lab → Coordinate spaces`
- один поиск по фамилии

## DNA Lab внутри KBDNA

DNA Lab подключен как вложенный раздел KBDNA через кнопку `DNA Lab`. Пользовательский быстрый вход `Получить G25 координаты` ведет в новый DNA Lab-движок, который использует отдельный `g25_core/` и хранит данные в `storage/`.

Старый пользовательский PCA-путь удален. PCA-сценарии открываются через `DNA Lab → Coordinate spaces`; Vahaduo/G25-расчеты используют `g25_core/`.

Запускать нужно только `bot.py`. Файл `app/bot_app.py` оставлен как legacy standalone launcher для изолированной разработки DNA Lab и защищен от случайного запуска на сервере.
