from django.core.management.base import BaseCommand
from set_main.models import (
    CurrencyRate, Texnics, BalonMod, BalonFurgon, ChiqimlikMod, 
    OptolMod, DriverSalary, Product, RaysMod, RaysHistoryMod, 
    RaysHistoryProduct, RaysHistoryExpense, CashTransactionMod, 
    CashTransactionHistory, FuelMod
)
from decimal import Decimal

class Command(BaseCommand):
    help = 'Migrate all USD values to UZS'

    def handle(self, *args, **kwargs):
        try:
            usd_currency = CurrencyRate.objects.get(currency='USD')
        except CurrencyRate.DoesNotExist:
            self.stdout.write(self.style.WARNING("USD currency not found, maybe already migrated or doesn't exist."))
            usd_currency = None

        try:
            uzs_currency, _ = CurrencyRate.objects.get_or_create(
                currency='UZS',
                defaults={'rate_to_uzs': 1.0}
            )
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"UZS currency error: {e}"))
            return

        RATE = Decimal('12800')
        INT_RATE = 12800

        def migrate_model(model_class, price_field='price', currency_field='currency'):
            if not usd_currency:
                return
            count = 0
            items = model_class.objects.filter(**{f"{currency_field}": usd_currency})

            for item in items:
                old_val = getattr(item, price_field)
                if old_val is not None:
                    setattr(item, price_field, old_val * RATE if isinstance(old_val, Decimal) else old_val * INT_RATE)
                setattr(item, currency_field, uzs_currency)
                item.save(update_fields=[price_field, currency_field])
                count += 1
            self.stdout.write(self.style.SUCCESS(f"Migrated {count} records in {model_class.__name__} (field: {price_field})"))

        # 1. Models with currency field (Only if currency == USD)
        migrate_model(Texnics)
        migrate_model(BalonMod)
        migrate_model(BalonFurgon)
        migrate_model(ChiqimlikMod)
        migrate_model(OptolMod)
        migrate_model(FuelMod)
        migrate_model(DriverSalary, price_field='amount')
        migrate_model(Product)

        # CashTransactionMod and CashTransactionHistory
        if usd_currency:
            for model_class in [CashTransactionMod, CashTransactionHistory]:
                count = 0
                for item in model_class.objects.filter(currency=usd_currency):
                    if item.amount is not None:
                        item.amount = item.amount * INT_RATE
                    if item.amount_in_usd is not None:
                        item.amount_in_usd = item.amount_in_usd * RATE
                    if item.total_expected_amount is not None:
                        item.total_expected_amount = item.total_expected_amount * RATE
                    if item.paid_amount is not None:
                        item.paid_amount = item.paid_amount * RATE
                    if item.remaining_debt is not None:
                        item.remaining_debt = item.remaining_debt * RATE
                    item.currency = uzs_currency
                    item.save(update_fields=[
                        'amount', 'amount_in_usd', 'total_expected_amount', 
                        'paid_amount', 'remaining_debt', 'currency'
                    ])
                    count += 1
                self.stdout.write(self.style.SUCCESS(f"Migrated {count} records in {model_class.__name__}"))

        # 2. RaysMod and RaysHistoryMod
        # We multiply by 12800 if the value is < 1,000,000 (which safely distinguishes USD vs UZS for total sums)
        for model_class in [RaysMod, RaysHistoryMod]:
            count = 0
            for item in model_class.objects.all():
                updated = False
                if item.price is not None and 0 < item.price < 500000:
                    item.price *= INT_RATE; updated = True
                if item.dr_price is not None and 0 < item.dr_price < 500000:
                    item.dr_price *= INT_RATE; updated = True
                if item.dp_price is not None and 0 < item.dp_price < 500000:
                    item.dp_price *= INT_RATE; updated = True
                if item.driver_expense is not None and 0 < item.driver_expense < 500000:
                    item.driver_expense *= INT_RATE; updated = True
                if item.returned_advance is not None and 0 < item.returned_advance < 500000:
                    item.returned_advance *= INT_RATE; updated = True

                if updated:
                    # Also set dp_currency if it was USD
                    if usd_currency and getattr(item, 'dp_currency', None) == usd_currency:
                        item.dp_currency = uzs_currency
                        item.save(update_fields=['price', 'dr_price', 'dp_price', 'driver_expense', 'returned_advance', 'dp_currency'])
                    else:
                        item.save(update_fields=['price', 'dr_price', 'dp_price', 'driver_expense', 'returned_advance'])
                    count += 1
            self.stdout.write(self.style.SUCCESS(f"Migrated {count} records in {model_class.__name__}"))

        # RaysHistoryProduct
        count = 0
        for item in RaysHistoryProduct.objects.all():
            if item.price and 0 < item.price < 500000:
                item.price *= INT_RATE
                item.save(update_fields=['price'])
                count += 1
        self.stdout.write(self.style.SUCCESS(f"Migrated {count} records in RaysHistoryProduct"))

        # RaysHistoryExpense
        count = 0
        for item in RaysHistoryExpense.objects.all():
            if item.price and 0 < item.price < 500000:
                item.price *= INT_RATE
                item.save(update_fields=['price'])
                count += 1
        self.stdout.write(self.style.SUCCESS(f"Migrated {count} records in RaysHistoryExpense"))

        self.stdout.write(self.style.SUCCESS("Successfully completed migration to UZS!"))
