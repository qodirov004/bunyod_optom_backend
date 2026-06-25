import os
import sys
import django

# Add project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'set_app.settings')
django.setup()

from set_main.models import CashTransactionHistory, RaysHistoryMod, CashTransactionMod

print("=== CHECKING TRANSACTIONS ===")
total_history = CashTransactionHistory.objects.count()
history_no_rays_history = CashTransactionHistory.objects.filter(rays_history__isnull=True).count()
print(f"Total transactions in CashTransactionHistory: {total_history}")
print(f"Transactions in CashTransactionHistory with rays_history=NULL: {history_no_rays_history}")

# Print a few samples of those with NULL rays_history
if history_no_rays_history > 0:
    print("\nSamples of transactions with rays_history=NULL:")
    for tx in CashTransactionHistory.objects.filter(rays_history__isnull=True)[:10]:
        print(f"ID: {tx.id}, Client: {tx.client}, Rays: {tx.rays}, Amount: {tx.amount}, Status: {tx.status}")

print("\nTotal transactions in CashTransactionMod:")
total_mod = CashTransactionMod.objects.count()
confirmed_mod = CashTransactionMod.objects.filter(status='confirmed').count()
print(f"Total: {total_mod}, Confirmed in Mod: {confirmed_mod}")

if confirmed_mod > 0:
    print("\nSamples of confirmed transactions in CashTransactionMod:")
    for tx in CashTransactionMod.objects.filter(status='confirmed')[:10]:
        print(f"ID: {tx.id}, Client: {tx.client}, Rays: {tx.rays}, Amount: {tx.amount}, Status: {tx.status}")
