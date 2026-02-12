"""Скрипт для получения email service account из credentials файла."""

import json
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Настройка кодировки для Windows
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# Загружаем .env
env_path = Path(__file__).parent.parent / ".env"
if env_path.exists():
    load_dotenv(env_path)
else:
    load_dotenv()

credentials_path = os.getenv("GOOGLE_SHEETS_CREDENTIALS_PATH", "").strip()

if not credentials_path:
    print("[ERROR] Ошибка: GOOGLE_SHEETS_CREDENTIALS_PATH не задан в переменных окружения")
    sys.exit(1)

creds_path = Path(credentials_path)
if not creds_path.exists():
    print(f"[ERROR] Ошибка: Файл credentials не найден: {credentials_path}")
    sys.exit(1)

try:
    with open(creds_path, 'r', encoding='utf-8') as f:
        creds_data = json.load(f)
    
    service_account_email = creds_data.get('client_email', '')
    
    if not service_account_email:
        print("[ERROR] Ошибка: В файле credentials не найден client_email")
        sys.exit(1)
    
    print(f"\n[OK] Email service account: {service_account_email}\n")
    print("[INFO] Инструкция:")
    print("1. Откройте вашу Google Sheets таблицу:")
    print("   https://docs.google.com/spreadsheets/d/1aMWJqT6eWBYVAyv2WSE1UjUMtnZA6E2EHBcSWF2u7gQ/edit")
    print("2. Нажмите кнопку 'Настройки доступа' (Share) в правом верхнем углу")
    print(f"3. Добавьте email выше ({service_account_email}) с правами 'Редактор' (Editor)")
    print("4. Нажмите 'Готово' (Done)\n")
    
except json.JSONDecodeError as e:
    print(f"[ERROR] Ошибка: Не удалось прочитать JSON файл: {e}")
    sys.exit(1)
except Exception as e:
    print(f"[ERROR] Ошибка: {e}")
    sys.exit(1)
