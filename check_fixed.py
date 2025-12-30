import sqlite3

conn = sqlite3.connect('bot_database.db')
cursor = conn.cursor()

print("=== ПРОВЕРКА БАЗЫ ДАННЫХ ===")

# Проверяем структуру таблицы products
cursor.execute("PRAGMA table_info(products)")
columns = cursor.fetchall()
print("\nСтруктура таблицы products:")
for col in columns:
    print(f"  {col[1]} ({col[2]})")

# Проверяем товары
cursor.execute("SELECT * FROM products")
products = cursor.fetchall()

print(f"\nЗагружено товаров: {len(products)}")
for product in products:
    print(f"\nТовар: {product[1]}")
    print(f"  ID: {product[0]}")
    print(f"  Цена в рублях: {product[6]} руб.")
    print(f"  Цена в звёздах: {product[3]} stars")
    print(f"  Дней подписки: {product[7]}")

conn.close()