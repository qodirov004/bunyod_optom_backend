import os
import sys
import django

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'set_app.settings')
django.setup()

from set_main.models import RaysMod, RaysHistoryMod, CashTransactionMod, CashTransactionHistory

print("=== ACTIVE RAYS ===")
for r in RaysMod.objects.all():
    print(f"ID: {r.id}, Driver: {r.driver}, Completed: {r.is_completed}, Price: {r.price}")

print("\n=== HISTORY RAYS ===")
for r in RaysHistoryMod.objects.all():
    print(f"ID: {r.id}, Original ID: {r.rays_id}, Driver: {r.driver}, Price: {r.price}")

print("\n=== ACTIVE TRANSACTIONS (MOD) ===")
for t in CashTransactionMod.objects.all():
    print(f"ID: {t.id}, Client: {t.client}, Rays: {t.rays_id}, Amount: {t.amount}, Status: {t.status}, ConfirmedByCashier: {t.is_confirmed_by_cashier}")

print("\n=== HISTORY TRANSACTIONS ===")
for t in CashTransactionHistory.objects.all():
    print(f"ID: {t.id}, Client: {t.client}, Rays: {t.rays_id}, RaysHistory: {t.rays_history_id}, Amount: {t.amount}, Status: {t.status}, ConfirmedByCashier: {t.is_confirmed_by_cashier}")
