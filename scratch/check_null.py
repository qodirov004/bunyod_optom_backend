import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "set_app.settings")
django.setup()

from set_main.models import CashTransactionMod, Texnics, Product, DriverSalary

def check_none(model, field):
    count = model.objects.filter(currency__isnull=True).count()
    if count > 0:
        first = model.objects.filter(currency__isnull=True).first()
        val = getattr(first, field, None)
        print(f"{model.__name__}: {count} items with NULL currency. Example {field}: {val}")
    else:
        print(f"{model.__name__}: 0 items with NULL currency.")

check_none(Texnics, 'price')
check_none(CashTransactionMod, 'amount')
check_none(Product, 'price')
check_none(DriverSalary, 'amount')
