# test_product_handler.py - проверяем получение товара
from database_adapter import get_product_from_db

print("=== ТЕСТ ПОЛУЧЕНИЯ ТОВАРА ===")

# Тест 1: Существующий товар
product = get_product_from_db('p6')
if product:
    print(f"✅ Товар p6 найден: {product.get('name', product.get('title'))}")
    print(f"   Цена: {product.get('price', product.get('price_rub'))} руб.")
    print(f"   Дней: {product.get('days')}")
else:
    print("❌ Товар p6 не найден")

# Тест 2: Несуществующий товар
product2 = get_product_from_db('nonexistent')
if not product2:
    print("✅ Несуществующий товар корректно возвращает None")
else:
    print("❌ Несуществующий товар должен возвращать None")