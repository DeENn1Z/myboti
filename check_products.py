import sqlite3

conn = sqlite3.connect('bot_database.db')
cursor = conn.cursor()

print("=== ТОВАРЫ В БАЗЕ ДАННЫХ ===")
cursor.execute("SELECT id, title, price_rub, days FROM products")
products = cursor.fetchall()

for product in products:
    print(f"ID: {product[0]}, Название: {product[1]}, Цена: {product[2]} руб., Дней: {product[3]}")

print(f"\nВсего товаров в базе: {len(products)}")
conn.close()