import os
import sys
import django
from django.db.models import Q, Sum

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'set_app.settings')
django.setup()

from set_main.models import RaysMod, RaysHistoryMod, CashTransactionHistory, CurrencyRate
from rest_framework.test import APIRequestFactory
from set_main.views import CashTransactionViewSet

print("Initializing test request context...")
factory = APIRequestFactory()
wsgi_request = factory.get('/api/casa/overview/')
from rest_framework.request import Request
drf_request = Request(wsgi_request)

view = CashTransactionViewSet()
# Set format and action
view.action = 'overview'
view.request = drf_request

# Call overview method
print("Calling CasaViewSet.overview()...")
response = view.overview(drf_request)
data = response.data

print("\n--- API Overview Output ---")
print("Period:", data["period"])
print("Cashbox:", data["cashbox"])
print("Expenses:", data["expenses"])

# Perform basic asserts/checks
print("\nPerforming sanity checks...")
try:
    usd_rate = CurrencyRate.objects.get(currency='USD').rate_to_uzs
except CurrencyRate.DoesNotExist:
    usd_rate = 12800.0
driver_exp_uzs = data["expenses"]["driver_expenses_uzs"]
remaining_bal = data["cashbox"]["remaining_balance_uzs"]
total_in_uzs = data["cashbox"]["total_in_uzs"]
total_expenses_uzs = data["expenses"]["total_expenses_uzs"]

# Balance math check: remaining_balance_uzs should equal total_in_uzs - total_expenses_uzs
expected_balance = total_in_uzs - total_expenses_uzs
print(f"Total In UZS (reduced by driver expenses): {total_in_uzs}")
print(f"Total Expenses (including driver expenses): {total_expenses_uzs}")
print(f"Driver Expenses UZS: {driver_exp_uzs}")
print(f"Actual Remaining Balance: {remaining_bal}")
print(f"Expected Remaining Balance: {expected_balance}")

assert round(remaining_bal, 2) == round(expected_balance, 2), "Mismatch in balance calculation!"
print("[OK] Math verification successful!")

# Test restore_to_active behavior
print("\nChecking restore_to_active model code...")
trip = RaysHistoryMod.objects.first()
if trip:
    print(f"Found historical trip ID: {trip.id}")
    print(f"Original returned_advance: {trip.returned_advance}")
    
    # We will simulate the creation in database without calling delete, or check how restore_to_active works.
    # Since we modified the model file, let's look at the method definition in models.py via python inspect.
    import inspect
    restore_method = inspect.getsource(RaysHistoryMod.restore_to_active)
    print("\nMethod source:")
    print("\n".join(restore_method.split("\n")[:15]))
    assert "returned_advance=0" in restore_method, "returned_advance was not set to 0 in restore_to_active!"
    print("[OK] restore_to_active source check successful!")
else:
    print("No historical trip found to test, but code source check will be performed on definition.")
    import inspect
    restore_method = inspect.getsource(RaysHistoryMod.restore_to_active)
    assert "returned_advance=0" in restore_method, "returned_advance was not set to 0 in restore_to_active!"
    print("[OK] restore_to_active source check successful!")

print("\nAll verification checks passed successfully!")
