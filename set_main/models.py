from decimal import Decimal, InvalidOperation
from django.db import models
from datetime import timedelta
from django.db.models import Q,Sum
from django.dispatch import receiver
from django.utils.timezone import now
from django.db.models.signals import post_save
from rest_framework.exceptions import ValidationError
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin

def get_default_currency_object():
    from .models import CurrencyRate
    return CurrencyRate.objects.get_or_create(
        currency='UZS',
        defaults={'rate_to_uzs': 1}
    )[0]

def get_default_currency():
    return get_default_currency_object().id

def to_uzs(amount, currency_obj) -> Decimal:
    if amount is None or amount == 0:
        return Decimal('0.00')
    
    # If currency_obj is a string (e.g., 'USD'), try to find the actual object
    if isinstance(currency_obj, str):
        try:
            from .models import CurrencyRate
            currency_obj = CurrencyRate.objects.get(currency=currency_obj)
        except:
            return Decimal('0.00')

    if not currency_obj:
        return Decimal(str(amount))

    amount_dec = Decimal(str(amount))
    # Use rate_to_uzs from the object
    rate_to_uzs = Decimal(str(getattr(currency_obj, 'rate_to_uzs', 1)))
    
    return amount_dec * rate_to_uzs

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
    price = models.BigIntegerField(default=0, blank=True)
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
    driver_expense = models.BigIntegerField(default=0)
    returned_advance = models.BigIntegerField(default=0, verbose_name="Kassaga qaytarilgan summa")
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
            driver_expense=self.driver_expense,
            returned_advance=0,
            kilometer=self.kilometer,
            dp_information=self.dp_information,
            count=self.count,
            is_completed=False,
        )
        # Bypassing auto_now_add to restore original created_at
        RaysMod.objects.filter(pk=rays.pk).update(created_at=self.created_at)
        rays.refresh_from_db()
        rays.client.set(self.client.all())

        # ✅ обновляем продукты: переносим с rays_history на новый rays
        for client in self.client.all():
            products = Product.objects.filter(client=client, rays_history=self)
            for product in products:
                product.rays = rays
                product.rays_history = None
                product.is_delivered = False
                product.save()

        # ✅ Reys tarixidan qaytganda uning barcha to'lovlarini o'chiramiz (kassadan pul ayriladi)
        # Mijoz qaytadan to'lashi va kassadan kiritilishi kerak bo'ladi.
        history_txs = CashTransactionHistory.objects.filter(
            Q(rays_history=self) | Q(rays__id=self.rays_id)
        )
        history_txs.delete()

        # ✅ Reys yakunlanganda avtomatik yaratilgan DriverSalary ni o'chiramiz
        if self.driver and self.dr_price > 0:
            auto_salary = DriverSalary.objects.filter(
                driver=self.driver,
                amount=self.dr_price,
                paid_at__gte=self.created_at
            ).order_by('-paid_at').first()
            if auto_salary:
                auto_salary.delete()

        # Mashina, furgon, haydovchini band qilamiz
        if rays.car:
            rays.car.is_busy = True
            rays.car.save()
        if rays.fourgon:
            rays.fourgon.is_busy = True
            rays.fourgon.save()
        if rays.driver:
            rays.driver.is_busy = True
            rays.driver.save()

        self.delete()
        return rays


def archive_product(product):
    product.is_delivered = True
    product.save()

def client_fully_paid_or_in_debt(client, rays):
    # Strictly target products of THIS specific trip that are not yet archived
    products = Product.objects.filter(client_id=client.id, rays_id=rays.id, is_delivered=False)
    total_product_price = products.aggregate(total=Sum('price'))['total'] or 0
    
    if total_product_price <= 0:
        return True # Nothing to pay

    # Target transactions of THIS specific trip or ITS products
    q_filter = Q(rays_id=rays.id) | Q(product__rays_id=rays.id)

    transactions_mod = CashTransactionMod.objects.filter(
        q_filter,
        client_id=client.id,
        status='confirmed'
    ).distinct()
    
    transactions_history = CashTransactionHistory.objects.filter(
        q_filter,
        client_id=client.id,
        status='confirmed'
    ).distinct()

    # Sum payments
    total_paid_mod = transactions_mod.aggregate(total=Sum('amount'))['total'] or 0
    total_paid_history = transactions_history.aggregate(total=Sum('amount'))['total'] or 0

    total_paid = total_paid_mod + total_paid_history

    if total_paid >= total_product_price:
        return True  # Fully paid

    # Check for debt
    has_debt_mod = CashTransactionMod.objects.filter(q_filter, client_id=client.id, is_debt=True, status='confirmed').exists()
    has_debt_history = transactions_history.filter(is_debt=True).exists()
    return has_debt_mod or has_debt_history


class RaysMod(models.Model):
    # ... (existing fields) ...
    driver = models.ForeignKey('CustomUser', on_delete=models.SET_NULL, null=True, blank=True)
    car = models.ForeignKey('CarsMod', on_delete=models.SET_NULL, null=True, blank=True)
    fourgon = models.ForeignKey('FurgonMod', on_delete=models.SET_NULL, null=True, blank=True)
    client = models.ManyToManyField('ClientsMod', blank=True, related_name='rays_clients')
    client_completed = models.ManyToManyField('ClientsMod', blank=True, related_name='completed_clients')
    price = models.BigIntegerField(default=0)
    dr_price = models.BigIntegerField(default=0)
    dp_price = models.BigIntegerField(default=0)
    driver_expense = models.BigIntegerField(default=0)
    returned_advance = models.BigIntegerField(default=0, verbose_name="Kassaga qaytarilgan summa")
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

        rates = {r.currency: float(r.rate_to_uzs) for r in CurrencyRate.objects.all()}

        def local_to_uzs(amount, currency_obj_or_code):
            if not amount: return 0
            if not currency_obj_or_code: return float(amount)
            
            curr = getattr(currency_obj_or_code, 'currency', currency_obj_or_code)
            
            if curr == 'UZS':
                return float(amount)
            elif curr in rates:
                return float(amount) * rates[curr]
            return float(amount)

        # Продукты
        total_uzs_products = 0
        for client in self.client.all():
            products = Product.objects.filter(client=client, rays=self, is_delivered=False)
            for product in products:
                total_uzs_products += local_to_uzs(product.price, product.currency)
        self.price = round(total_uzs_products)

        # Все типы расходов
        start_time = self.created_at
        total_uzs_expenses = 0

        def get_sum(queryset):
            s = 0
            for item in queryset:
                s += local_to_uzs(item.price, getattr(item, 'currency', 'UZS'))
            return s

        total_uzs_expenses += get_sum(Texnics.objects.filter(car=self.car, created_at__gte=start_time).defer('custom_rate_to_uzs'))
        total_uzs_expenses += get_sum(BalonMod.objects.filter(car=self.car, created_at__gte=start_time))
        total_uzs_expenses += get_sum(BalonFurgon.objects.filter(furgon=self.fourgon, created_at__gte=start_time))
        total_uzs_expenses += get_sum(OptolMod.objects.filter(car=self.car, created_at__gte=start_time))
        total_uzs_expenses += get_sum(ChiqimlikMod.objects.filter(driver=self.driver, created_at__gte=start_time))
        self.dr_price = round(total_uzs_expenses)
        self.save()
    
    def archive_all_transactions(self, client, rays_history):
        # Strictly archive transactions belonging to THIS specific trip
        all_tx = CashTransactionMod.objects.filter(client_id=client.id, rays_id=self.id).distinct()
        for tx in all_tx:
            create_history_from_transaction(tx, rays_history=rays_history)
            tx.delete()
    def __str__(self):
        return f"Rays #{self.id} - {self.driver} - {self.country}"

    def complete_whole_race(self):
        # Strictly check all clients of the trip
        for client in self.client.all():
            # Check if this client has fully paid or has an official debt for THIS trip
            if not client_fully_paid_or_in_debt(client, self):
                raise ValidationError(
                    f"❌ Reysni yakunlab bo'lmaydi: Mijoz '{client.company or client.first_name}' hali to'lovni amalga oshirmagan yoki qarz sifatida belgilanmagan."
                )


        # Automatically create a DriverSalary record for the driver
        if self.driver and self.dr_price > 0:
            DriverSalary.objects.create(
                driver=self.driver,
                amount=self.dr_price,
                currency=get_default_currency_object() # Use a helper to get actual object
            )

        history = RaysHistoryMod.objects.create(
            rays_id=self.id,
            country=self.country,
            driver=self.driver,
            car=self.car,
            fourgon=self.fourgon,
            price=self.price,
            dr_price=self.dr_price,
            dp_price=self.dp_price,
            driver_expense=self.driver_expense,
            returned_advance=self.returned_advance,
            dp_information=self.dp_information,
            kilometer=self.kilometer,
            count=self.count
        )
        # Bypassing auto_now_add to save the original created_at in history
        RaysHistoryMod.objects.filter(pk=history.pk).update(created_at=self.created_at)
        history.refresh_from_db()
        history.client.set(self.client.all())

        for client in self.client.all():
            products = Product.objects.filter(client_id=client.id, rays_id=self.id, is_delivered=False)
            for product in products:
                RaysHistoryProduct.objects.create(
                    name=product.name,
                    price=product.price,
                    count=product.count,
                    client=client,
                    rays_history=history,
                    from_location=product.from_location.name if product.from_location else None,
                    to_location=product.to_location.name if product.to_location else None
                )

                # 🟢 ДОБАВЛЯЕМ обновление ссылок:
                product.rays_history = history
                product.rays = None
                archive_product(product)  # вызовет product.is_delivered = True и сохранит

            self.archive_all_transactions(client, rays_history=history)

            client.save()

        CashTransactionHistory.objects.filter(rays_id=self.id).update(rays_history=history)

        expenses = ChiqimlikMod.objects.filter(driver_id=self.driver_id, created_at__gte=self.created_at)
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
    price = models.BigIntegerField(verbose_name="Цена", default=0, blank=True)
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
            # Получаем текущий курс
            rate_dec = Decimal(str(self.currency.rate_to_uzs))
            price_dec = Decimal(str(self.price))

            # Конвертируем в UZS и сохраняем в поле price_in_usd (теперь там будет UZS)
            self.price_in_usd = (price_dec * rate_dec).quantize(Decimal('0.01'))

        except (AttributeError, InvalidOperation):
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

class FuelMod(models.Model):
    car = models.ForeignKey(CarsMod, on_delete=models.SET_NULL, null=True, verbose_name="Машина")
    driver = models.ForeignKey('CustomUser', on_delete=models.SET_NULL, null=True, verbose_name="Haydovchi")
    fuel_type = models.CharField(max_length=50, verbose_name="Тип топлива")
    liters = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Литры/Кубы")
    price = models.BigIntegerField(verbose_name="Цена")
    currency = models.ForeignKey(CurrencyRate, on_delete=models.SET_NULL, null=True, verbose_name="Валюта", default=get_default_currency)
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата создания")

    def __str__(self):
        return f"{self.car.name if self.car else 'Без машины'} - {self.fuel_type} ({self.liters})"

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
    custom_rate_to_uzs = models.DecimalField(max_digits=10, decimal_places=2, default=1.0)
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата создания")

    def __str__(self):
        return f"{self.car.name if self.car else 'Nomalum'} - {self.service.name if self.service else ''}"
 
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

from django.db.models.signals import pre_delete
from django.dispatch import receiver

@receiver(pre_delete, sender=RaysMod)
def free_resources_on_rays_delete(sender, instance, **kwargs):
    if instance.car:
        instance.car.is_busy = False
        instance.car.save(update_fields=['is_busy'])
    if instance.fourgon:
        instance.fourgon.is_busy = False
        instance.fourgon.save(update_fields=['is_busy'])
    if instance.driver:
        instance.driver.is_busy = False
        instance.driver.save(update_fields=['is_busy'])

    # moved_at — когда была перенесена в историюllkjh;lkm,