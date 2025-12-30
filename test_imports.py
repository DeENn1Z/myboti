# test_imports.py - проверка корректности импортов
try:
    from database_adapter import get_product_from_db, load_products_from_db
    
    # Тест 1: Загрузка всех товаров
    products = load_products_from_db()
    print(f"✅ load_products_from_db работает. Товаров: {len(products.get('products', []))}")
    
    # Тест 2: Получение одного товара
    product = get_product_from_db('p1')
    if product:
        print(f"✅ get_product_from_db работает. Товар p1: {product['name']}")
    else:
        print("❌ get_product_from_db не нашёл товар p1")
        
except ImportError as e:
    print(f"❌ Ошибка импорта: {e}")
except Exception as e:
    print(f"❌ Другая ошибка: {e}")