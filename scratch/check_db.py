import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "set_app.settings")
django.setup()

from set_main.models import Texnics, RaysMod

tex = Texnics.objects.all()[:5]
print("Texnics:")
for t in tex:
    curr = t.currency.currency if t.currency else 'None'
    print(f"ID: {t.id}, Price: {t.price}, Currency: {curr}")

rays = RaysMod.objects.all()[:5]
print("\nRaysMod:")
for r in rays:
    print(f"ID: {r.id}, Price: {r.price}, DR: {r.dr_price}, DP: {r.dp_price}")
