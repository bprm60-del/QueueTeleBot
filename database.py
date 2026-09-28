import sqlite3
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Tuple

DB_PATH = Path(__file__).resolve().parent / "queue_bot.db"


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Инициализация таблиц базы данных"""
    with get_connection() as conn:
        cursor = conn.cursor()

        # Таблица студентов
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                full_name TEXT NOT NULL,
                group_name TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Таблица групп
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS groups (
                group_name TEXT PRIMARY KEY,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Таблица расписания сдачи (слоты / пары)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS schedule_slots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_name TEXT NOT NULL,
                subject TEXT NOT NULL,
                slot_date TEXT NOT NULL,       -- YYYY-MM-DD
                slot_time TEXT NOT NULL,       -- HH:MM
                max_students INTEGER DEFAULT 0, -- 0 = без ограничений
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (group_name) REFERENCES groups(group_name) ON DELETE CASCADE
            )
        """)

        # Таблица записей в очередь
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS queue_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                slot_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                status TEXT DEFAULT 'waiting', -- waiting, completed
                FOREIGN KEY (slot_id) REFERENCES schedule_slots(id) ON DELETE CASCADE,
                FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
                UNIQUE (slot_id, user_id)
            )
        """)
        conn.commit()


def cleanup_old_entries():
    """
    Удаляет все прошедшие записи и слоты (дата которых раньше сегодняшнего дня).
    Это обеспечивает автоматическую очистку предыдущих очередей.
    """
    today_str = date.today().strftime("%Y-%m-%d")
    with get_connection() as conn:
        cursor = conn.cursor()
        
        # Находим id устаревших слотов
        cursor.execute("SELECT id FROM schedule_slots WHERE slot_date < ?", (today_str,))
        expired_slots = cursor.fetchall()
        expired_slot_ids = [slot["id"] for slot in expired_slots]

        if expired_slot_ids:
            placeholders = ",".join("?" for _ in expired_slot_ids)
            # Удаляем записи в очереди для устаревших слотов
            cursor.execute(f"DELETE FROM queue_entries WHERE slot_id IN ({placeholders})", expired_slot_ids)
            # Удаляем сами устаревшие слоты
            cursor.execute(f"DELETE FROM schedule_slots WHERE id IN ({placeholders})", expired_slot_ids)
            conn.commit()


# ================= Студенты (Пользователи) =================

def get_user(user_id: int) -> Optional[dict]:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        return dict(row) if row else None


def save_user(user_id: int, full_name: str, group_name: str):
    group_name = group_name.strip().upper()
    with get_connection() as conn:
        cursor = conn.cursor()
        # Автоматически регистрируем группу, если её еще нет
        cursor.execute("INSERT OR IGNORE INTO groups (group_name) VALUES (?)", (group_name,))
        # Сохраняем/обновляем студента
        cursor.execute("""
            INSERT INTO users (user_id, full_name, group_name)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                full_name = excluded.full_name,
                group_name = excluded.group_name
        """, (user_id, full_name.strip(), group_name))
        conn.commit()


# ================= Группы =================

def get_all_groups() -> List[str]:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT group_name FROM groups ORDER BY group_name")
        return [row["group_name"] for row in cursor.fetchall()]


def add_group(group_name: str):
    group_name = group_name.strip().upper()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT OR IGNORE INTO groups (group_name) VALUES (?)", (group_name,))
        conn.commit()


def delete_group(group_name: str):
    group_name = group_name.strip().upper()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM schedule_slots WHERE group_name = ?", (group_name,))
        cursor.execute("DELETE FROM groups WHERE group_name = ?", (group_name,))
        conn.commit()


# ================= Расписание (Слоты для сдачи) =================

def add_schedule_slot(group_name: str, subject: str, slot_date: str, slot_time: str, max_students: int = 0) -> int:
    """
    Добавляет слот сдачи в расписание группы.
    Дата должна быть в диапазоне от сегодня до +14 дней (2 недели).
    """
    cleanup_old_entries()
    group_name = group_name.strip().upper()
    add_group(group_name)

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO schedule_slots (group_name, subject, slot_date, slot_time, max_students)
            VALUES (?, ?, ?, ?, ?)
        """, (group_name, subject.strip(), slot_date.strip(), slot_time.strip(), max_students))
        conn.commit()
        return cursor.lastrowid


def get_available_slots_for_group(group_name: str) -> List[dict]:
    """
    Возвращает доступные слоты для сдачи для указанной группы:
    только будущие и не дальше 2 недель вперед.
    """
    cleanup_old_entries()
    group_name = group_name.strip().upper()
    today = date.today()
    max_date = today + timedelta(days=14)
    today_str = today.strftime("%Y-%m-%d")
    max_date_str = max_date.strftime("%Y-%m-%d")

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT s.*, 
                   COUNT(q.id) as current_count
            FROM schedule_slots s
            LEFT JOIN queue_entries q ON s.id = q.slot_id
            WHERE s.group_name = ?
              AND s.slot_date >= ?
              AND s.slot_date <= ?
            GROUP BY s.id
            ORDER BY s.slot_date ASC, s.slot_time ASC
        """, (group_name, today_str, max_date_str))
        return [dict(row) for row in cursor.fetchall()]


def get_all_active_slots() -> List[dict]:
    """Все активные слоты по всем группам (для админа)"""
    cleanup_old_entries()
    today_str = date.today().strftime("%Y-%m-%d")
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT s.*, COUNT(q.id) as current_count
            FROM schedule_slots s
            LEFT JOIN queue_entries q ON s.id = q.slot_id
            WHERE s.slot_date >= ?
            GROUP BY s.id
            ORDER BY s.group_name ASC, s.slot_date ASC, s.slot_time ASC
        """, (today_str,))
        return [dict(row) for row in cursor.fetchall()]


def get_slot_by_id(slot_id: int) -> Optional[dict]:
    cleanup_old_entries()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM schedule_slots WHERE id = ?", (slot_id,))
        row = cursor.fetchone()
        return dict(row) if row else None


def delete_schedule_slot(slot_id: int):
    """Удаляет слот и все связанные записи в очереди"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM queue_entries WHERE slot_id = ?", (slot_id,))
        cursor.execute("DELETE FROM schedule_slots WHERE id = ?", (slot_id,))
        conn.commit()


def clear_queue_for_slot(slot_id: int):
    """Очищает очередь для слота (удаляет всех записавшихся)"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM queue_entries WHERE slot_id = ?", (slot_id,))
        conn.commit()


# ================= Очереди (Запись студентов) =================

def join_queue(slot_id: int, user_id: int) -> Tuple[bool, str]:
    """
    Записывает студента в очередь на выбранный слот.
    Проверяет лимит мест и отсутствие дубликата записи.
    """
    cleanup_old_entries()
    slot = get_slot_by_id(slot_id)
    if not slot:
        return False, "Слот сдачи не найден или уже прошел."

    with get_connection() as conn:
        cursor = conn.cursor()
        
        # Проверяем, не записан ли уже студент на этот слот
        cursor.execute("SELECT id FROM queue_entries WHERE slot_id = ? AND user_id = ?", (slot_id, user_id))
        if cursor.fetchone():
            return False, "Вы уже находитесь в очереди на эту сдачу!"

        # Проверяем лимит мест
        if slot["max_students"] > 0:
            cursor.execute("SELECT COUNT(*) as cnt FROM queue_entries WHERE slot_id = ?", (slot_id,))
            cnt = cursor.fetchone()["cnt"]
            if cnt >= slot["max_students"]:
                return False, f"К сожалению, лимит мест ({slot['max_students']}) в этой очереди исчерпан."

        # Записываем в очередь
        cursor.execute("""
            INSERT INTO queue_entries (slot_id, user_id)
            VALUES (?, ?)
        """, (slot_id, user_id))
        conn.commit()

        # Узнаем порядковый номер
        cursor.execute("SELECT COUNT(*) as position FROM queue_entries WHERE slot_id = ? AND id <= (SELECT id FROM queue_entries WHERE slot_id = ? AND user_id = ?)", (slot_id, slot_id, user_id))
        pos = cursor.fetchone()["position"]
        return True, f"Вы успешно записались в очередь! Ваш номер: #{pos}"


def leave_queue(slot_id: int, user_id: int) -> bool:
    """Удаляет запись студента из конкретной очереди"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM queue_entries WHERE slot_id = ? AND user_id = ?", (slot_id, user_id))
        conn.commit()
        return cursor.rowcount > 0


def get_queue_for_slot(slot_id: int) -> List[dict]:
    """Возвращает упорядоченный список студентов в очереди для слота"""
    cleanup_old_entries()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT q.id as entry_id, q.joined_at, u.user_id, u.full_name, u.group_name
            FROM queue_entries q
            JOIN users u ON q.user_id = u.user_id
            WHERE q.slot_id = ?
            ORDER BY q.id ASC
        """, (slot_id,))
        return [dict(row) for row in cursor.fetchall()]


def remove_first_from_queue(slot_id: int) -> Optional[dict]:
    """Вызывает (удаляет) первого студента из очереди («Следующий!»)"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT q.id as entry_id, u.user_id, u.full_name, u.group_name
            FROM queue_entries q
            JOIN users u ON q.user_id = u.user_id
            WHERE q.slot_id = ?
            ORDER BY q.id ASC
            LIMIT 1
        """, (slot_id,))
        first_student = cursor.fetchone()
        if first_student:
            student_dict = dict(first_student)
            cursor.execute("DELETE FROM queue_entries WHERE id = ?", (student_dict["entry_id"],))
            conn.commit()
            return student_dict
        return None


def get_user_active_queues(user_id: int) -> List[dict]:
    """Возвращает список очередей, в которых сейчас записан студент"""
    cleanup_old_entries()
    today_str = date.today().strftime("%Y-%m-%d")
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT q.id as entry_id, s.id as slot_id, s.group_name, s.subject, 
                   s.slot_date, s.slot_time
            FROM queue_entries q
            JOIN schedule_slots s ON q.slot_id = s.id
            WHERE q.user_id = ? AND s.slot_date >= ?
            ORDER BY s.slot_date ASC, s.slot_time ASC
        """, (user_id, today_str))
        return [dict(row) for row in cursor.fetchall()]
