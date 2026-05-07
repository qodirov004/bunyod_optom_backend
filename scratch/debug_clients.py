
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'bunyod_optom_backend.settings')
django.setup()

from set_main.models import RaysMod

def check_rays(rays_id):
    r = RaysMod.objects.filter(id=rays_id).first()
    if not r:
        print(f"Rays #{rays_id} not found")
        return

    print(f"--- Rays #{rays_id} ---")
    print("Direct clients:", [c.company or f"{c.first_name} {c.last_name}" for c in r.client.all()])
    
    product_clients = []
    for p in r.product_set.all():
        if p.client:
            product_clients.append(p.client.company or f"{p.client.first_name} {p.client.last_name}")
    print("Product clients:", product_clients)

check_rays(4)
check_rays(5)
