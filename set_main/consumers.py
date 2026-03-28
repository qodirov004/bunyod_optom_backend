import json
from channels.generic.websocket import AsyncWebsocketConsumer
from django.db.models import Sum
from django.utils.timezone import now, timedelta

class ReferensConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        await self.channel_layer.group_add("referens_group", self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard("referens_group", self.channel_name)

    async def receive(self, text_data):
        # обычно клиенты ничего не отправляют
        pass

    async def send_referens_update(self, event):
        await self.send(text_data=json.dumps(event["data"]))


class ArizaConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        await self.channel_layer.group_add("ariza_group", self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard("ariza_group", self.channel_name)

    async def receive(self, text_data):
        pass

    async def send_ariza_update(self, event):
        await self.send(text_data=json.dumps(event["data"]))

class ProductConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        # Принять соединение
        await self.accept()
        # Добавить подключившегося клиента в группу "products"
        await self.channel_layer.group_add("products", self.channel_name)
        print(f"New WebSocket connection: {self.channel_name}")

    async def disconnect(self, close_code):
        # Удалить клиента из группы "products"
        await self.channel_layer.group_discard("products", self.channel_name)
        print(f"WebSocket disconnected: {self.channel_name}")

    async def receive(self, text_data):
        """
        Обработка сообщений, полученных от клиента.
        Здесь можно реализовать логику по запросу данных или командам.
        """
        data = json.loads(text_data)
        print("Received message from client:", data)
        # Например, можно отправить подтверждение обратно:
        await self.send(text_data=json.dumps({
            "message": "Сообщение получено",
            "data": data,
        }))

    async def product_update(self, event):
        """
        Метод вызывается, когда группа "products" получает событие с типом 'product_update'.
        """
        content = event.get("content", {})
        # Отправить обновление клиенту
        await self.send(text_data=json.dumps(content))