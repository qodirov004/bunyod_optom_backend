import os
import django
import sys

# Добавляем путь к проекту в sys.path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'set_app.settings')
django.setup()

from set_main.models import RaysMod, CustomUser, CarsMod, FurgonMod

active_drivers = RaysMod.objects.exclude(driver__isnull=True).values_list('driver_id', flat=True)
active_cars = RaysMod.objects.exclude(car__isnull=True).values_list('car_id', flat=True)
active_fourgons = RaysMod.objects.exclude(fourgon__isnull=True).values_list('fourgon_id', flat=True)

stuck_drivers = CustomUser.objects.filter(is_busy=True).exclude(id__in=active_drivers)
stuck_cars = CarsMod.objects.filter(is_busy=True).exclude(id__in=active_cars)
stuck_fourgons = FurgonMod.objects.filter(is_busy=True).exclude(id__in=active_fourgons)

print(f"Fixing {stuck_drivers.count()} drivers")
stuck_drivers.update(is_busy=False)

print(f"Fixing {stuck_cars.count()} cars")
stuck_cars.update(is_busy=False)

print(f"Fixing {stuck_fourgons.count()} fourgons")
stuck_fourgons.update(is_busy=False)

print("Done")
