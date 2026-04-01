import os
import django

# Set up Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'set_app.settings')
django.setup()

from set_main.models import CashCategory, ChiqimlarCategory

def seed_categories():
    # Seed CashCategory (for payment_way)
    cash_categories = ['Naqd', 'Karta', 'O\'tkazma (Perechisleniye)']
    for name in cash_categories:
        obj, created = CashCategory.objects.get_or_create(name=name)
        if created:
            print(f"Created CashCategory: {name} (ID: {obj.id})")
        else:
            print(f"CashCategory already exists: {name} (ID: {obj.id})")

    # Seed ChiqimlarCategory (just in case)
    expense_categories = ['Yoqilg\'i', 'Ta\'mirlash', 'Ovqat', 'Boshqa']
    for name in expense_categories:
        obj, created = ChiqimlarCategory.objects.get_or_create(name=name)
        if created:
            print(f"Created ChiqimlarCategory: {name} (ID: {obj.id})")
        else:
            print(f"ChiqimlarCategory already exists: {name} (ID: {obj.id})")

if __name__ == '__main__':
    seed_categories()
