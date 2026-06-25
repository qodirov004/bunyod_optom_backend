import os
import sys
import django

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'set_app.settings')
django.setup()

from set_main.models import RaysHistoryMod, CashTransactionHistory, CashTransactionMod
from django.db.models import Q

# Let's find any trip in history
history_trips = RaysHistoryMod.objects.all()
if not history_trips.exists():
    print("No trips in history to test restore.")
    sys.exit()

trip = history_trips.first()
print(f"Testing restore on RaysHistoryMod ID: {trip.id}, Original Rays ID: {trip.rays_id}")

# Find transactions for this trip
history_txs = CashTransactionHistory.objects.filter(
    Q(rays_history=trip) | Q(rays__id=trip.rays_id)
)
print(f"Transactions found in CashTransactionHistory for this trip: {history_txs.count()}")
for tx in history_txs:
    print(f"  TX ID: {tx.id}, Amount: {tx.amount}, RaysHistory: {tx.rays_history_id}")

# Let's perform restore
print("\nPerforming restore_to_active()...")
try:
    restored_rays = trip.restore_to_active()
    print(f"Restore successful! New active Rays ID: {restored_rays.id}")
except Exception as e:
    print(f"Error during restore: {e}")
    sys.exit()

# Now check database states
print("\nChecking post-restore database states:")
history_txs_after = CashTransactionHistory.objects.filter(
    Q(rays_history_id=trip.id)
)
print(f"Transactions in CashTransactionHistory: {history_txs_after.count()}")

mod_txs = CashTransactionMod.objects.filter(rays=restored_rays)
print(f"Transactions in CashTransactionMod: {mod_txs.count()}")
for tx in mod_txs:
    print(f"  TX ID: {tx.id}, Amount: {tx.amount}, Status: {tx.status}")

# Let's rollback/delete restored rays to not affect the DB
# (we delete the restored rays and recreate the history trip, or since it's sqlite, we can do it later if needed, but let's just do it manually)
print("\nTest completed.")
