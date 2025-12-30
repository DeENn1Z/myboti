# Файл: create_database.py
# Этот скрипт нужно запустить ОДИН РАЗ, чтобы создать базу данных и таблицу.

import sqlite3  # Импортируем модуль для работы с SQLite

# 1. Подключаемся к файлу базы данных. Если его нет - он создастся.
conn = sqlite3.connect('bot_database.db')

# 2. Создаем "курсор" - это специальный объект, который выполняет команды.
cursor = conn.cursor()

# 3. Пишем команду на языке SQL для создания таблицы "users".
create_table_query = """
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,      -- ID пользователя в Телеграме (будет главным ключом)
    username TEXT,                    -- Имя пользователя (например, @ivanov)
    full_name TEXT,                   -- Полное имя
    subscription_end DATE,            -- Дата окончания подписки (в формате ГГГГ-ММ-ДД)
    is_admin BOOLEAN DEFAULT FALSE,   -- Является ли админом (по умолчанию - нет)
    reg_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP -- Дата регистрации (заполнится сама)
);
"""

# 4. Выполняем команду создания таблицы.
cursor.execute(create_table_query)

# 5. Сохраняем (коммитим) изменения в базе данных.
conn.commit()

# 6. Закрываем соединение.
conn.close()

print("[SUCCESS] База данных 'bot_database.db' и таблица 'users' успешно созданы!")