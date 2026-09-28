import re
import datetime
from typing import Optional

import telebot
from telebot import types

import config
import database

# Инициализируем бота и базу данных
bot = telebot.TeleBot(config.BOT_TOKEN, parse_mode="HTML")
database.init_db()

# Регулярные выражения для валидации
# Формат группы ИТМО: 1 буква (латиница или кириллица) + 4 цифры
GROUP_REGEX = re.compile(r'^[A-Za-zА-Яа-я]\d{4}$')


# ================= ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ =================

def normalize_group(group_str: str) -> str:
    """Приводит номер группы к верхнему регистру без пробелов"""
    return group_str.strip().upper()


def parse_date(date_str: str) -> Optional[datetime.date]:
    """Парсит дату в формате YYYY-MM-DD или DD.MM.YYYY"""
    date_str = date_str.strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.datetime.strptime(date_str, fmt).date()
        except ValueError:
            pass
    return None


def parse_time(time_str: str) -> Optional[str]:
    """Проверяет и форматирует время ЧЧ:ММ"""
    time_str = time_str.strip()
    try:
        t = datetime.datetime.strptime(time_str, "%H:%M").time()
        return t.strftime("%H:%M")
    except ValueError:
        return None


# ================= КЛАВИАТУРЫ =================

def get_main_keyboard(user_id: int):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    btn_schedule = types.KeyboardButton("📋 Расписание и запись")
    btn_my_queues = types.KeyboardButton("🙋‍♂️ Мои очереди")
    btn_profile = types.KeyboardButton("👤 Мой профиль")
    
    markup.add(btn_schedule, btn_my_queues)
    
    if config.is_admin(user_id):
        btn_admin = types.KeyboardButton("⚙️ Админ-панель")
        markup.add(btn_profile, btn_admin)
    else:
        markup.add(btn_profile)
    return markup


def get_admin_keyboard():
    markup = types.InlineKeyboardMarkup(row_width=2)
    btn_add_slot = types.InlineKeyboardButton("➕ Добавить сдачу (слот)", callback_data="admin_add_slot")
    btn_manage_slots = types.InlineKeyboardButton("📅 Список расписания", callback_data="admin_slots_list")
    btn_groups = types.InlineKeyboardButton("👥 Список групп", callback_data="admin_groups_list")
    btn_cleanup = types.InlineKeyboardButton("🧹 Очистить старые записи", callback_data="admin_cleanup")
    
    markup.add(btn_add_slot, btn_manage_slots)
    markup.add(btn_groups, btn_cleanup)
    return markup


# ================= СТАРТ И РЕГИСТРАЦИЯ =================

@bot.message_handler(commands=['start'])
def handle_start(message: types.Message):
    user_id = message.from_user.id
    user = database.get_user(user_id)
    
    if user:
        welcome_text = (
            f"👋 С возвращением, <b>{user['full_name']}</b>!\n"
            f"🎓 Группа: <code>{user['group_name']}</code>\n\n"
            f"Выберите необходимое действие в меню ниже:"
        )
        bot.send_message(message.chat.id, welcome_text, reply_markup=get_main_keyboard(user_id))
    else:
        reg_text = (
            "👋 <b>Добро пожаловать в бот очередей ИТМО!</b>\n\n"
            "Этот бот позволяет записываться в электронную очередь на сдачу лабораторных и домашних работ.\n\n"
            "📝 Для начала пройдем быструю регистрацию.\n"
            "Пожалуйста, введите ваше <b>ФИО полностью</b> (Фамилия Имя Отчество через пробел):\n"
            "<i>Пример: Иванов Иван Иванович</i>"
        )
        msg = bot.send_message(message.chat.id, reg_text)
        bot.register_next_step_handler(msg, process_reg_fio)


def process_reg_fio(message: types.Message):
    fio = message.text.strip() if message.text else ""
    parts = fio.split()
    
    if len(parts) < 2:
        msg = bot.reply_to(message, "⚠️ Пожалуйста, введите фамилию, имя и отчество (минимум 2 слова).\nПопробуйте еще раз:")
        bot.register_next_step_handler(msg, process_reg_fio)
        return

    msg = bot.send_message(
        message.chat.id,
        f"Отлично, <b>{fio}</b>!\n\n"
        "Теперь введите <b>номер вашей группы в ИТМО</b>:\n"
        "<i>Формат: буква и 4 цифры, например: <code>M3101</code>, <code>K3240</code>, <code>P3311</code></i>"
    )
    bot.register_next_step_handler(msg, process_reg_group, fio)


def process_reg_group(message: types.Message, fio: str):
    raw_group = message.text.strip() if message.text else ""
    group = normalize_group(raw_group)

    if not GROUP_REGEX.match(group):
        msg = bot.reply_to(
            message,
            "⚠️ Некорректный номер группы!\n"
            "В ИТМО номер группы обычно состоит из 1 буквы и 4 цифр (например, <b>M3101</b> или <b>P3311</b>).\n"
            "Попробуйте ввести номер группы еще раз:"
        )
        bot.register_next_step_handler(msg, process_reg_group, fio)
        return

    user_id = message.from_user.id
    database.save_user(user_id, fio, group)

    bot.send_message(
        message.chat.id,
        f"✅ <b>Регистрация успешно завершена!</b>\n\n"
        f"👤 Студент: <b>{fio}</b>\n"
        f"🎓 Группа: <code>{group}</code>\n\n"
        f"Теперь вы можете смотреть расписание и записываться в очереди.",
        reply_markup=get_main_keyboard(user_id)
    )


# ================= ПРОФИЛЬ =================

@bot.message_handler(func=lambda msg: msg.text == "👤 Мой профиль")
def handle_profile(message: types.Message):
    user = database.get_user(message.from_user.id)
    if not user:
        handle_start(message)
        return

    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("✏️ Изменить ФИО и группу", callback_data="edit_profile"))

    text = (
        "👤 <b>Ваш профиль:</b>\n\n"
        f"• <b>ФИО:</b> {user['full_name']}\n"
        f"• <b>Группа:</b> <code>{user['group_name']}</code>\n"
        f"• <b>Telegram ID:</b> <code>{user['user_id']}</code>"
    )
    bot.send_message(message.chat.id, text, reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data == "edit_profile")
def handle_edit_profile(call: types.CallbackQuery):
    bot.answer_callback_query(call.id)
    msg = bot.send_message(call.message.chat.id, "Введите новое <b>ФИО</b> (Фамилия Имя Отчество):")
    bot.register_next_step_handler(msg, process_reg_fio)


# ================= РАСПИСАНИЕ И ЗАПИСЬ В ОЧЕРЕДЬ =================

@bot.message_handler(func=lambda msg: msg.text == "📋 Расписание и запись")
def handle_schedule(message: types.Message):
    user = database.get_user(message.from_user.id)
    if not user:
        handle_start(message)
        return

    group = user["group_name"]
    slots = database.get_available_slots_for_group(group)

    if not slots:
        bot.send_message(
            message.chat.id,
            f"📅 Для группы <code>{group}</code> сейчас <b>нет активных слотов сдачи</b> на ближайшие 2 недели.\n\n"
            "Ожидайте, пока преподаватель или администратор добавит расписание."
        )
        return

    text = (
        f"📅 <b>Расписание сдачи для группы {group}</b>\n"
        f"<i>(доступно бронирование максимум на 2 недели вперед)</i>\n\n"
        f"Выберите пару для записи в очередь:"
    )

    markup = types.InlineKeyboardMarkup(row_width=1)
    for slot in slots:
        limit_str = f"({slot['current_count']}/{slot['max_students']} мест)" if slot['max_students'] > 0 else f"({slot['current_count']} чел.)"
        btn_text = f"📍 {slot['slot_date']} в {slot['slot_time']} | {slot['subject']} {limit_str}"
        markup.add(types.InlineKeyboardButton(btn_text, callback_data=f"slot_info_{slot['id']}"))

    bot.send_message(message.chat.id, text, reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data.startswith("slot_info_"))
def handle_slot_info(call: types.CallbackQuery):
    bot.answer_callback_query(call.id)
    slot_id = int(call.data.replace("slot_info_", ""))
    slot = database.get_slot_by_id(slot_id)
    
    if not slot:
        bot.send_message(call.message.chat.id, "⚠️ Этот слот уже завершен или удален.")
        return

    queue = database.get_queue_for_slot(slot_id)
    user_id = call.from_user.id
    
    # Формируем список очереди
    limit_text = f" (максимум {slot['max_students']} человек)" if slot['max_students'] > 0 else " (без лимита)"
    queue_text = f"📌 <b>Информация о сдаче:</b>\n"
    queue_text += f"• Предмет / Задание: <b>{slot['subject']}</b>\n"
    queue_text += f"• Группа: <code>{slot['group_name']}</code>\n"
    queue_text += f"• Дата и время: <b>{slot['slot_date']} в {slot['slot_time']}</b>{limit_text}\n\n"
    queue_text += "👥 <b>Текущая очередь:</b>\n"

    user_is_in_queue = False
    user_pos = 0

    if queue:
        for idx, student in enumerate(queue, 1):
            marker = " 👉 (Вы)" if student["user_id"] == user_id else ""
            if student["user_id"] == user_id:
                user_is_in_queue = True
                user_pos = idx
            queue_text += f"{idx}. {student['full_name']}{marker}\n"
    else:
        queue_text += "<i>Очередь пока пуста. Вы можете быть первым!</i>\n"

    markup = types.InlineKeyboardMarkup(row_width=1)
    if user_is_in_queue:
        queue_text += f"\n✅ Вы записаны в эту очередь под номером <b>#{user_pos}</b>."
        markup.add(types.InlineKeyboardButton("❌ Выйти из очереди", callback_data=f"leave_queue_{slot_id}"))
    else:
        markup.add(types.InlineKeyboardButton("🙋‍♂️ Встать в очередь", callback_data=f"join_queue_{slot_id}"))

    markup.add(types.InlineKeyboardButton("🔄 Обновить список", callback_data=f"slot_info_{slot_id}"))
    bot.send_message(call.message.chat.id, queue_text, reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data.startswith("join_queue_"))
def handle_join_queue(call: types.CallbackQuery):
    slot_id = int(call.data.replace("join_queue_", ""))
    user_id = call.from_user.id
    user = database.get_user(user_id)

    if not user:
        bot.answer_callback_query(call.id, "Сначала зарегистрируйтесь через /start", show_alert=True)
        return

    success, message = database.join_queue(slot_id, user_id)
    bot.answer_callback_query(call.id, message, show_alert=True)
    # Обновляем экран слота
    handle_slot_info(call)


@bot.callback_query_handler(func=lambda call: call.data.startswith("leave_queue_"))
def handle_leave_queue(call: types.CallbackQuery):
    slot_id = int(call.data.replace("leave_queue_", ""))
    user_id = call.from_user.id

    if database.leave_queue(slot_id, user_id):
        bot.answer_callback_query(call.id, "Вы успешно покинули очередь.", show_alert=True)
    else:
        bot.answer_callback_query(call.id, "Вы не были записаны в эту очередь.", show_alert=True)
    handle_slot_info(call)


# ================= МОИ ОЧЕРЕДИ =================

@bot.message_handler(func=lambda msg: msg.text == "🙋‍♂️ Мои очереди")
def handle_my_queues(message: types.Message):
    user_id = message.from_user.id
    user = database.get_user(user_id)
    if not user:
        handle_start(message)
        return

    queues = database.get_user_active_queues(user_id)
    if not queues:
        bot.send_message(
            message.chat.id,
            "ℹ️ Сейчас вы не записаны ни в одну активную очередь.\n"
            "Нажмите <b>📋 Расписание и запись</b>, чтобы выбрать сдачу."
        )
        return

    text = "📋 <b>Ваши активные записи в очереди:</b>\n\n"
    markup = types.InlineKeyboardMarkup(row_width=1)

    for q in queues:
        # Узнаем порядковый номер в очереди
        slot_queue = database.get_queue_for_slot(q["slot_id"])
        pos = next((idx for idx, s in enumerate(slot_queue, 1) if s["user_id"] == user_id), None)
        pos_str = f"#{pos}" if pos else "?"

        text += (
            f"• <b>{q['subject']}</b> ({q['group_name']})\n"
            f"  📅 {q['slot_date']} в {q['slot_time']} — Ваше место: <b>{pos_str}</b>\n\n"
        )
        markup.add(
            types.InlineKeyboardButton(f"❌ Отменить запись: {q['subject']}", callback_data=f"leave_queue_{q['slot_id']}")
        )

    bot.send_message(message.chat.id, text, reply_markup=markup)


# ================= АДМИН-ПАНЕЛЬ (УПРАВЛЕНИЕ РАСПИСАНИЕМ) =================

@bot.message_handler(commands=['admin'])
@bot.message_handler(func=lambda msg: msg.text == "⚙️ Админ-панель")
def handle_admin_panel(message: types.Message):
    if not config.is_admin(message.from_user.id):
        bot.reply_to(message, "⛔ У вас нет прав администратора для управления расписанием.")
        return

    text = (
        "⚙️ <b>Панель администратора сервера очередей</b>\n\n"
        "Здесь вы можете:\n"
        "• Добавлять пары/слоты сдачи для <b>любой группы</b>\n"
        "• Просматривать и редактировать расписание\n"
        "• Вызывать следующих студентов («Следующий!»)\n"
        "• Очищать очереди и прошедшие записи\n"
        "• Добавлять/удалять группы"
    )
    bot.send_message(message.chat.id, text, reply_markup=get_admin_keyboard())


@bot.callback_query_handler(func=lambda call: call.data == "admin_cleanup")
def handle_admin_cleanup(call: types.CallbackQuery):
    if not config.is_admin(call.from_user.id):
        return
    database.cleanup_old_entries()
    bot.answer_callback_query(call.id, "🧹 Прошедшие записи и слоты успешно очищены!", show_alert=True)


@bot.callback_query_handler(func=lambda call: call.data == "admin_groups_list")
def handle_admin_groups(call: types.CallbackQuery):
    if not config.is_admin(call.from_user.id):
        return
    bot.answer_callback_query(call.id)
    groups = database.get_all_groups()
    if not groups:
        text = "👥 Список зарегистрированных групп пуст."
    else:
        text = "👥 <b>Список групп в системе:</b>\n\n" + "\n".join(f"• <code>{g}</code>" for g in groups)

    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("➕ Добавить новую группу", callback_data="admin_add_group_prompt"))
    bot.send_message(call.message.chat.id, text, reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data == "admin_add_group_prompt")
def handle_admin_add_group_prompt(call: types.CallbackQuery):
    if not config.is_admin(call.from_user.id):
        return
    bot.answer_callback_query(call.id)
    msg = bot.send_message(call.message.chat.id, "Введите номер новой группы (например: <code>M3101</code>):")
    bot.register_next_step_handler(msg, process_admin_add_group)


def process_admin_add_group(message: types.Message):
    if not config.is_admin(message.from_user.id):
        return
    group = normalize_group(message.text or "")
    if not GROUP_REGEX.match(group):
        msg = bot.reply_to(message, "⚠️ Неверный формат группы (должна быть 1 буква и 4 цифры). Попробуйте еще раз:")
        bot.register_next_step_handler(msg, process_admin_add_group)
        return

    database.add_group(group)
    bot.send_message(message.chat.id, f"✅ Группа <code>{group}</code> успешно добавлена в систему!", reply_markup=get_admin_keyboard())


# --- Пошаговое добавление слота сдачи админом ---

@bot.callback_query_handler(func=lambda call: call.data == "admin_add_slot")
def handle_admin_add_slot(call: types.CallbackQuery):
    if not config.is_admin(call.from_user.id):
        return
    bot.answer_callback_query(call.id)

    msg = bot.send_message(
        call.message.chat.id,
        "➕ <b>Создание нового слота сдачи в расписании</b>\n\n"
        "Шаг 1/5: Введите <b>номер группы</b> (например: <code>M3101</code> или <code>P3311</code>):\n"
        "<i>Можно указать любую новую группу — бот автоматически добавит её в базу!</i>"
    )
    bot.register_next_step_handler(msg, process_slot_group)


def process_slot_group(message: types.Message):
    group = normalize_group(message.text or "")
    if not GROUP_REGEX.match(group):
        msg = bot.reply_to(message, "⚠️ Неверный формат группы ИТМО (буква + 4 цифры). Введите группу еще раз:")
        bot.register_next_step_handler(msg, process_slot_group)
        return

    msg = bot.send_message(
        message.chat.id,
        f"Группа: <code>{group}</code>\n\n"
        "Шаг 2/5: Введите <b>название предмета / лабораторной работы</b>:\n"
        "<i>Пример: Веб-программирование (ЛР №2)</i>"
    )
    bot.register_next_step_handler(msg, process_slot_subject, group)


def process_slot_subject(message: types.Message, group: str):
    subject = message.text.strip() if message.text else ""
    if not subject:
        msg = bot.reply_to(message, "⚠️ Название предмета не может быть пустым. Введите название:")
        bot.register_next_step_handler(msg, process_slot_subject, group)
        return

    today = datetime.date.today()
    max_date = today + datetime.timedelta(days=14)

    msg = bot.send_message(
        message.chat.id,
        f"Предмет: <b>{subject}</b>\n\n"
        "Шаг 3/5: Введите <b>дату проведения сдачи</b> в формате <code>ДД.ММ.ГГГГ</code> (или <code>ГГГГ-ММ-ДД</code>):\n"
        f"<i>Правило: максимум 2 недели вперед (с {today.strftime('%d.%m.%Y')} по {max_date.strftime('%d.%m.%Y')})</i>"
    )
    bot.register_next_step_handler(msg, process_slot_date, group, subject)


def process_slot_date(message: types.Message, group: str, subject: str):
    parsed = parse_date(message.text or "")
    today = datetime.date.today()
    max_date = today + datetime.timedelta(days=14)

    if not parsed:
        msg = bot.reply_to(message, "⚠️ Неверный формат даты. Введите дату в виде <code>ДД.ММ.ГГГГ</code> (например, 29.09.2026):")
        bot.register_next_step_handler(msg, process_slot_date, group, subject)
        return

    if parsed < today:
        msg = bot.reply_to(message, "⚠️ Дата не может быть в прошлом! Введите будущую дату:")
        bot.register_next_step_handler(msg, process_slot_date, group, subject)
        return

    if parsed > max_date:
        msg = bot.reply_to(
            message,
            f"⚠️ Запись возможна <b>максимум на 2 недели вперед</b> (до {max_date.strftime('%d.%m.%Y')}).\n"
            f"Введите допустимую дату:"
        )
        bot.register_next_step_handler(msg, process_slot_date, group, subject)
        return

    date_str = parsed.strftime("%Y-%m-%d")
    msg = bot.send_message(
        message.chat.id,
        f"Дата: <b>{date_str}</b>\n\n"
        "Шаг 4/5: Введите <b>время начала</b> в формате <code>ЧЧ:ММ</code>:\n"
        "<i>Пример: 10:00 или 15:20</i>"
    )
    bot.register_next_step_handler(msg, process_slot_time, group, subject, date_str)


def process_slot_time(message: types.Message, group: str, subject: str, date_str: str):
    t = parse_time(message.text or "")
    if not t:
        msg = bot.reply_to(message, "⚠️ Неверный формат времени! Введите время в формате <code>ЧЧ:ММ</code> (например, 11:40):")
        bot.register_next_step_handler(msg, process_slot_time, group, subject, date_str)
        return

    msg = bot.send_message(
        message.chat.id,
        f"Время: <b>{t}</b>\n\n"
        "Шаг 5/5: Введите <b>максимальное количество мест в очереди</b>:\n"
        "<i>Введите 0, если лимита нет (очередь без ограничений)</i>"
    )
    bot.register_next_step_handler(msg, process_slot_limit, group, subject, date_str, t)


def process_slot_limit(message: types.Message, group: str, subject: str, date_str: str, time_str: str):
    raw_val = (message.text or "").strip()
    if not raw_val.isdigit():
        msg = bot.reply_to(message, "⚠️ Введите целое число (0 для отсутствия ограничений):")
        bot.register_next_step_handler(msg, process_slot_limit, group, subject, date_str, time_str)
        return

    max_students = int(raw_val)
    slot_id = database.add_schedule_slot(
        group_name=group,
        subject=subject,
        slot_date=date_str,
        slot_time=time_str,
        max_students=max_students
    )

    limit_desc = f"{max_students} человек" if max_students > 0 else "без ограничений"
    bot.send_message(
        message.chat.id,
        f"✅ <b>Слот сдачи успешно добавлен в расписание!</b>\n\n"
        f"• ID слота: <code>{slot_id}</code>\n"
        f"• Группа: <code>{group}</code>\n"
        f"• Предмет: <b>{subject}</b>\n"
        f"• Дата и время: <b>{date_str} в {time_str}</b>\n"
        f"• Лимит очереди: <b>{limit_desc}</b>",
        reply_markup=get_admin_keyboard()
    )


# --- Просмотр и управление активными слотами админом ---

@bot.callback_query_handler(func=lambda call: call.data == "admin_slots_list")
def handle_admin_slots_list(call: types.CallbackQuery):
    if not config.is_admin(call.from_user.id):
        return
    bot.answer_callback_query(call.id)
    slots = database.get_all_active_slots()

    if not slots:
        bot.send_message(call.message.chat.id, "📅 Нет активных слотов расписания.", reply_markup=get_admin_keyboard())
        return

    text = "📅 <b>Все активные слоты сдачи:</b>\nНажмите на слот для управления очередью:\n"
    markup = types.InlineKeyboardMarkup(row_width=1)

    for s in slots:
        btn_text = f"[{s['group_name']}] {s['slot_date']} {s['slot_time']} | {s['subject']} ({s['current_count']} чел.)"
        markup.add(types.InlineKeyboardButton(btn_text, callback_data=f"admin_manage_slot_{s['id']}"))

    bot.send_message(call.message.chat.id, text, reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data.startswith("admin_manage_slot_"))
def handle_admin_manage_slot(call: types.CallbackQuery):
    if not config.is_admin(call.from_user.id):
        return
    bot.answer_callback_query(call.id)
    slot_id = int(call.data.replace("admin_manage_slot_", ""))
    slot = database.get_slot_by_id(slot_id)

    if not slot:
        bot.send_message(call.message.chat.id, "⚠️ Этот слот уже удален.")
        return

    queue = database.get_queue_for_slot(slot_id)
    text = (
        f"⚙️ <b>Управление слотом #{slot['id']}</b>\n\n"
        f"• Группа: <code>{slot['group_name']}</code>\n"
        f"• Предмет: <b>{slot['subject']}</b>\n"
        f"• Дата/Время: <b>{slot['slot_date']} в {slot['slot_time']}</b>\n"
        f"• Всего в очереди: <b>{len(queue)}</b> чел.\n\n"
        f"👥 <b>Список студентов:</b>\n"
    )

    if queue:
        for idx, student in enumerate(queue, 1):
            text += f"{idx}. {student['full_name']} (<code>{student['user_id']}</code>)\n"
    else:
        text += "<i>В очереди никого нет.</i>\n"

    markup = types.InlineKeyboardMarkup(row_width=2)
    if queue:
        markup.add(types.InlineKeyboardButton("📢 Вызвать следующего", callback_data=f"admin_next_{slot_id}"))
        markup.add(types.InlineKeyboardButton("🧹 Очистить очередь", callback_data=f"admin_clear_queue_{slot_id}"))

    markup.add(types.InlineKeyboardButton("❌ Удалить весь слот", callback_data=f"admin_del_slot_{slot_id}"))
    markup.add(types.InlineKeyboardButton("⬅️ Назад к списку", callback_data="admin_slots_list"))

    bot.send_message(call.message.chat.id, text, reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data.startswith("admin_next_"))
def handle_admin_next(call: types.CallbackQuery):
    if not config.is_admin(call.from_user.id):
        return
    slot_id = int(call.data.replace("admin_next_", ""))
    student = database.remove_first_from_queue(slot_id)

    if student:
        bot.answer_callback_query(call.id, f"Студент {student['full_name']} вызван на сдачу!", show_alert=True)
        # Отправляем уведомление студенту, если возможно
        try:
            bot.send_message(
                student["user_id"],
                f"🔔 <b>Ваша очередь подошла!</b>\n"
                f"Преподаватель вызывает вас на сдачу работы."
            )
        except Exception:
            pass
    else:
        bot.answer_callback_query(call.id, "В очереди больше никого нет.", show_alert=True)

    handle_admin_manage_slot(call)


@bot.callback_query_handler(func=lambda call: call.data.startswith("admin_clear_queue_"))
def handle_admin_clear_queue(call: types.CallbackQuery):
    if not config.is_admin(call.from_user.id):
        return
    slot_id = int(call.data.replace("admin_clear_queue_", ""))
    database.clear_queue_for_slot(slot_id)
    bot.answer_callback_query(call.id, "Все предыдущие записи в этой очереди удалены!", show_alert=True)
    handle_admin_manage_slot(call)


@bot.callback_query_handler(func=lambda call: call.data.startswith("admin_del_slot_"))
def handle_admin_del_slot(call: types.CallbackQuery):
    if not config.is_admin(call.from_user.id):
        return
    slot_id = int(call.data.replace("admin_del_slot_", ""))
    database.delete_schedule_slot(slot_id)
    bot.answer_callback_query(call.id, "Слот и очередь успешно удалены.", show_alert=True)
    handle_admin_slots_list(call)


# ================= ЗАПУСК БОТА =================

if __name__ == '__main__':
    print("=" * 50)
    print("🤖 Бот очередей ИТМО запущен!")
    print(f"Администраторы (ID): {list(config.ADMIN_IDS) if config.ADMIN_IDS else 'НЕ УКАЗАНЫ (добавьте в .env)'}")
    print("=" * 50)
    
    # skip_pending=True игнорирует сообщения, отправленные когда бот был офлайн
    bot.infinity_polling(skip_pending=True)
