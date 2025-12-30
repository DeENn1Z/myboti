import sqlite3

conn = sqlite3.connect('bot_database.db')
cursor = conn.cursor()

cursor.execute("SELECT * FROM users")
users = cursor.fetchall()

print(f"Пользователей в базе: {len(users)}")
for user in users:
    print(f"ID: {user[0]}, Имя: {user[2]}, Дата регистрации: {user[5]}")

conn.close()