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
