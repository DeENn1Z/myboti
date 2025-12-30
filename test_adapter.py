from database_adapter import db

# Тестируем получение товаров
print("=== ТЕСТ БАЗЫ ДАННЫХ ===")
products = db.get_all_products()
print(f"Товаров в базе: {len(products)}")

for product in products:
    print(f"ID: {product['id']}, Название: {product['title']}, Цена: {product['price_rub']} руб.")

# Тестируем получение одного товара
print("\n=== ТЕСТ ПОЛУЧЕНИЯ ТОВАРА ===")
test_product = db.get_product('p1')
if test_product:
    print(f"Товар p1: {test_product['name']}, {test_product['price']} руб., {test_product['days']} дней")