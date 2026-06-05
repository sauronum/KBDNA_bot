from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:
    def load_dotenv(*args, **kwargs) -> bool:
        return False


ROOT_DIR = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Settings:
    root_dir: Path
    bot_token: str
    log_level: str


def _required_env(name: str) -> str:
    value = os.getenv(name, '').strip()
    if not value:
        raise RuntimeError(f'Environment variable {name} is required')
    return value


def load_settings() -> Settings:
    load_dotenv(ROOT_DIR / '.env')

    return Settings(
        root_dir=ROOT_DIR,
        bot_token=_required_env('BOT_TOKEN'),
        log_level=(os.getenv('LOG_LEVEL', 'INFO').strip() or 'INFO').upper(),
    )
