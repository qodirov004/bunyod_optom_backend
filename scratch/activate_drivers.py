import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'bunyod_optom_backend.settings')
django.setup()

from set_main.models import CustomUser

# Barcha haydovchilarni faollashtiramiz
updated = CustomUser.objects.filter(status='driver').update(is_active=True)
print(f"Muvaffaqiyatli: {updated} ta haydovchi faollashtirildi.")
