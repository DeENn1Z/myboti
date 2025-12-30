# remove_test_user.py
import sqlite3

conn = sqlite3.connect('bot_database.db')
cursor = conn.cursor()

# Удаляем пользователя с вашим ID
cursor.execute("DELETE FROM users WHERE user_id = 7784754900")
conn.commit()

print("✅ Тестовый пользователь удалён из базы данных")
conn.close()