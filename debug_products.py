import json

print("=== АНАЛИЗ products.json ===")

with open('products.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

print(f"Тип данных: {type(data)}")
print(f"Ключи: {list(data.keys()) if isinstance(data, dict) else 'это список'}")

if isinstance(data, dict) and 'products' in data:
    products = data['products']
else:
    products = data

print(f"\nНайдено товаров: {len(products)}")

for i, product in enumerate(products):
    print(f"\n--- Товар #{i+1} ---")
    for key, value in product.items():
        print(f"  {key}: {repr(value)} (тип: {type(value).__name__})")
        