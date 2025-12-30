# check_db.py - проверка содержимого базы данных
import sqlite3

conn = sqlite3.connect('bot_database.db')
cursor = conn.cursor()

# Проверяем таблицу товаров
cursor.execute("SELECT * FROM products")
products = cursor.fetchall()

print("=== ТОВАРЫ В БАЗЕ ДАННЫХ ===")
print(f"Всего товаров: {len(products)}")
for product in products:
    print(f"ID: {product[0]}, Название: {product[1]}, Цена: {product[3]}")

conn.close()