import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'bunyod_optom_backend.settings')
django.setup()

from set_main.models import CashTransactionMod, CashTransactionHistory

def cleanup():
    # Delete transactions with no rays and no rays_history
    active = CashTransactionMod.objects.filter(rays__isnull=True, rays_history__isnull=True)
    active_count = active.count()
    active.delete()
    
    history = CashTransactionHistory.objects.filter(rays__isnull=True, rays_history_id__isnull=True)
    history_count = history.count()
    history.delete()
    
    print(f"O'chirildi (Aktiv): {active_count}")
    print(f"O'chirildi (Tarix): {history_count}")

if __name__ == "__main__":
    cleanup()
