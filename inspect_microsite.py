import os

print("=== MENCARI FILE TEMPLATE MICROSITE / STOREFRONT ===")
for root, _, files in os.walk('.'):
    if any(x in root for x in ['node_modules', '.git', '__pycache__', 'tests']):
        continue
    for f in files:
        if f.endswith(('.html', '.jinja', '.jinja2', '.py')):
            fp = os.path.join(root, f)
            try:
                with open(fp, 'r', encoding='utf-8', errors='ignore') as s:
                    txt = s.read()
                    if 'Pilihan Produk' in txt or 'single_page' in txt or 'storefront_template' in txt or 'shabu-ajhi' in txt:
                        print(f"File relevan: {fp}")
            except Exception:
                pass
