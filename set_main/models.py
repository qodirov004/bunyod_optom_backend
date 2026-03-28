from decimal import Decimal, InvalidOperation
from django.db import models
from datetime import timedelta
from django.db.models import Q,Sum
from django.dispatch import receiver
from django.utils.timezone import now
from django.db.models.signals import post_save
from rest_framework.exceptions import ValidationError
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin

def get_default_currency():
    from .models import CurrencyRate
    return CurrencyRate.objects.get_or_create(
        currency='UZS',
        defaults={'rate_to_uzs': 1}
    )[0].id

TYPE_BALON = [
    ('standart','Standart'),
    ('qishki','Qishki'),
    ('yozgi','Yozgi'),
    ('universal','Universal')
]

HOLAT_CHOICES = [
    ('foal', 'Foal'),
    ('tamirda', 'Ta\'mirda'),
    ('kutmokda', 'Kutmokda'),
]

FURGON_STATUS = [
    ('foal','Foal'),
    ('kutmokda','Kutmokda'),
]

STATUS_CHOICES = [
    ('driver', 'Driver'),
    ('owner', 'Owner'),
    ('ceo', 'CEO'),
    ('cashier', 'Cashier'),
    ('bugalter', 'Bugalter'),
    ('zaphos', 'Zaphos'),
]

class CurrencyRate(models.Model):
    CURRENCY_CHOICES = [
        ('USD', '🇺🇸 Доллар (USD)'),
        ('RUB', '🇷🇺 Рубль (RUB)'),
        ('EUR', '🇪🇺 Евро (EUR)'),
        ('UZS', '🇺🇿 Uzs (UZS)'),
    ]
    
    currency = models.CharField(max_length=3, choices=CURRENCY_CHOICES, unique=True, verbose_name="Валюта")
    rate_to_uzs = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="Курс к UZS")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Дата обновления")

    class Meta:
        verbose_name = "Курс валюты"
        verbose_name_plural = "Курсы валют"

    def __str__(self):
        return f"{self.currency} → {self.rate_to_uzs} UZS"

class DriverSalary(models.Model):
    driver = models.ForeignKey('CustomUser', on_delete=models.CASCADE)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.ForeignKey(CurrencyRate, on_delete=models.SET_NULL, null=True,default=get_default_currency)
    paid_at = models.DateTimeField(auto_now_add=True)

class CountryMod(models.Model):
    name = models.CharField(max_length=255, verbose_name="Название страны")

    def __str__(self):
        return self.name

class RaysHistoryProduct(models.Model):
    name = models.CharField(max_length=255)
    price = models.BigIntegerField()
    count = models.PositiveBigIntegerField()
    client = models.ForeignKey('ClientsMod', on_delete=models.SET_NULL, null=True)
    rays_history = models.ForeignKey('RaysHistoryMod', on_delete=models.CASCADE)
    from_location = models.CharField(max_length=255, verbose_name="Откуда", blank=True, null=True)
    to_location = models.CharField(max_length=255, verbose_name="Куда", blank=True, null=True)

class RaysHistoryExpense(models.Model):
    name = models.CharField(max_length=255)
    price = models.BigIntegerField()
    description = models.TextField()
    driver = models.ForeignKey('CustomUser', on_delete=models.SET_NULL, null=True)
    rays_history = models.ForeignKey('RaysHistoryMod', on_delete=models.CASCADE)

class RaysHistoryMod(models.Model):
    rays_id = models.PositiveBigIntegerField(blank=True,null=True)
    driver = models.ForeignKey('CustomUser', on_delete=models.SET_NULL, null=True, blank=True)
    car = models.ForeignKey('CarsMod', on_delete=models.SET_NULL, null=True, blank=True)
    fourgon = models.ForeignKey('FurgonMod', on_delete=models.SET_NULL, null=True, blank=True)
    client = models.ManyToManyField('ClientsMod', blank=True, related_name='rays_history_clients')
    price = models.BigIntegerField(default=0)
    dr_price = models.BigIntegerField(default=0)
    dp_price = models.BigIntegerField(default=0)
    dp_currency = models.ForeignKey(CurrencyRate, on_delete=models.SET_NULL, null=True,default=get_default_currency)
    dp_information = models.TextField(blank=True, null=True)
    country = models.ForeignKey('CountryMod', on_delete=models.SET_NULL, null=True, blank=True)
    kilometer = models.IntegerField(default=0)
    count = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    def __str__(self):
        return f"История рейса #{self.id}"
    def can_restore(self):
        """Можно ли восстановить обратно в Rays (не прошло ли 2 дней)."""
        return now() - self.created_at <= timedelta(days=2)
    def restore_to_active(self):
        if not self.can_restore():
            raise Exception("❌ Восстановление невозможно — прошло более 2 дней.")

        rays = RaysMod.objects.create(
            country=self.country,
            driver=self.driver,
            car=self.car,
            fourgon=self.fourgon,
            price=self.price,
            dr_price=self.dr_price,
            dp_price=self.dp_price,
            kilometer=self.kilometer,
            dp_information=self.dp_information,
            count=self.count,
            is_completed=False,
        )
        rays.client.set(self.client.all())

        # ✅ обновляем продукты: переносим с rays_history на новый rays
        for client in self.client.all():
            products = Product.objects.filter(client=client, rays_history=self)
            for product in products:
                product.rays = rays
                product.rays_history = None
                product.save()

        # ✅ обновляем транзакции
        CashTransactionHistory.objects.filter(rays__id=self.id).update(rays=rays)

        self.delete()
        return rays


def archive_product(product):
    product.is_delivered = True
    product.save()

def client_fully_paid_or_in_debt(client,rays):
    products = Product.objects.filter(client=client, rays=rays, is_delivered=False)
    total_product_price = products.aggregate(total=Sum('price'))['total'] or 0
    transactions_mod = CashTransactionMod.objects.filter(
        client=client,
        status='confirmed'
    ).filter(
        Q(rays=rays) | Q(product__in=products)
    ).distinct()
    transactions_history = CashTransactionHistory.objects.filter(
        client=client,
        status='confirmed'
    ).filter(
        Q(rays=rays) | Q(product__in=products)
    ).distinct()
    # Суммируем оплаты
    total_paid_mod = transactions_mod.aggregate(total=Sum('amount'))['total'] or 0
    total_paid_history = transactions_history.aggregate(total=Sum('amount'))['total'] or 0

    total_paid = total_paid_mod + total_paid_history

    if total_paid >= total_product_price:
        return True  # всё оплачено

    # Проверяем есть ли долг по этим транзакциям
    has_debt = transactions_history.filter(is_debt=True).exists()
    return has_debt

class RaysMod(models.Model):
    driver = models.ForeignKey('CustomUser', on_delete=models.SET_NULL, null=True, blank=True)
    car = models.ForeignKey('CarsMod', on_delete=models.SET_NULL, null=True, blank=True)
    fourgon = models.ForeignKey('FurgonMod', on_delete=models.SET_NULL, null=True, blank=True)
    client = models.ManyToManyField('ClientsMod', blank=True, related_name='rays_clients')
    client_completed = models.ManyToManyField('ClientsMod', blank=True, related_name='completed_clients')
    price = models.BigIntegerField(default=0)
    dr_price = models.BigIntegerField(default=0)
    dp_price = models.BigIntegerField(default=0)
    dp_currency = models.ForeignKey('CurrencyRate', on_delete=models.SET_NULL, null=True, blank=True,default=get_default_currency)
    dp_information = models.TextField(blank=True, null=True)
    country = models.ForeignKey('CountryMod', on_delete=models.SET_NULL, null=True, blank=True)
    kilometer = models.IntegerField(default=0)
    count = models.IntegerField(default=0)
    is_completed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def update_prices_from_products_and_expenses(self):
        from .models import (
            Product, ChiqimlikMod, BalonMod, BalonFurgon, Texnics,
            OptolMod, CurrencyRate
        )
        from .views import to_usd

        # Продукты
        total_usd_products = 0
        for client in self.client.all():
            products = Product.objects.filter(client=client, rays=self, is_delivered=False)
            for product in products:
                total_usd_products += to_usd(product.price, product.currency)
        self.price = round(total_usd_products)

        # Все типы расходов
        start_time = self.created_at
        total_usd_expenses = 0

        # Валюты
        rates = {r.currency: float(r.rate_to_uzs) for r in CurrencyRate.objects.all()}
        usd_rate = rates.get('USD', 1) or 1

        def local_to_usd(amount, currency):
            if currency == 'USD':
                return float(amount)
            elif currency == 'UZS':
                return float(amount) / usd_rate
            elif currency in rates:
                return (float(amount) * rates[currency]) / usd_rate
            return 0

        def sum_expenses(queryset):
            return sum(local_to_usd(item.price, getattr(item, 'currency', 'USD')) for item in queryset)

        # Расчёт всех расходов (важно фильтровать по водителю, машине, фургону, времени)
        total_usd_expenses += sum_expenses(Texnics.objects.filter(car=self.car, created_at__gte=start_time))
        total_usd_expenses += sum_expenses(BalonMod.objects.filter(car=self.car, created_at__gte=start_time))
        total_usd_expenses += sum_expenses(BalonFurgon.objects.filter(furgon=self.fourgon, created_at__gte=start_time))
        total_usd_expenses += sum_expenses(OptolMod.objects.filter(car=self.car, created_at__gte=start_time))
        total_usd_expenses += sum_expenses(ChiqimlikMod.objects.filter(driver=self.driver, created_at__gte=start_time))

        self.dr_price = round(total_usd_expenses)
        self.save()
    
    def archive_all_transactions(self,client, rays_history):
        all_tx = CashTransactionMod.objects.filter(client=client).filter(Q(rays=self) | Q(product__rays=self)).distinct()
        for tx in all_tx:
            create_history_from_transaction(tx, rays_history=rays_history)
            tx.delete()
    def __str__(self):
        return f"Rays #{self.id} - {self.driver} - {self.country}"
    def complete_whole_race(self):
        remaining_clients = self.client.exclude(id__in=self.client_completed.values_list('id', flat=True))

        for client in remaining_clients:
            if not client_fully_paid_or_in_debt(client, self):
                raise ValidationError(f"Клиент {client.first_name} не оплатил или не оформил долг.")

        history = RaysHistoryMod.objects.create(
            rays_id=self.id,
            country=self.country,
            driver=self.driver,
            car=self.car,
            fourgon=self.fourgon,
            price=self.price,
            dr_price=self.dr_price,
            dp_price=self.dp_price,
            dp_information=self.dp_information,
            kilometer=self.kilometer,
            count=self.count
        )
        history.client.set(self.client.all())

        for client in self.client.all():
            products = Product.objects.filter(client=client, rays=self, is_delivered=False)
            for product in products:
                RaysHistoryProduct.objects.create(
                    name=product.name,
                    price=product.price,
                    count=product.count,
                    client=client,
                    rays_history=history,
                    from_location=product.from_location,
                    to_location=product.to_location
                )

                # 🟢 ДОБАВЛЯЕМ обновление ссылок:
                product.rays_history = history
                product.rays = None
                archive_product(product)  # вызовет product.is_delivered = True и сохранит

            self.archive_all_transactions(client, rays_history=history)

            client.save()

        CashTransactionHistory.objects.filter(rays=self).update(rays_history=history)

        expenses = ChiqimlikMod.objects.filter(driver=self.driver, created_at__gte=self.created_at)
        for expense in expenses:
            RaysHistoryExpense.objects.create(
                name=(expense.chiqimlar.name if expense.chiqimlar else 'Без категории'),
                price=expense.price,
                description=expense.description,
                driver=self.driver,
                rays_history=history
            )

        if self.car:
            self.car.is_busy = False
            self.car.save()
        if self.fourgon:
            self.fourgon.is_busy = False
            self.fourgon.save()
        if self.driver:
            self.driver.is_busy = False
            self.driver.save()

        self.delete()
        return history

    def complete_race(self):
        """
        Завершает весь рейс сразу, если все клиенты оплатили или оформили долг.
        """
        return self.complete_whole_race()

class CustomUserManager(BaseUserManager):
    def create_user(self, username, password=None, **extra_fields):
        if not username:
            raise ValueError('Пользователь должен иметь username')
        user = self.model(username=username, **extra_fields)
        user.set_password(password)  # Обязательно хешируем
        user.is_active = True  # Включаем пользователя
        user.save(using=self._db)
        return user

    def create_superuser(self, username, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        return self.create_user(username, password, **extra_fields)

class CustomUser(AbstractBaseUser, PermissionsMixin):
    username = models.CharField(max_length=150, unique=True)
    fullname = models.CharField(max_length=255)
    phone_number = models.CharField(max_length=20, blank=True, null=True)
    status = models.CharField(max_length=50, choices=STATUS_CHOICES, default='driver')
    photo = models.ImageField(upload_to='user_photos/', blank=True, null=True, default='defaults/furgon_default.avif')

    passport_series = models.CharField(max_length=4, blank=True, null=True)
    passport_number = models.CharField(max_length=6, blank=True, null=True)
    passport_issued_by = models.CharField(max_length=255, blank=True, null=True)
    passport_issued_date = models.DateField(blank=True, null=True)
    passport_birth_date = models.DateField(blank=True, null=True)
    passport_photo = models.ImageField(upload_to='passport_photos/', blank=True, null=True, default='defaults/furgon_default.avif')
    is_busy = models.BooleanField(default=False)

    date = models.DateTimeField(auto_now_add=True)
    is_staff = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    USERNAME_FIELD = 'username'
    REQUIRED_FIELDS = ['fullname', 'phone_number', 'status']

    objects = CustomUserManager()
    
    def __str__(self):
        return self.username
    
    class Meta:
        verbose_name = 'Пользователь'
        verbose_name_plural = 'Пользователи'
        #сортировка по дате создания
        ordering = ['-date']

class ClientsMod(models.Model):
    first_name = models.CharField(max_length=255, verbose_name="Имя")
    last_name = models.CharField(max_length=255, verbose_name="Фамилия")
    city = models.CharField(max_length=255, verbose_name="Город")
    number = models.CharField(max_length=20, verbose_name="Номер телефона")
    company = models.CharField(max_length=100,verbose_name='Firma')
    
    def __str__(self):
        return self.first_name

class ChiqimlarCategory(models.Model):
    name = models.CharField(max_length=255, verbose_name="Название категории")

    def __str__(self):
        return self.name

class ChiqimlikMod(models.Model):
    driver = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True,verbose_name="Пользователь")
    chiqimlar = models.ForeignKey(ChiqimlarCategory, on_delete=models.SET_NULL,null=True, verbose_name="Категория расходов")
    photo = models.ImageField(upload_to='chiqimlik_photos/', verbose_name="Фото",blank=True,default='defaults/furgon_default.avif')
    price = models.BigIntegerField(verbose_name="Цена")
    currency = models.ForeignKey(CurrencyRate, on_delete=models.SET_NULL, null=True, verbose_name="Валюта",default=get_default_currency)
    description = models.TextField(verbose_name="Описание")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата создания")

    def __str__(self):
        return f"{self.chiqimlar.name} - {self.price}"

# this is for ariza number 2
class ReferensMod(models.Model):
    driver = models.ForeignKey(CustomUser, on_delete=models.SET_NULL,null=True, verbose_name="Пользователь")
    description = models.TextField(verbose_name="Описание")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата создания")

    def __str__(self):
        return f"Ариза от {self.driver.username}"

class ArizaMod(models.Model):
    driver = models.ForeignKey(CustomUser, on_delete=models.SET_NULL,null=True, verbose_name="Пользователь")
    description = models.TextField(verbose_name="Описание")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата создания")

    def __str__(self):
        return f"Ариза от {self.driver.username}"

class CarsMod(models.Model):
    name = models.CharField(max_length=255, verbose_name="Название модели")
    number = models.CharField(max_length=255, verbose_name="Номер модели")
    year = models.CharField(max_length=255, verbose_name="Год выпуска")
    engine = models.CharField(max_length=255, verbose_name="Двигатель")
    transmission = models.CharField(max_length=255, verbose_name="Трансмиссия")
    power = models.CharField(max_length=255, verbose_name="Количество кВт")
    capacity = models.CharField(max_length=255, verbose_name="Грузоподъемность")
    fuel = models.CharField(max_length=255, verbose_name="Топливо")
    mileage = models.CharField(max_length=255, verbose_name="Пробег")
    holat = models.CharField(max_length=225, choices=HOLAT_CHOICES, default='kutmokda', verbose_name="Холат")
    car_number = models.CharField(max_length=255, verbose_name="Номер автомобиля")
    kilometer = models.PositiveBigIntegerField(verbose_name="Пробег")
    photo = models.ImageField(upload_to='cars_photos/', verbose_name="Фото модели",blank=True,default='defaults/furgon_default.avif') 
    is_busy = models.BooleanField(default=False, verbose_name="Занят?")

    def __str__(self):
        return self.name

class FurgonMod(models.Model):
    name = models.CharField(max_length=255, verbose_name="Название модели")
    number = models.CharField(max_length=255, verbose_name="Номер фургона")
    photo = models.ImageField(upload_to='furgon_photos/', verbose_name="Фото модели",default='defaults/furgon_default.avif')
    kilometer = models.PositiveBigIntegerField(verbose_name="Пробег")
    status = models.CharField(max_length=255, choices=FURGON_STATUS, default='new', verbose_name="Статус модели")
    description = models.TextField(null=True, blank=True, verbose_name="Описание модели")
    is_busy = models.BooleanField(default=False, verbose_name="Занята?")

    def __str__(self):
        return self.name

class FromLocation(models.Model):
    name = models.CharField(max_length=255, verbose_name="Название города")

    def __str__(self):
        return self.name

class ToLocation(models.Model):
    name = models.CharField(max_length=255, verbose_name="Название города")

    def __str__(self):
        return self.name

class Product(models.Model):
    rays = models.ForeignKey(RaysMod, null=True, blank=True, on_delete=models.SET_NULL)
    rays_history = models.ForeignKey(RaysHistoryMod, null=True, blank=True, on_delete=models.SET_NULL)
    name = models.CharField(max_length=255, verbose_name="Название товара")
    client = models.ForeignKey('ClientsMod', on_delete=models.CASCADE, null=True, blank=True, verbose_name="Клиент")
    price = models.BigIntegerField(verbose_name="Цена")
    price_in_usd = models.DecimalField(max_digits=15, decimal_places=2, default=0) 
    currency = models.ForeignKey(CurrencyRate, on_delete=models.SET_NULL, null=True, verbose_name="Валюта",default=get_default_currency)
    count = models.PositiveBigIntegerField(verbose_name="Количество")
    description = models.TextField(blank=True, verbose_name="Описание товара")
    photo = models.ImageField(upload_to='product_photos/', verbose_name="Фото товара", default='defaults/furgon_default.avif')
    is_busy = models.BooleanField(default=False, verbose_name="Занят?")
    from_location = models.ForeignKey(FromLocation, on_delete=models.SET_NULL, null=True, verbose_name="Откуда")
    to_location = models.ForeignKey(ToLocation, on_delete=models.SET_NULL, null=True, verbose_name="Куда")
    is_delivered = models.BooleanField(default=False, verbose_name="Доставлен?")  # Новое поле

    def save(self, *args, **kwargs):
        # Если не задана валюта — просто сохраняем
        if not self.currency:
            super().save(*args, **kwargs)
            return

        try:
            # Получаем объект USD и наш текущий курс
            usd_obj = CurrencyRate.objects.get(currency='USD')
            current_rate = self.currency.rate_to_uzs

            # Конвертируем в Decimal
            price_dec = Decimal(self.price)
            rate_dec  = Decimal(current_rate)
            usd_rate_dec = Decimal(usd_obj.rate_to_uzs)

            if self.currency.currency == 'USD':
                # Если валюта уже USD — оставляем цену без изменений
                self.price_in_usd = price_dec
            else:
                # Иначе делим: цена * курс_валюты / курс_USD
                self.price_in_usd = (price_dec * rate_dec) / usd_rate_dec

            # Округление до копеек
            self.price_in_usd = self.price_in_usd.quantize(Decimal('0.01'))

        except (CurrencyRate.DoesNotExist, InvalidOperation):
            # В случае проблем с курсами — обнуляем
            self.price_in_usd = Decimal('0.00')

        super().save(*args, **kwargs)

    def __str__(self):
        return self.name

class OptolMod(models.Model):
    car = models.ForeignKey(CarsMod, on_delete=models.SET_NULL,null=True)
    price = models.BigIntegerField(verbose_name="Цена")
    currency = models.ForeignKey(CurrencyRate, on_delete=models.SET_NULL, null=True, verbose_name="Валюта",default=get_default_currency)
    kilometr = models.PositiveBigIntegerField(verbose_name="Пробег",blank=True,null=True)
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата создания",blank=True)

    def __str__(self):
        return self.car.name

class BalonFurgon(models.Model):
    type = models.CharField(max_length=100,choices=TYPE_BALON, verbose_name="Тип балона")
    furgon = models.ForeignKey(FurgonMod, on_delete=models.SET_NULL,null=True)
    price = models.BigIntegerField(verbose_name="Цена")
    currency = models.ForeignKey(CurrencyRate, on_delete=models.SET_NULL, null=True, verbose_name="Валюта",default=get_default_currency)
    kilometr = models.PositiveBigIntegerField(verbose_name="Пробег",blank=True,null=True)
    count = models.PositiveBigIntegerField(verbose_name="Количество")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата создания")

    def __str__(self):
        return self.type

class BalonMod(models.Model):
    type = models.CharField(max_length=100,choices=TYPE_BALON, verbose_name="Тип балона")
    car = models.ForeignKey(CarsMod, on_delete=models.SET_NULL,null=True)
    price = models.BigIntegerField(verbose_name="Цена")
    currency = models.ForeignKey(CurrencyRate, on_delete=models.SET_NULL, null=True, verbose_name="Валюта",default=get_default_currency)
    kilometr = models.PositiveBigIntegerField(verbose_name="Пробег",blank=True,null=True)
    count = models.PositiveBigIntegerField(verbose_name="Количество")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата создания")

    def __str__(self):
        return self.type

class Service(models.Model):    
    name = models.CharField(max_length=255, verbose_name="Название услуги")

    def __str__(self):
        return self.name

class Texnics(models.Model):
    car = models.ForeignKey(CarsMod, on_delete=models.SET_NULL,null=True, verbose_name="Машина")
    service = models.ForeignKey(Service, on_delete=models.CASCADE,null=True, verbose_name="Service")
    price = models.BigIntegerField(verbose_name="Цена")
    currency = models.ForeignKey(CurrencyRate, on_delete=models.SET_NULL, null=True, verbose_name="Валюта",default=get_default_currency)
    kilometer = models.PositiveBigIntegerField(verbose_name="Пробег",blank=True,null=True)
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата создания")

    def __str__(self):
        return self.car
 
PAYMENT_WAY_CHOICES = [
    ('via_driver', 'Передаст водителю'),
    ('card', 'Переведет на карту'),
    ('advance', 'Оплатил заранее'),
    ('debt', 'В долг')
]

class CashCategory(models.Model):
    name = models.CharField(max_length=200)

    def __str__(self):
        return self.name

def create_history_from_transaction(tx, rays_history=None):
    return CashTransactionHistory.objects.create(
        client=tx.client,
        rays=tx.rays,
        rays_history=rays_history,  # <-- добавь это
        product=tx.product,
        driver=tx.driver,
        amount=tx.amount,
        amount_in_usd=tx.amount_in_usd,
        currency=tx.currency,
        status='confirmed',
        payment_way=tx.payment_way,
        is_confirmed_by_cashier=True,
        cashier=tx.cashier,
        comment=tx.comment,
        is_debt=tx.is_debt,
        is_via_driver=tx.is_via_driver,
        is_delivered_to_cashier=tx.is_delivered_to_cashier,
        total_expected_amount=tx.total_expected_amount,
        paid_amount=tx.paid_amount,
        remaining_debt=tx.remaining_debt,
        created_at=tx.created_at
    )

class CashTransactionMod(models.Model):
    PAYMENT_STATUS_CHOICES = [
        ('pending', 'Ожидает подтверждения'),  # Транзакция создана, но ещё не подтверждена кассиром
        ('confirmed', 'Подтверждено'),        # Транзакция подтверждена кассиром
        ('cancelled', 'Отменено'),            # Транзакция отменена
    ]
    client = models.ForeignKey('ClientsMod', on_delete=models.CASCADE)  
    # Клиент, совершающий оплату
    rays = models.ForeignKey('RaysMod', on_delete=models.CASCADE, null=True, blank=True)
    # Рейс, к которому относится транзакция (может быть пустым, если оплата заранее)
    product = models.ForeignKey('Product', on_delete=models.SET_NULL, null=True, blank=True)
    # Продукт, за который производится оплата
    driver = models.ForeignKey(
        'CustomUser',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        limit_choices_to={'status': 'driver'}
    )
    # Водитель, через которого передаются деньги (если оплата через водителя)
    amount = models.BigIntegerField()
    # Сумма, которую платит клиент в этой транзакции
    amount_in_usd = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    currency = models.ForeignKey(CurrencyRate, on_delete=models.SET_NULL, null=True, verbose_name="Валюта",default=get_default_currency)
    status = models.CharField(max_length=20, choices=PAYMENT_STATUS_CHOICES, default='pending')
    # Статус транзакции
    payment_way = models.ForeignKey('CashCategory', on_delete=models.SET_NULL, null=True)
    # Способ оплаты (например, наличные, через водителя, карта и т.п.)
    is_confirmed_by_cashier = models.BooleanField(default=False)
    # Подтвердил ли кассир эту транзакцию
    cashier = models.ForeignKey(
        'CustomUser',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='cashier_operations',
        limit_choices_to={'status': 'cashier'}
    )
    # Кассир, подтвердивший транзакцию
    comment = models.TextField(blank=True, null=True)
    # Дополнительный комментарий
    is_debt = models.BooleanField(default=False, verbose_name="Клиент взял в долг")
    # Указывает, взял ли клиент в долг
    is_via_driver = models.BooleanField(default=False)
    # Указывает, передаются ли деньги через водителя
    is_delivered_to_cashier = models.BooleanField(default=False)
    # Указывает, доставил ли водитель деньги кассиру
    total_expected_amount = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    # Сколько клиент должен заплатить за весь товар
    paid_amount = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    # Сколько клиент уже заплатил за этот товар
    remaining_debt = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    # Сколько осталось заплатить (total_expected_amount - paid_amount)
    created_at = models.DateTimeField(auto_now_add=True)
    # Дата и время создания транзакции
    class Meta:
        indexes = [
            models.Index(fields=['driver', 'is_confirmed_by_cashier']),
        ]
    def save(self, *args, **kwargs):
        # Автоматически считаем оставшийся долг, если есть нужные данные
        if self.total_expected_amount is not None and self.paid_amount is not None:
            self.remaining_debt = self.total_expected_amount - self.paid_amount
        super().save(*args, **kwargs)
    def is_payment_via_driver(self):
        return self.payment_way and self.payment_way.name.lower() == 'через водителя'

class CashTransactionHistory(models.Model):
    client = models.ForeignKey('ClientsMod', on_delete=models.CASCADE)
    rays = models.ForeignKey('RaysMod', on_delete=models.SET_NULL, null=True, blank=True)
    rays_history = models.ForeignKey('RaysHistoryMod', on_delete=models.SET_NULL, null=True, blank=True)
    product = models.ForeignKey('Product', on_delete=models.SET_NULL, null=True, blank=True)
    driver = models.ForeignKey('CustomUser', on_delete=models.SET_NULL, null=True, blank=True,related_name='cash_transactions_as_driver')
    amount = models.BigIntegerField()
    amount_in_usd = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    currency = models.ForeignKey(CurrencyRate, on_delete=models.SET_NULL, null=True, verbose_name="Валюта",default=get_default_currency)
    status = models.CharField(max_length=20)
    payment_way = models.ForeignKey('CashCategory', on_delete=models.SET_NULL, null=True)
    cashier = models.ForeignKey('CustomUser', on_delete=models.SET_NULL, null=True, blank=True,related_name='cash_transactions_as_cashier')
    comment = models.TextField(blank=True, null=True)
    is_via_driver = models.BooleanField(default=False)
    is_confirmed_by_cashier = models.BooleanField(default=False)# Подтвердил ли кассир эту транзакцию
    is_delivered_to_cashier = models.BooleanField(default=False)
    total_expected_amount = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    paid_amount = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    remaining_debt = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    is_debt = models.BooleanField(default=False, verbose_name="Клиент взял в долг")
    created_at = models.DateTimeField()
    moved_at = models.DateTimeField(auto_now_add=True)
    # moved_at — когда была перенесена в историюllkjh;lkm,