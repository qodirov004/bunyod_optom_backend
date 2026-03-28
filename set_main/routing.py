from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    re_path(r'ws/referens/$', consumers.ReferensConsumer.as_asgi()),
    re_path(r'ws/ariza/$', consumers.ArizaConsumer.as_asgi()),
    re_path(r'ws/products/$', consumers.ProductConsumer.as_asgi()),
]