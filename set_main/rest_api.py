from . import models
from decimal import Decimal,InvalidOperation
from django.utils import timezone
from django.db.models import Q,Sum
from rest_framework import serializers
from rest_framework_simplejwt.tokens import RefreshToken

def to_usd(amount, currency_code):
    """
    Конвертирует сумму из указанной валюты в доллары США.
    """
    try:
        amount = Decimal(str(amount))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal('0.00')

    if currency_code == 'USD':
        return amount

    try:
        currency_rate = models.CurrencyRate.objects.get(currency=currency_code)
        usd_currency = models.CurrencyRate.objects.get(currency='USD')
        usd_rate = Decimal(str(usd_currency.rate_to_uzs))
        
        if usd_rate == 0:
            return Decimal('0.00')

        if currency_code == 'UZS':
            return amount / usd_rate

        # Конвертировать сначала в UZS, затем в USD
        uzs_amount = amount * Decimal(str(currency_rate.rate_to_uzs))
        return uzs_amount / usd_rate
    except (models.CurrencyRate.DoesNotExist, ZeroDivisionError, InvalidOperation):
        return Decimal('0.00')
            
class CurrencySerializer(serializers.ModelSerializer):
    class Meta:
        model = models.CurrencyRate
        fields = '__all__'

class DriverSerializer(serializers.ModelSerializer):
    currency_name = serializers.SerializerMethodField()
    driver_name = serializers.SerializerMethodField()
    class Meta:
        model = models.DriverSalary
        fields = '__all__'

    def get_currency_name(self, obj):
        return getattr(obj.currency, 'currency', 'UZS')

    def get_driver_name(self, obj):
        return obj.driver.fullname if obj.driver else None

class CashCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = models.CashCategory
        fields = '__all__'

class CashTransactionSerializer(serializers.ModelSerializer):
    client_name = serializers.CharField(source='client.first_name', read_only=True)
    driver_name = serializers.CharField(source='driver.fullname', read_only=True)
    product_name = serializers.CharField(source='product.name', read_only=True)
    cashier_name = serializers.CharField(source='cashier.fullname', read_only=True)
    payment_way_name = serializers.CharField(source='payment_way.name', read_only=True)
    class Meta:
        model = models.CashTransactionMod
        fields = [
            'id',
            'client', 'client_name',
            'rays',
            'product', 'product_name',
            'driver', 'driver_name',
            'amount',
            'amount_in_usd',
            'currency',
            'status',
            'payment_way', 'payment_way_name',
            'is_confirmed_by_cashier',
            'cashier', 'cashier_name',
            'comment',
            'is_debt',
            'is_via_driver',
            'is_delivered_to_cashier',
            'total_expected_amount',
            'paid_amount',
            'remaining_debt',
            'created_at',
        ]
        read_only_fields = [
            'status',
            'is_confirmed_by_cashier',
            'cashier',
            'remaining_debt',  # ✅ сделать только для чтения
        ]
    def create(self, validated_data):
        request = self.context['request']
        client = validated_data['client']
        user = request.user

        if not user.is_authenticated:
            validated_data['cashier'] = None
        else:
            validated_data['cashier'] = user

        # Получаем курс USD
        try:
            usd_rate = Decimal(models.CurrencyRate.objects.get(currency='USD').rate_to_uzs)
        except models.CurrencyRate.DoesNotExist:
            usd_rate = Decimal('1')

        # ✅ Локальная функция (без self!)
        def to_usd(value: Decimal, currency):
            try:
                if currency.currency == 'USD':
                    return Decimal(value)
                rate_to_uzs = Decimal(currency.rate_to_uzs)
                return (Decimal(value) * rate_to_uzs) / usd_rate
            except (models.CurrencyRate.DoesNotExist, InvalidOperation):
                return Decimal('0')

        # Оплата (amount) в валюте клиента
        currency = validated_data.get('currency')
        amount = Decimal(validated_data.get('amount', 0))
        amount_in_usd = to_usd(amount, currency)
        validated_data['amount_in_usd'] = round(amount_in_usd, 2)

        # Определяем продукты клиента
        products = models.Product.objects.filter(client=client, is_delivered=False)

        # Ищем, задан ли один конкретный продукт
        product = validated_data.get('product') or None

        if not product:
            # Нет конкретного продукта — считаем по всем
            total_expected_usd = sum(to_usd(p.price, p.currency) for p in products)
            past_paid_usd = models.CashTransactionMod.objects.filter(
                client=client, status='pending'
            ).aggregate(total=Sum('amount_in_usd'))['total'] or Decimal('0')

            total_paid_usd = past_paid_usd + amount_in_usd

            validated_data['total_expected_amount'] = round(total_expected_usd, 2)
            validated_data['paid_amount'] = round(total_paid_usd, 2)
            validated_data['remaining_debt'] = round(max(total_expected_usd - total_paid_usd, 0), 2)
            validated_data['product'] = None  # явно укажем, что продукт не задан
        else:
            # Расчёт по конкретному продукту
            expected_usd = to_usd(product.price, product.currency)
            past_paid_usd = models.CashTransactionMod.objects.filter(
                client=client, product=product, status='pending'
            ).aggregate(total=Sum('amount_in_usd'))['total'] or Decimal('0')

            total_paid_usd = past_paid_usd + amount_in_usd

            validated_data['total_expected_amount'] = round(expected_usd, 2)
            validated_data['paid_amount'] = round(total_paid_usd, 2)
            validated_data['remaining_debt'] = round(max(expected_usd - total_paid_usd, 0), 2)

        # Назначаем водителя, если есть rays и клиент в нём
        rays = validated_data.get('rays')
        if rays and client in rays.client.all():
            validated_data['driver'] = rays.driver

        if validated_data.get('payment_way') and validated_data['payment_way'].name.lower() == 'через водителя':
            validated_data['is_via_driver'] = True

        return super().create(validated_data)

class ConfirmCashTransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.CashTransactionMod
        fields = ['id']

    def update(self, instance, validated_data):
        request = self.context['request']
        user = request.user

        if instance.status != 'pending':
            raise serializers.ValidationError("Только 'pending' транзакции можно подтвердить.")

        currency = validated_data.get('currency', instance.currency)
        amount = Decimal(str(validated_data.get('amount', instance.amount)))
        client = validated_data.get('client', instance.client)
        product = validated_data.get('product', instance.product)

        # Получаем курс USD→UZS
        try:
            usd_rate = Decimal(models.CurrencyRate.objects.get(currency='USD').rate_to_uzs)
        except models.CurrencyRate.DoesNotExist:
            usd_rate = Decimal('1')

        def to_usd(value: Decimal, curr):
            try:
                if curr.currency == 'USD':
                    return Decimal(value)
                rate_to_uzs = Decimal(curr.rate_to_uzs)
                return (Decimal(value) * rate_to_uzs) / usd_rate
            except (models.CurrencyRate.DoesNotExist, InvalidOperation):
                return Decimal('0')

        # 1) Ожидаемая сумма по товарам
        if product:
            expected_usd = to_usd(product.price, product.currency)
            past_paid_usd = (
                models.CashTransactionMod.objects
                .filter(client=client, product=product, status='pending')
                .exclude(id=instance.id)
                .aggregate(total=Sum('amount_in_usd'))['total'] or Decimal('0')
            )
        else:
            prods = models.Product.objects.filter(client=client, is_delivered=False)
            expected_usd = sum(to_usd(p.price, p.currency) for p in prods)
            past_paid_usd = (
                models.CashTransactionMod.objects
                .filter(client=client, status='pending')
                .exclude(id=instance.id)
                .aggregate(total=Sum('amount_in_usd'))['total'] or Decimal('0')
            )
            instance.product = None

        # 2) Конвертация текущего платежа
        amount_in_usd = to_usd(amount, currency)
        total_paid_usd = past_paid_usd + amount_in_usd

        # 3) Остаток долга
        remaining_debt = expected_usd - total_paid_usd
        if remaining_debt < 0:
            remaining_debt = Decimal('0')

        # 4) Сохраняем в транзакции
        instance.amount = int(amount)
        instance.currency = currency
        instance.amount_in_usd         = amount_in_usd.quantize(Decimal('0.01'))
        instance.total_expected_amount = expected_usd.quantize(Decimal('0.01'))
        instance.paid_amount           = total_paid_usd.quantize(Decimal('0.01'))
        instance.remaining_debt        = remaining_debt.quantize(Decimal('0.01'))
        instance.status                = 'confirmed'
        instance.is_confirmed_by_cashier = True
        # если аноним — cashier остаётся None
        if user.is_authenticated:
            instance.cashier = user
        instance.save()

        # 5) Перенос в историю и удаление оригинала
        models.create_history_from_transaction(instance)
        instance.delete()
        return instance

class CashTransactionHistorySerializer(serializers.ModelSerializer):
    client_name = serializers.SerializerMethodField()
    payment_name = serializers.SerializerMethodField()
    driver_name = serializers.SerializerMethodField()
    class Meta:
        model = models.CashTransactionHistory
        fields = '__all__'

    def get_client_name(self, obj):
        return obj.client.first_name if obj.client else None
    def get_payment_name(self,obj):
        return obj.payment_way.name if obj.payment_way else None
    def get_driver_name(self, obj):
        return obj.driver.fullname if obj.driver else None


    
class TexnicsSerializer(serializers.ModelSerializer):
    service_name = serializers.CharField(source="service.name", read_only=True)
    class Meta:
        model = models.Texnics
        fields = ["service_name", "kilometer"]  # <-- to'g'rilandi

class RaysHistorySerializer(serializers.ModelSerializer):
    driver_name = serializers.CharField(source="driver.username", read_only=True)
    client_name = serializers.CharField(source="client.first_name", read_only=True)
    car_name = serializers.CharField(source="car.name", read_only=True)
    furgon_name = serializers.CharField(source="fourgon.name", read_only=True)
    texnics = serializers.SerializerMethodField()
    class Meta:
        model = models.RaysHistoryMod
        fields = ["driver_name", "client_name", "car_name", "furgon_name", "price",'dr_price','dp_price', "kilometer",'dp_information', "created_at", "texnics"]
    def get_texnics(self, obj):
        texnics = models.Texnics.objects.filter(car=obj.car)
        print(f"Texnics for {obj.car}: {texnics}")
        return TexnicsSerializer(texnics, many=True).data

class CarHistorySerializer(serializers.ModelSerializer):
    history = RaysHistorySerializer(source="rayshistorymod_set", many=True)
    class Meta:
        model = models.CarsMod
        fields = ["name", "number", "year", "history"]

class ServiceSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.Service
        fields = '__all__'
        
class RaysHistoryClientSerializer(serializers.ModelSerializer):
    driver_name = serializers.CharField(source="driver.username", read_only=True)
    client_name = serializers.CharField(source="client.first_name", read_only=True)
    car_name = serializers.CharField(source="car.name", read_only=True)
    furgon_name = serializers.CharField(source="fourgon.name", read_only=True)
    texnics = serializers.SerializerMethodField()
    class Meta:
        model = models.RaysHistoryMod
        fields = ["driver_name", "client_name", "car_name", "furgon_name", "price","created_at", "texnics"]
    def get_texnics(self, obj):
        texnics = models.Texnics.objects.filter(car=obj.car)
        print(f"Texnics for {obj.car}: {texnics}")
        return TexnicsSerializer(texnics, many=True).data

class ClientHistorySerializer(serializers.ModelSerializer):
    history = RaysHistoryClientSerializer(source="rayshistorymod_set", many=True)
    class Meta:
        model = models.ClientsMod
        fields = ["first_name", "last_name", "number", "history"]

class CountrySerializer(serializers.ModelSerializer):
    class Meta:
        model = models.CountryMod
        fields = '__all__'

class TexSerializer(serializers.ModelSerializer):
    car_name = serializers.SerializerMethodField()
    class Meta:
        model = models.Texnics
        fields = '__all__'
    def get_car_name(self, obj):
        return obj.car.name

class ClientsSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.ClientsMod
        fields = '__all__'

def get_driver_total_rays_usd(driver):
    from .models import RaysHistoryMod
    total = 0
    for ray in RaysHistoryMod.objects.filter(driver=driver):
        if ray.price:
            total += float(ray.price)
    return round(total, 2)
class CustomUserSerializer(serializers.ModelSerializer):
    rays_count = serializers.SerializerMethodField()
    total_rays_usd = serializers.SerializerMethodField()
    token = serializers.SerializerMethodField()

    class Meta:
        model = models.CustomUser
        fields = [
            'id', 'username', 'password', 'fullname', 'photo', 'phone_number', 'status', 'date',
            'passport_series', 'passport_number', 'passport_issued_by', 'passport_issued_date',
            'passport_birth_date', 'passport_photo_front', 'passport_photo_back', 
            'license_number', 'license_expiry', 'is_busy', 'rays_count', 'total_rays_usd', 'token'
        ]
        extra_kwargs = {
            'password': {
                'write_only': True,
                'required': False,
                'allow_blank': False
            }
        }

    def get_token(self, user):
        refresh = RefreshToken.for_user(user)
        return {
            'refresh': str(refresh),
            'access': str(refresh.access_token)
        }

    def get_rays_count(self, obj):
        return models.RaysHistoryMod.objects.filter(driver=obj).count()

    def get_total_rays_usd(self, obj):
        from .models import RaysHistoryMod
        total = 0
        for ray in RaysHistoryMod.objects.filter(driver=obj):
            if ray.price:
                total += float(ray.price)
        return round(total, 2)

    def create(self, validated_data):
        password = validated_data.pop('password', None)
        user = models.CustomUser(**validated_data)
        if password:
            user.set_password(password)
        else:
            raise serializers.ValidationError({'password': 'Пароль обязателен.'})
        user.save()
        return user

    def update(self, instance, validated_data):
        password = validated_data.pop('password', None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        if password:
            instance.set_password(password)
        instance.save()
        return instance

    # def get_rays_count(self, obj):
    #     return models.RaysHistoryMod.objects.filter(driver=obj).count()

    # def get_total_rays_usd(self, obj):
    #     return get_driver_total_rays_usd(obj)


    
class ChiqimlarCategorySerializer(serializers.ModelSerializer):
	class Meta:
		model = models.ChiqimlarCategory
		fields = '__all__'

class ChiqimlikSerializer(serializers.ModelSerializer):
    driver_name = serializers.SerializerMethodField()
    class Meta:
        model = models.ChiqimlikMod
        fields = '__all__'

    def get_driver_name(self, obj):
        return obj.driver.fullname if obj.driver else None

class CarsSerializer(serializers.ModelSerializer):
	class Meta:
		model = models.CarsMod
		fields = '__all__'
	
class ReferensSerializer(serializers.ModelSerializer):
    driver_name = serializers.SerializerMethodField()
    class Meta:
        model = models.ReferensMod
        fields = '__all__'

    def get_driver_name(self, obj):
        return obj.driver.fullname if obj.driver else None

class ArizaSerializer(serializers.ModelSerializer):
    driver_name = serializers.SerializerMethodField()

    class Meta:
        model = models.ArizaMod
        fields = '__all__'

    def get_driver_name(self, obj):
        return obj.driver.fullname if obj.driver else None

class FurgonSerializer(serializers.ModelSerializer):
	class Meta:
		model = models.FurgonMod
		fields = '__all__'

class FromLocationSerializer(serializers.ModelSerializer): # Детальная информация о фургоне
    class Meta:
        model = models.FromLocation
        fields = '__all__'

class ToLocationSerializer(serializers.ModelSerializer): # Детальная информация о фургоне
    class Meta:
        model = models.ToLocation
        fields = '__all__'

class ProductSerializer(serializers.ModelSerializer):
    from_location_name = serializers.SerializerMethodField()
    to_location_name = serializers.SerializerMethodField()
    client_name = serializers.SerializerMethodField()
    currency_name = serializers.SerializerMethodField()
    # rays = serializers.PrimaryKeyRelatedField(read_only=True) 
    class Meta:
        model = models.Product
        fields = '__all__'
    
    def get_currency_name(self, obj):
        return obj.currency.currency if obj.currency else None
    
    def get_client_name(self, obj):
        return f'{obj.client.first_name} {obj.client.last_name}'

    def get_from_location_name(self, obj):
        return obj.from_location.name if obj.from_location else None

    def get_to_location_name(self, obj):
        return obj.to_location.name if obj.to_location else None
    
class ClientWithProductsSerializer(serializers.ModelSerializer):
    products = serializers.SerializerMethodField()  # заменили ProductSerializer на SerializerMethodField

    class Meta:
        model = models.ClientsMod
        fields = ['id', 'first_name', 'last_name', 'number', 'products']

    def get_products(self, obj):
        rays = self.context.get('rays')  # получаем текущий рейс из контекста
        if rays and hasattr(rays, '_prefetched_objects_cache') and 'product_set' in rays._prefetched_objects_cache:
            products = [p for p in rays.product_set.all() if p.client_id == obj.id and not p.is_delivered]
            return ProductSerializer(products, many=True).data

        products = models.Product.objects.filter(client=obj, rays=rays, is_delivered=False)
        return ProductSerializer(products, many=True).data

class OptolSerializer(serializers.ModelSerializer): # Детальная информация о фургоне
    car_name = serializers.SerializerMethodField()
    class Meta:
        model = models.OptolMod
        fields = '__all__'
    
    def get_car_name(self, obj):
        return obj.car.name

class BolonFurgonSerializer(serializers.ModelSerializer): # Детальная информация о фургоне
    furgon_name = serializers.SerializerMethodField()
    class Meta:
        model = models.BalonFurgon
        fields = '__all__'

    def get_furgon_name(self,obj):
        return obj.furgon.name

class BalonSerializer(serializers.ModelSerializer):
    car_name = serializers.SerializerMethodField()
    class Meta:
        model = models.BalonMod
        fields = '__all__'

    def get_car_name(self, obj):
        return obj.car.name if obj.car else None
    
class RaysHistoryProductSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.RaysHistoryProduct
        fields = ['name', 'price', 'count', 'from_location', 'to_location']

class RaysHistoryExpenseSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.RaysHistoryExpense
        fields = '__all__'

class SimpleUserSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.CustomUser  # или CustomUser, если у тебя кастомная модель
        fields = ['id','fullname', 'phone_number']

class SimpleClientSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.ClientsMod
        fields = ['first_name', 'number']

class SimpleCarSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.CarsMod
        fields = ['name', 'number']

class SimpleFurgonSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.FurgonMod
        fields = ['name', 'number']

class SimpleRaysHistorySerializer(serializers.ModelSerializer):
    class Meta:
        model = models.RaysHistoryMod
        fields = ['id', 'created_at']

class SimpleCountrySerializer(serializers.ModelSerializer):
    class Meta:
        model = models.CountryMod
        fields = ['id', 'name']

class ClientWithProductsHistorySerializer(serializers.ModelSerializer):
    products = serializers.SerializerMethodField()
    class Meta:
        model = models.ClientsMod
        fields = ['id', 'first_name', 'last_name', 'number', 'products']
    def get_products(self, obj):
        rays_history = self.context.get('rays_history')
        if rays_history and hasattr(rays_history, '_prefetched_objects_cache') and 'product_set' in rays_history._prefetched_objects_cache:
            products = [p for p in rays_history.product_set.all() if p.client_id == obj.id]
            return ProductSerializer(products, many=True).data

        products = models.Product.objects.filter(client=obj, rays_history=rays_history)
        return ProductSerializer(products, many=True).data

class ExtendedRaysHistorySerializer(serializers.ModelSerializer):
    expenses = serializers.SerializerMethodField()
    driver = SimpleUserSerializer(read_only=True)
    car = SimpleCarSerializer(read_only=True)
    fourgon = SimpleFurgonSerializer(read_only=True)
    country = SimpleCountrySerializer(read_only=True)
    client = serializers.SerializerMethodField()
    class Meta:
        model = models.RaysHistoryMod
        fields = [
            'id', 'rays_id', 'country', 'driver', 'car', 'fourgon', 'client',
            'price', 'dr_price', 'dp_price', 'dp_currency',
            'kilometer', 'dp_information', 'created_at', 'count',
            'expenses'
        ]
    expenses = RaysHistoryExpenseSerializer(source='rayshistoryexpense_set', many=True, read_only=True)
    def get_client(self, obj):
        clients = obj.client.all()
        return ClientWithProductsHistorySerializer(clients, many=True, context={'rays_history': obj}).data
    
    def to_representation(self, instance):
        rep = super().to_representation(instance)
        # Frontend expects these as objects, but ExtendedRaysHistorySerializer already has them as objects
        # We just need to make sure the naming matches what the frontend expects if different
        return rep

class RaysSerializer(serializers.ModelSerializer):
    country_name = serializers.SerializerMethodField()
    dp_currency_name = serializers.SerializerMethodField()
    expenses = serializers.SerializerMethodField()
    driver = serializers.PrimaryKeyRelatedField(
        queryset=models.CustomUser.objects.none(), write_only=True, required=False
    )
    car = serializers.PrimaryKeyRelatedField(
        queryset=models.CarsMod.objects.none(), write_only=True, required=False
    )
    fourgon = serializers.PrimaryKeyRelatedField(
        queryset=models.FurgonMod.objects.none(), write_only=True, required=False
    )
    client = serializers.PrimaryKeyRelatedField(
        queryset=models.ClientsMod.objects.all(), many=True, write_only=True, required=False
    )
    client_completed = serializers.PrimaryKeyRelatedField(
        queryset=models.ClientsMod.objects.all(), many=True, required=False, write_only=True
    )
    driver_data = SimpleUserSerializer(source='driver', read_only=True)
    car_data = SimpleCarSerializer(source='car', read_only=True)
    fourgon_data = SimpleFurgonSerializer(source='fourgon', read_only=True)
    client_data = serializers.SerializerMethodField()
    client_completed_data = SimpleClientSerializer(source='client_completed', many=True, read_only=True)
    class Meta:
        model = models.RaysMod
        fields = [
            'id', 'country', 'driver', 'car', 'fourgon', 'client', 'client_completed',
            'price', 'dr_price', 'dp_price', 'dp_currency',
            'kilometer', 'dp_information', 'created_at', 'count', 'is_completed',
            'car_data', 'fourgon_data', 'client_data', 'driver_data', 'client_completed_data', 
            'expenses', 'country_name', 'dp_currency_name'
        ]

    def get_dp_currency_name(self, obj):
        return obj.dp_currency.currency if obj.dp_currency else None

    def get_client_data(self, obj):
        # Optimized: products are prefetched in the view
        clients = obj.client.all()
        return ClientWithProductsSerializer(
            clients,
            many=True,
            context={'rays': obj}
        ).data

    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['car'].queryset = self.get_car_queryset()
        self.fields['driver'].queryset = self.get_driver_queryset()
        self.fields['fourgon'].queryset = self.get_fourgon_queryset()
    
    def get_country_name(self, obj):
        return obj.country.name if obj.country else None

    def get_expenses(self, obj):
        if not obj.driver:
            return {}

        driver = obj.driver
        start_time = obj.created_at

        # Загружаем только расходы после начала рейса
        texnics = models.Texnics.objects.filter(car=obj.car, created_at__gte=start_time)
        balons = models.BalonMod.objects.filter(car=obj.car, created_at__gte=start_time)
        balon_furgons = models.BalonFurgon.objects.filter(furgon=obj.fourgon, created_at__gte=start_time)
        optols = models.OptolMod.objects.filter(car=obj.car, created_at__gte=start_time)
        chiqimliks = models.ChiqimlikMod.objects.filter(driver=driver, created_at__gte=start_time)
        arizas = models.ArizaMod.objects.filter(driver=driver, created_at__gte=start_time)
        referens = models.ReferensMod.objects.filter(driver=driver, created_at__gte=start_time)

        total_usd = 0

        def serialize_qs(qs, price_field='price', currency_field='currency'):
            result = []
            nonlocal total_usd
            for item in qs:
                amount = getattr(item, price_field, 0)
                currency_obj = getattr(item, currency_field, None)
                currency_code = currency_obj.currency if currency_obj else 'USD'
                usd_value = to_usd(amount, currency_code)
                total_usd += usd_value
                result.append({
                    "id": item.id,
                    "price": amount,
                    "currency": currency_code,
                    "usd_value": round(usd_value, 2),
                })
            return result

        return {
            "texnics": serialize_qs(texnics),
            "balons": serialize_qs(balons),
            "balon_furgons": serialize_qs(balon_furgons),
            "optols": serialize_qs(optols),
            "chiqimliks": serialize_qs(chiqimliks),
            "arizalar": ArizaSerializer(arizas, many=True).data,
            "referenslar": ReferensSerializer(referens, many=True).data,

            "total_usd": round(total_usd, 2)
        }

    def get_car_queryset(self):
        instance = getattr(self, 'instance', None)
        if instance and not isinstance(instance, list):
            if instance.car:
                return models.CarsMod.objects.filter(Q(is_busy=False) | Q(id=instance.car.id))
            return models.CarsMod.objects.filter(is_busy=False)
        return models.CarsMod.objects.filter(is_busy=False)

    def get_driver_queryset(self):
        instance = getattr(self, 'instance', None)
        if instance and not isinstance(instance, list) and instance.driver:
            return models.CustomUser.objects.filter(status='driver').filter(Q(is_busy=False) | Q(id=instance.driver.id))
        return models.CustomUser.objects.filter(status='driver', is_busy=False)
    def get_fourgon_queryset(self):
        instance = getattr(self, 'instance', None)
        if instance and not isinstance(instance, list) and instance.fourgon:
            return models.FurgonMod.objects.filter(Q(is_busy=False) | Q(id=instance.fourgon.id))
        return models.FurgonMod.objects.filter(is_busy=False)
    def validate_driver(self, value):
        instance = getattr(self, 'instance', None)
        if instance and instance.driver and instance.driver.id == value.id:
            return value
        if value.is_busy:
            raise serializers.ValidationError("Этот водитель уже участвует в активном рейсе.")
        return value

    def to_representation(self, instance):
        rep = super().to_representation(instance)
        # Safely swap IDs with objects for the frontend
        if 'car_data' in rep:
            rep['car'] = rep.pop('car_data')
        if 'fourgon_data' in rep:
            rep['fourgon'] = rep.pop('fourgon_data')
        if 'client_data' in rep:
            rep['client'] = rep.pop('client_data')
        if 'driver_data' in rep:
            rep['driver'] = rep.pop('driver_data')
        if 'client_completed_data' in rep:
            rep['client_completed'] = rep.pop('client_completed_data')
        return rep

    def create(self, validated_data):
        clients = validated_data.pop('client', [])
        clients_completed = validated_data.pop('client_completed', [])

        # Обработка случая, если данные пришли в initial_data как список ID
        if not clients:
            clients = self.initial_data.getlist('client') if hasattr(self.initial_data, 'getlist') else self.initial_data.get('client', [])
        if not clients_completed:
            clients_completed = self.initial_data.getlist('client_completed') if hasattr(self.initial_data, 'getlist') else self.initial_data.get('client_completed', [])

        # Преобразуем объекты или строки/числа в ID
        clients = [c.id if isinstance(c, models.ClientsMod) else int(c) for c in clients]
        clients_completed = [c.id if isinstance(c, models.ClientsMod) else int(c) for c in clients_completed]

        # Создаём объект RaysMod
        instance = models.RaysMod(**validated_data)
        instance.price = 0  # будет пересчитано позже
        instance.dr_price = 0
        instance.save()

        # Устанавливаем ManyToMany отношения
        if clients:
            instance.client.set(clients)
        if clients_completed:
            instance.client_completed.set(clients_completed)

        # Пересчёт цен
        instance.update_prices_from_products_and_expenses()

        # Обновление статуса сущностей
        if instance.car:
            instance.car.is_busy = True
            instance.car.save()
        if instance.fourgon:
            instance.fourgon.is_busy = True
            instance.fourgon.save()
        if instance.driver:
            instance.driver.is_busy = True
            instance.driver.save()

        return instance

    def update(self, instance, validated_data):
        clients = validated_data.pop('client', None)
        clients_completed = validated_data.pop('client_completed', None)
        car = validated_data.pop('car', None)
        fourgon = validated_data.pop('fourgon', None)
        driver = validated_data.pop('driver', None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        if car:
            instance.car = car
        if fourgon:
            instance.fourgon = fourgon
        if driver:
            instance.driver = driver
        instance.save()
        if clients is not None:
            clients = [c.id if isinstance(c, models.ClientsMod) else c for c in clients]
            instance.client.set(clients)
            instance.update_prices_from_products_and_expenses()

        if clients_completed is not None:
            clients_completed = [c.id if isinstance(c, models.ClientsMod) else c for c in clients_completed]
            instance.client_completed.set(clients_completed)
        return instance

class RaysHSerializer(serializers.ModelSerializer):
    driver = serializers.PrimaryKeyRelatedField(queryset=models.CustomUser.objects.all(), write_only=True)
    driver_data = SimpleUserSerializer(source='driver', read_only=True)
    car = serializers.PrimaryKeyRelatedField(queryset=models.CarsMod.objects.all(), write_only=True)
    car_data = SimpleCarSerializer(source='car', read_only=True)
    fourgon = serializers.PrimaryKeyRelatedField(queryset=models.FurgonMod.objects.all(), write_only=True)
    fourgon_data = SimpleFurgonSerializer(source='fourgon', read_only=True)
    client = serializers.PrimaryKeyRelatedField(queryset=models.ClientsMod.objects.all(), many=True, write_only=True)
    client_data = SimpleClientSerializer(source='client', many=True, read_only=True)
    class Meta:
        model = models.RaysHistoryMod
        fields = '__all__'

class CarDetailsSerializer(serializers.Serializer):
    car = CarsSerializer()
    chiqimliklar = ChiqimlikSerializer(many=True)
    referenslar = ReferensSerializer(many=True)
    arizalar = ArizaSerializer(many=True)
    optollar = OptolSerializer(many=True)
    balonlar = BalonSerializer(many=True)
    texniklar = TexSerializer(many=True)