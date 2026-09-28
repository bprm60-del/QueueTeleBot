import os
from pathlib import Path
from dotenv import load_dotenv

# Загружаем переменные из .env файла
env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=env_path)

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

# Список ID администраторов (разработчик / преподаватель / староста)
raw_admin_ids = os.getenv("ADMIN_IDS", "").strip()
ADMIN_IDS = set()
if raw_admin_ids:
    for item in raw_admin_ids.split(","):
        clean_item = item.strip()
        if clean_item.isdigit():
            ADMIN_IDS.add(int(clean_item))

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS
