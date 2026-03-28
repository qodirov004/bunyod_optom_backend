from . import rest_api
from django.dispatch import receiver
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db.models.signals import post_save
from .models import (
    Product,RaysMod, Texnics, BalonMod, BalonFurgon, OptolMod,
    ChiqimlikMod, ArizaMod, ReferensMod
)

def update_rays_by_car(car):
    if not car:
        return
    rays_qs = RaysMod.objects.filter(car=car, is_completed=False)
    for rays in rays_qs:
        rays.update_prices_from_products_and_expenses()

def update_rays_by_furgon(furgon):
    if not furgon:
        return
    rays_qs = RaysMod.objects.filter(fourgon=furgon, is_completed=False)
    for rays in rays_qs:
        rays.update_prices_from_products_and_expenses()

def update_rays_by_driver(driver):
    if not driver:
        return
    rays_qs = RaysMod.objects.filter(driver=driver, is_completed=False)
    for rays in rays_qs:
        rays.update_prices_from_products_and_expenses()

# 🚗 Расходы, связанные с машиной
@receiver(post_save, sender=Texnics)
@receiver(post_save, sender=BalonMod)
@receiver(post_save, sender=OptolMod)
def handle_car_expenses(sender, instance, **kwargs):
    update_rays_by_car(instance.car)

# 🚛 Расходы, связанные с фургоном
@receiver(post_save, sender=BalonFurgon)
def handle_furgon_expenses(sender, instance, **kwargs):
    update_rays_by_furgon(instance.furgon)

# 👨‍✈️ Расходы, связанные с водителем
@receiver(post_save, sender=ChiqimlikMod)
@receiver(post_save, sender=ArizaMod)
@receiver(post_save, sender=ReferensMod)
def handle_driver_expenses(sender, instance, **kwargs):
    update_rays_by_driver(instance.driver)

@receiver(post_save, sender=Product)
def update_rays_price_on_product_save(sender, instance, created, **kwargs):
    if instance.client:
        rays = RaysMod.objects.filter(client=instance.client, is_completed=False)
        for ray in rays:
            ray.update_prices_from_products_and_expenses() 

@receiver(post_save, sender=ReferensMod)
def referens_updated(sender, instance, created, **kwargs):
    channel_layer = get_channel_layer()
    data = rest_api.ReferensSerializer(instance).data
    async_to_sync(channel_layer.group_send)(
        "referens_group",
        {
            "type": "send_referens_update",
            "data": {
                "action": "created" if created else "updated",
                "referens": data
            }
        }
    )

@receiver(post_save, sender=ArizaMod)
def ariza_updated(sender, instance, created, **kwargs):
    channel_layer = get_channel_layer()
    data = rest_api.ArizaSerializer(instance).data
    async_to_sync(channel_layer.group_send)(
        "ariza_group",
        {
            "type": "send_ariza_update",
            "data": {
                "action": "created" if created else "updated",
                "ariza": data
            }
        }
    )

# @receiver(post_save, sender=RaysMod)
# def move_to_history(sender, instance, **kwargs):
#     if instance.is_completed:
#         instance.complete_race()

@receiver(post_save, sender=Product)
def product_post_save(sender, instance, created, **kwargs):
    """
    При сохранении модели Product отправляем обновление всем, кто подписан на группу "products".
    """
    channel_layer = get_channel_layer()
    data = {
        "id": instance.id,
        "name": instance.name,
        "price": instance.price,
        "count": instance.count,
        "description": instance.description,
    }
    async_to_sync(channel_layer.group_send)(
        "products",
        {
            "type": "product_update",  # вызовет метод product_update в consumer'е
            "content": data,
        }
    )
