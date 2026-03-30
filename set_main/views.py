from decimal import Decimal
from drf_yasg import openapi
from openpyxl import Workbook
from . import models, rest_api
from operator import itemgetter
from django.db.models import Sum
from rest_framework import status
from django.db.models import Count
from rest_framework import viewsets
from collections import defaultdict
from django.http import HttpResponse
from django.utils.timezone import now
from .pagination import RaysPagination
from datetime import timedelta, datetime
from rest_framework.viewsets import ViewSet
from django.db.models import Prefetch
from rest_framework.decorators import action
from django.contrib.auth import authenticate
from rest_framework.response import Response
from django.utils.dateparse import parse_date
from django.contrib.auth import get_user_model
from drf_yasg.utils import swagger_auto_schema
from rest_framework.permissions import AllowAny
from rest_framework import permissions
from rest_framework.filters import SearchFilter
from rest_framework_simplejwt.tokens import RefreshToken
from .permissions import IsOwnerOrCEO, IsCashierOrAdmin, IsZaphosOrAdmin, IsDriverOrAdmin
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from .docs import load_doc as docs
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from django.db.models import Sum, F, Case, When, DecimalField
from django.db.models.functions import Coalesce
from django.db.models import OuterRef, Subquery, Sum, Value, DecimalField

User = get_user_model()

def to_usd(amount, currency_obj) -> Decimal:
    if amount is None or amount == 0:
        return Decimal('0.00')
    
    # If currency_obj is a string (e.g., 'USD'), try to find the actual object
    if isinstance(currency_obj, str):
        try:
            currency_obj = models.CurrencyRate.objects.get(currency=currency_obj)
        except models.CurrencyRate.DoesNotExist:
            return Decimal('0.00')

    if not currency_obj:
        return Decimal('0.00')

    amount_dec = Decimal(str(amount))
    rate_to_uzs = Decimal(str(currency_obj.rate_to_uzs))
    
    amount_in_uzs = amount_dec * rate_to_uzs
    
    try:
        usd_currency = models.CurrencyRate.objects.get(currency='USD')
        usd_rate = Decimal(str(usd_currency.rate_to_uzs))
        return amount_in_uzs / usd_rate
    except (models.CurrencyRate.DoesNotExist, InvalidOperation, ZeroDivisionError):
        return Decimal('0.00')


def get_client_total_expected_usd(client):
    from .models import Product
    total_usd = 0
    for product in Product.objects.filter(client=client, is_delivered=False):
        currency = getattr(product, 'currency', 'USD')
        price = getattr(product, 'price', 0)
        total_usd += to_usd(price, currency)
    return total_usd

class CurrencyRateViewSet(viewsets.ModelViewSet):
    def get_permissions(self):
        if self.action in ['list', 'retrieve']:
            permission_classes = [permissions.IsAuthenticated]
        else:
            permission_classes = [IsOwnerOrCEO]
        return [permission() for permission in permission_classes]

    queryset = models.CurrencyRate.objects.all()
    serializer_class = rest_api.CurrencySerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]

class DriverViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.AllowAny]
    queryset = models.DriverSalary.objects.select_related('driver', 'currency').all()
    serializer_class = rest_api.DriverSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    @action(detail=True, methods=['get'], url_path='driver-salary-summary')
    def driver_salary_summary(self, request, pk=None):
        try:
            driver = models.CustomUser.objects.get(pk=pk)
        except models.CustomUser.DoesNotExist:
            return Response({"error": "🚫 Водитель не найден"}, status=404)

        salaries = models.DriverSalary.objects.filter(driver=driver)

        # фильтрация по дате через query-параметры
        date_from = request.query_params.get('date_from')
        date_to = request.query_params.get('date_to')

        if date_from:
            salaries = salaries.filter(created_at__date__gte=date_from)
        if date_to:
            salaries = salaries.filter(created_at__date__lte=date_to)

        total_by_currency = defaultdict(Decimal)
        total_paid_usd = Decimal('0.00')

        for s in salaries:
            if not s.currency:
                continue  # пропускаем если нет валюты

            total_by_currency[s.currency.currency] += s.amount

            try:
                usd_value = to_usd(s.amount, s.currency)
                total_paid_usd += usd_value
            except Exception as e:
                continue

        return Response({
            "driver": rest_api.CustomUserSerializer(driver).data,
            "salary_records": rest_api.DriverSerializer(salaries, many=True).data,
            "total_by_currency": {k: float(v) for k, v in total_by_currency.items()},
            "total_paid_usd": round(float(total_paid_usd), 2)
        })

class CashCategoryViewSet(viewsets.ModelViewSet):
    permission_classes = [IsCashierOrAdmin]
    queryset = models.CashCategory.objects.all()
    serializer_class = rest_api.CashCategorySerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]

class CashTransactionViewSet(viewsets.ModelViewSet):
    queryset = models.CashTransactionMod.objects.select_related(
        'client', 'rays', 'product', 'driver', 'currency', 'payment_way', 'cashier'
    ).all()
    serializer_class = rest_api.CashTransactionSerializer 
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['is_via_driver', 'is_delivered_to_cashier', 'status', 'cashier']
    permission_classes = [IsCashierOrAdmin]  
    
    @action(detail=False, methods=['get'], url_path='cash-pay-present')
    def cash_pay_present(self, request):
        # Получаем список ID всех клиентов, кто участвовал в транзакциях (либо живая транзакция, либо история)
        clients_in_current = models.CashTransactionMod.objects.values_list('client_id', flat=True)
        clients_in_history = models.CashTransactionHistory.objects.values_list('client_id', flat=True)

        # Все уникальные клиенты
        all_client_ids = set(clients_in_current).union(set(clients_in_history))

        total_clients = len(all_client_ids)

        # Считаем количество оплативших клиентов (из истории транзакций, с подтверждением кассира)
        paid_clients_ids = models.CashTransactionHistory.objects.filter(
            is_confirmed_by_cashier=True,
            status="confirmed"
        ).values_list('client_id', flat=True).distinct()

        paid_clients_count = len(set(paid_clients_ids))

        # Вычисляем количество не оплативших клиентов
        unpaid_clients_count = total_clients - paid_clients_count
        if unpaid_clients_count < 0:
            unpaid_clients_count = 0  # защита от отрицательных значений

        # Вычисляем проценты
        percent_paid = (paid_clients_count / total_clients * 100) if total_clients > 0 else 0
        percent_unpaid = (unpaid_clients_count / total_clients * 100) if total_clients > 0 else 0

        return Response({
            "total_clients": total_clients,
            "paid_clients": paid_clients_count,
            "unpaid_clients": unpaid_clients_count,
            "percent_paid": round(percent_paid, 2),
            "percent_unpaid": round(percent_unpaid, 2)
        })

    @action(detail=False,methods=['get'],url_path='counts')
    def get_count(self,request):
        car_count = models.CarsMod.objects.all().count()
        client_count = models.ClientsMod.objects.all().count()
        rays_count = models.RaysMod.objects.all().count()
        return Response({
            'car_count':car_count,
            'client_count':client_count,
            'rays_count':rays_count
        })

    @action(detail=False, methods=['get'], url_path='clients-summary')
    def clients_summary(self, request):
        # Под-запрос: сумма price_in_usd по всем продуктам клиента
        products_sum_sq = (
            models.Product.objects
            .filter(client=OuterRef('pk'))
            .values('client')
            .annotate(total=Sum('price_in_usd'))
            .values('total')
        )

        # Под-запрос: сумма amount_in_usd по подтверждённым историям
        payments_sum_sq = (
            models.CashTransactionHistory.objects
            .filter(client=OuterRef('pk'), is_confirmed_by_cashier=True)
            .values('client')
            .annotate(total=Sum('amount_in_usd'))
            .values('total')
        )

        qs = (
            models.ClientsMod.objects
            .filter(rays_clients__is_completed=False)
            .distinct()
            .annotate(
                total_expected_usd=Coalesce(
                    Subquery(products_sum_sq),
                    Value(Decimal('0')),
                    output_field=DecimalField()
                ),
                total_paid_usd=Coalesce(
                    Subquery(payments_sum_sq),
                    Value(Decimal('0')),
                    output_field=DecimalField()
                )
            )
            .prefetch_related(
                Prefetch(
                    'rays_clients',
                    queryset=models.RaysMod.objects.filter(is_completed=False).only('id'),
                    to_attr='active_rays'
                )
            )
        )

        result = []
        for client in qs:
            expected = client.total_expected_usd
            paid     = client.total_paid_usd
            remaining = expected - paid

            result.append({
                "client_id": client.id,
                "client_name": f"{client.first_name} {client.last_name}",
                "active_rays": [r.id for r in client.active_rays],
                "total_expected_usd": float(expected.quantize(Decimal('0.01'))),
                "total_paid_usd":     float(paid.quantize(Decimal('0.01'))),
                "total_remaining_usd": float(remaining.quantize(Decimal('0.01')))
            })

        return Response(result)

    @action(detail=False, methods=['get'], url_path='via-driver-summary')
    def via_driver_summary(self, request):
        transactions = models.CashTransactionMod.objects.filter(is_via_driver=True, status='pending')
        
        summary = defaultdict(lambda: defaultdict(lambda: {"usd": 0, "original": 0, "currency": ""}))

        for tx in transactions:
            driver = tx.driver.fullname if tx.driver else "❓ Без водителя"
            client = tx.client.first_name if tx.client else "❓ Без клиента"

            summary[driver][client]["usd"] += float(tx.amount_in_usd)
            summary[driver][client]["original"] += float(tx.amount)
            summary[driver][client]["currency"] = tx.currency.currency

        response_data = []
        for driver, clients in summary.items():
            for client, amounts in clients.items():
                response_data.append({
                    "driver": driver,
                    "client": client,
                    "amount_in_usd": round(amounts["usd"], 2),
                    "amount_original": round(amounts["original"], 2),
                    "currency": amounts["currency"]
                })
        return Response(response_data)

    @action(detail=False, methods=['get'], url_path='rays-clients-map')
    def rays_clients_map(self, request):
        active_rays = models.RaysMod.objects.filter(is_completed=False).prefetch_related('client')
        active_ray_ids = [r.id for r in active_rays]
        
        # 1. Bulk fetch all confirmed cash histories for these rays
        cash_histories = models.CashTransactionHistory.objects.filter(
            rays_id__in=active_ray_ids, status='confirmed'
        ).values('rays_id', 'client_id').annotate(
            paid=Sum('amount_in_usd')
        )
        ch_map = {(item['rays_id'], item['client_id']): item['paid'] for item in cash_histories}

        # 2. Bulk fetch all products for these rays
        products_data = models.Product.objects.filter(
            rays_id__in=active_ray_ids
        ).values('rays_id', 'client_id').annotate(
            expected=Sum('price_in_usd')
        )
        prod_map = {(item['rays_id'], item['client_id']): item['expected'] for item in products_data}

        data = []
        for rays in active_rays:
            clients_data = []
            for client in rays.client.all():
                casa_paid = ch_map.get((rays.id, client.id), 0)
                total_expected = prod_map.get((rays.id, client.id), 0)
                
                clients_data.append({
                    "id": client.id,
                    "first_name": f'{client.first_name} {client.last_name}',
                    "total_expected_amount_usd": float(total_expected),
                    "casa_paid": float(casa_paid),
                    "total_remaining_usd": float(total_expected - casa_paid)
                })

            data.append({
                "rays_id": rays.id,
                "clients": clients_data
            })

        return Response(data)

    # permission_classes = [IsAuthenticated]
    @docs.casa_overview_doc
    @action(detail=False, methods=['get'], url_path='overview', url_name='overview')
    def overview(self, request):
        from datetime import datetime, timedelta
        from django.utils.timezone import now
        from django.db.models import Sum

        period = request.query_params.get('period')
        start_date = request.query_params.get('start_date')
        end_date = request.query_params.get('end_date')

        # Определяем дату фильтра
        date_from = None
        date_to = None

        if period == 'week':
            date_from = now() - timedelta(days=7)
        elif period == 'month':
            date_from = now() - timedelta(days=30)
        elif period == 'year':
            date_from = now() - timedelta(days=365)
        elif period == 'custom':
            try:
                if start_date:
                    date_from = datetime.strptime(start_date, "%Y-%m-%d")
                if end_date:
                    date_to = datetime.strptime(end_date, "%Y-%m-%d")
            except ValueError:
                return Response({"error": "Invalid date format. Use YYYY-MM-DD."}, status=400)

        # Фильтр для CashTransactionHistory (поле created_at)
        cashbox_filter = {}
        if date_from:
            cashbox_filter['created_at__gte'] = date_from
        if date_to:
            cashbox_filter['created_at__lte'] = date_to

        cashbox = models.CashTransactionHistory.objects.filter(
            is_confirmed_by_cashier=True,
            status="confirmed",
            **cashbox_filter
        ).values('currency__currency').annotate(
            total=Sum('amount')
        )

        currency_totals = {"USD": 0, "RUB": 0, "EUR": 0, "UZS": 0}

        for item in cashbox:
            currency = item['currency__currency']
            amount = item['total'] or 0
            if currency in currency_totals:
                currency_totals[currency] += float(amount)

        rates = {rate.currency: float(rate.rate_to_uzs) for rate in models.CurrencyRate.objects.all()}
        usd_rate = rates.get('USD', 1) or 1

        total_in_usd = 0
        for curr, amount in currency_totals.items():
            if amount == 0:
                continue
            if curr == 'USD':
                total_in_usd += amount
            elif curr == 'UZS':
                total_in_usd += amount / usd_rate
            elif curr in rates:
                amount_in_uzs = amount * rates[curr]
                total_in_usd += amount_in_uzs / usd_rate

        # Фильтр для моделей с created_at
        created_at_filter = {}
        if date_from:
            created_at_filter['created_at__gte'] = date_from
        if date_to:
            created_at_filter['created_at__lte'] = date_to

        dp_prices = 0

        def sum_expenses(qs):
            nonlocal dp_prices
            for item in qs.filter(**created_at_filter):
                amount = getattr(item, 'price', 0)
                currency_obj = getattr(item, 'currency', None)
                if not currency_obj:
                    continue
                rate = float(currency_obj.rate_to_uzs)
                curr_code = currency_obj.currency
                if curr_code == 'USD':
                    dp_prices += float(amount)
                elif curr_code == 'UZS':
                    dp_prices += float(amount) / usd_rate
                else:
                    dp_prices += (float(amount) * rate) / usd_rate

        sum_expenses(models.Texnics.objects.select_related('currency').all())
        sum_expenses(models.BalonMod.objects.select_related('currency').all())
        sum_expenses(models.BalonFurgon.objects.select_related('currency').all())
        sum_expenses(models.OptolMod.objects.select_related('currency').all())
        sum_expenses(models.ChiqimlikMod.objects.select_related('currency').all())

        # Фильтр для DriverSalary (поле paid_at)
        salary_filter = {}
        if date_from:
            salary_filter['paid_at__gte'] = date_from
        if date_to:
            salary_filter['paid_at__lte'] = date_to

        salaries_usd = 0
        salaries = models.DriverSalary.objects.filter(**salary_filter).values('currency__currency').annotate(total=Sum('amount'))
        for item in salaries:
            curr = item['currency__currency']
            amount = float(item['total'] or 0)
            rate = rates.get(curr)
            if curr == 'USD':
                salaries_usd += amount
            elif rate:
                salaries_usd += (amount * rate) / usd_rate

        total_expenses_usd = dp_prices + salaries_usd
        final_balance_usd = total_in_usd - total_expenses_usd

        return Response({
            "cashbox": {
                **currency_totals,
                "total_in_usd": round(total_in_usd, 2)
            },
            "expenses": {
                "dp_price_usd": round(dp_prices, 2),
                "salaries_usd": round(salaries_usd, 2),
                "total_expenses_usd": round(total_expenses_usd, 2)
            },
            "final_balance_usd": round(final_balance_usd, 2)
        })
    @docs.casa_client_debt_doc
    @action(detail=False, methods=['get'], url_path='client-debt')
    def client_debt(self, request):
        from collections import defaultdict
        client_id = request.query_params.get('client_id')
        if not client_id:
            return Response({'error': 'client_id is required'}, status=400)

        client = models.ClientsMod.objects.filter(id=client_id).first()
        if not client:
            return Response({"error": "Клиент не найден"}, status=404)

        confirmed_tx = models.CashTransactionHistory.objects.filter(
            client=client,
            status='confirmed'
        )

        paid_by_currency = defaultdict(float)
        total_paid_usd = 0

        for tx in confirmed_tx:
            paid_by_currency[tx.currency] += tx.amount
            total_paid_usd += to_usd(tx.amount, tx.currency)

        expected_usd = get_client_total_expected_usd(client)
        remaining_usd = max(expected_usd - total_paid_usd, 0)

        return Response({
            "client_id": client_id,
            "paid": {
                **paid_by_currency,
                "total_usd": round(total_paid_usd, 2)
            },
            "expected_usd": round(expected_usd, 2),
            "remaining_debt_usd": round(remaining_usd, 2)
        })
    @docs.casa_client_debt_all_doc
    @action(detail=False, methods=['get'], url_path='all-debts')
    def all_clients_debts(self, request):
        result = []

        # 1) клиенты с хотя бы одной подтверждённой записью долга
        debt_clients = models.ClientsMod.objects.filter(
            cashtransactionhistory__is_debt=True,
            cashtransactionhistory__status='confirmed'
        ).distinct()

        for client in debt_clients:
            # 2) сумма всех долгов клиента (expected) по всем is_debt=True
            total_expected_usd = (
                models.CashTransactionHistory.objects
                .filter(client=client, status='confirmed', is_debt=True)
                .aggregate(total=Sum('total_expected_amount'))['total']
                or Decimal('0')
            )

            # 3) сумма всех подтверждённых платежей
            total_paid_usd = (
                models.CashTransactionHistory.objects
                .filter(client=client, status='confirmed')
                .aggregate(total=Sum('amount_in_usd'))['total']
                or Decimal('0')
            )

            # 4) итоговая задолженность
            remaining_usd = total_expected_usd - total_paid_usd
            if remaining_usd < 0:
                remaining_usd = Decimal('0')

            result.append({
                "client_id": client.id,
                "fullname": f'{client.last_name} {client.first_name}',
                'client_company':client.company,
                "expected_usd": float(total_expected_usd.quantize(Decimal('0.01'))),
                "paid_usd":     float(total_paid_usd.quantize(Decimal('0.01'))),
                "remaining_usd":float(remaining_usd.quantize(Decimal('0.01'))),
            })

        return Response(result)
    @docs.casa_confirm_doc
    @action(detail=True, methods=['patch'], url_path='confirm')
    def confirm_transaction(self, request, pk=None):
        transaction = self.get_object()
        serializer = rest_api.ConfirmCashTransactionSerializer(
            transaction, data=request.data, context={'request': request}, partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({'message': '✅ Транзакция подтверждена и перемещена в историю.'}, status=status.HTTP_200_OK)

class CashierHistoryViewSet(viewsets.ModelViewSet):
    permission_classes = [IsCashierOrAdmin]
    queryset = models.CashTransactionHistory.objects.select_related(
        'client', 'rays', 'rays_history', 'product', 'driver', 'currency', 'payment_way', 'cashier'
    ).all()
    serializer_class = rest_api.CashTransactionHistorySerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]

class FromLocationViewSet(viewsets.ModelViewSet):
    def get_permissions(self):
        if self.action in ['list', 'retrieve']:
            permission_classes = [permissions.IsAuthenticated]
        else:
            permission_classes = [IsOwnerOrCEO]
        return [permission() for permission in permission_classes]

    queryset = models.FromLocation.objects.all()
    serializer_class = rest_api.FromLocationSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]

class ToLocationViewSet(viewsets.ModelViewSet):
    def get_permissions(self):
        if self.action in ['list', 'retrieve']:
            permission_classes = [permissions.IsAuthenticated]
        else:
            permission_classes = [IsOwnerOrCEO]
        return [permission() for permission in permission_classes]

    queryset = models.ToLocation.objects.all()
    serializer_class = rest_api.ToLocationSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]

class CarActiveDetailViewSet(ViewSet):
    @swagger_auto_schema(
        operation_summary="🔍 Получить активную информацию по машине",
        operation_description="""
    Возвращает текущую информацию по машине с учётом активного рейса.  
    В ответе будут данные по водителю, затратам (чек, референс, заявка, оплат, баллон, тех.обслуживание) и их суммарные значения.
    """,
        responses={200: openapi.Response(description="Успешный ответ с данными по машине и затратам"),
                404: openapi.Response(description="Машина не найдена или не в активном рейсе")}
    )
    def retrieve(self, request, pk=None):
        try:
            car = models.CarsMod.objects.get(pk=pk)
        except models.CarsMod.DoesNotExist:
            return Response({"error": "🚫 Машина не найдена"}, status=404)
        rays = models.RaysMod.objects.filter(car=car).order_by('-created_at').first()
        if not rays:
            return Response({"error": "🚫 Машина не в активном рейсе"}, status=404)
        driver = rays.driver
        furgon = rays.fourgon
        start_time = rays.created_at
        chiqimliklar = models.ChiqimlikMod.objects.filter(driver=driver, created_at__gte=start_time)
        referenslar = models.ReferensMod.objects.filter(driver=driver, created_at__gte=start_time)
        arizalar = models.ArizaMod.objects.filter(driver=driver, created_at__gte=start_time)
        optollar = models.OptolMod.objects.filter(car=car, created_at__gte=start_time)
        balonlar = models.BalonMod.objects.filter(car=car, created_at__gte=start_time)
        balonfurgon = models.BalonFurgon.objects.filter(furgon=furgon, created_at__gte=start_time)
        texniklar = models.Texnics.objects.filter(car=car)
        
        total_chiqim_usd = sum(to_usd(x.price, x.currency) for x in chiqimliklar)
        total_optol_usd = sum(to_usd(x.price, x.currency) for x in optollar)
        total_balon_usd = sum(to_usd(x.price, x.currency) for x in balonlar)
        total_balonfurgon_usd = sum(to_usd(x.price, x.currency) for x in balonfurgon)
        total_service_usd = sum(to_usd(x.price, x.currency) for x in texniklar)

        total_expense_usd = (
            total_chiqim_usd + total_optol_usd + total_balon_usd +
            total_balonfurgon_usd + total_service_usd
        )
        response_data = {
            "driver": CustomUserSerializer(driver).data,
            "rays_id": rays.id,
            "start_time": start_time,
            "chiqimliklar": rest_api.ChiqimlikSerializer(chiqimliklar, many=True).data,
            "referenslar": rest_api.ReferensSerializer(referenslar, many=True).data,
            "arizalar": rest_api.ArizaSerializer(arizalar, many=True).data,     
            "total_expense_usd": round(total_expense_usd, 2),
            "details_expense_usd": {
                "chiqimlik": round(total_chiqim_usd, 2),
                "optol": round(total_optol_usd, 2),
                "balon": round(total_balon_usd, 2),
                "balonfurgon": round(total_balonfurgon_usd, 2),
                "service": round(total_service_usd, 2)
            }
        }
        return Response(response_data)

    @swagger_auto_schema(
        operation_summary="📋 Список всех активных машин с рейсами",
        operation_description="""
    Возвращает список всех машин, участвующих в активных рейсах.  
    Каждая машина содержит данные по водителю, затратам, началу рейса и деталям затрат.
    """,
        responses={200: openapi.Response(description="Успешный ответ со списком машин")}
    )
    def list(self, request):
        active_rays = models.RaysMod.objects.select_related('driver', 'car', 'fourgon')\
            .filter(is_completed=False, car__isnull=False)
        
        if not active_rays:
            return Response([])

        # Collect drivers and cars to bulk fetch expenses
        driver_ids = [r.driver_id for r in active_rays if r.driver_id]
        car_ids = [r.car_id for r in active_rays if r.car_id]
        furgon_ids = [r.fourgon_id for r in active_rays if r.fourgon_id]
        
        # Min start time to limit bulk fetch
        min_start = min(r.created_at for r in active_rays)

        # Bulk fetch all expense types
        chiqimliklar_all = list(models.ChiqimlikMod.objects.filter(driver_id__in=driver_ids, created_at__gte=min_start).select_related('currency', 'chiqimlar', 'driver'))
        referenslar_all = list(models.ReferensMod.objects.filter(driver_id__in=driver_ids, created_at__gte=min_start).select_related('currency', 'driver'))
        arizalar_all = list(models.ArizaMod.objects.filter(driver_id__in=driver_ids, created_at__gte=min_start).select_related('currency', 'driver'))
        optollar_all = list(models.OptolMod.objects.filter(car_id__in=car_ids, created_at__gte=min_start).select_related('currency', 'car'))
        balonlar_all = list(models.BalonMod.objects.filter(car_id__in=car_ids, created_at__gte=min_start).select_related('currency', 'car'))
        balonfurgon_all = list(models.BalonFurgon.objects.filter(furgon_id__in=furgon_ids, created_at__gte=min_start).select_related('currency', 'furgon'))
        texniklar_all = list(models.Texnics.objects.filter(car_id__in=car_ids).select_related('currency', 'car'))

        result = []
        for rays in active_rays:
            car = rays.car
            furgon = rays.fourgon
            driver = rays.driver
            start_time = rays.created_at

            # Filter in-memory
            c_list = [x for x in chiqimliklar_all if x.driver_id == rays.driver_id and x.created_at >= start_time]
            r_list = [x for x in referenslar_all if x.driver_id == rays.driver_id and x.created_at >= start_time]
            a_list = [x for x in arizalar_all if x.driver_id == rays.driver_id and x.created_at >= start_time]
            o_list = [x for x in optollar_all if x.car_id == rays.car_id and x.created_at >= start_time]
            b_list = [x for x in balonlar_all if x.car_id == rays.car_id and x.created_at >= start_time]
            bf_list = [x for x in balonfurgon_all if x.furgon_id == rays.fourgon_id and x.created_at >= start_time]
            t_list = [x for x in texniklar_all if x.car_id == rays.car_id]

            total_chiqim_usd = sum(to_usd(x.price, x.currency) for x in c_list)
            total_optol_usd = sum(to_usd(x.price, x.currency) for x in o_list)
            total_balon_usd = sum(to_usd(x.price, x.currency) for x in b_list)
            total_balonfurgon_usd = sum(to_usd(x.price, x.currency) for x in bf_list)
            total_service_usd = sum(to_usd(x.price, x.currency) for x in t_list)

            total_expense_usd = (
                total_chiqim_usd + total_optol_usd + total_balon_usd +
                total_balonfurgon_usd + total_service_usd
            )
            result.append({
                "car_id": car.id,
                "car_name": car.name,
                "driver": CustomUserSerializer(driver).data,
                "rays_id": rays.id,
                "start_time": start_time,
                "chiqimliklar": rest_api.ChiqimlikSerializer(c_list, many=True).data,
                "referenslar": rest_api.ReferensSerializer(r_list, many=True).data,
                "arizalar": rest_api.ArizaSerializer(a_list, many=True).data,
                "total_expense_usd": round(total_expense_usd, 2),
                "details_expense_usd": {
                    "chiqimlik": round(total_chiqim_usd, 2),
                    "optol": round(total_optol_usd, 2),
                    "balon": round(total_balon_usd, 2),
                    "balonfurgon": round(total_balonfurgon_usd, 2),
                    "service": round(total_service_usd, 2)
                }
            })
        return Response(result)

class CarFullHistoryViewSet(ViewSet):
    @swagger_auto_schema(
        operation_summary="🔍 Получить информацию по машине",
        operation_description="""
    Возвращает текущую информацию по машине.  
    В ответе будут данные по водителю, затратам (чек, референс, заявка, оплат, баллон, тех.обслуживание) и их суммарные значения.
    """,
        responses={200: openapi.Response(description="Успешный ответ с данными по машине и затратам"),
                404: openapi.Response(description="Машина не найдена")}
    )
    def retrieve(self, request, pk=None):
        try:
            car = models.CarsMod.objects.get(pk=pk)
        except models.CarsMod.DoesNotExist:
            return Response({"error": "🚫 Машина не найдена"}, status=404)
        rays = models.RaysMod.objects.filter(car=car).order_by('-created_at').first()
        history = models.RaysHistoryMod.objects.filter(car=car).order_by('-created_at').first()
        driver = rays.driver if rays else (history.driver if history else None)
        if not driver:
            return Response({"error": "🚫 Водитель не найден для этой машины"}, status=404)
        chiqimliklar = models.ChiqimlikMod.objects.filter(driver=driver)
        referenslar = models.ReferensMod.objects.filter(driver=driver)
        arizalar = models.ArizaMod.objects.filter(driver=driver)
        optollar = models.OptolMod.objects.filter(car=car)
        balonlar = models.BalonMod.objects.filter(car=car)
        texniklar = models.Texnics.objects.filter(car=car)
        total_chiqim = chiqimliklar.aggregate(total=Sum('price'))['total'] or 0
        total_optol = optollar.aggregate(total=Sum('price'))['total'] or 0
        total_balon = balonlar.aggregate(total=Sum('price'))['total'] or 0
        total_service = texniklar.aggregate(total=Sum('price'))['total'] or 0
        total_expense = total_chiqim + total_optol + total_balon + total_service
        serializer = rest_api.CarDetailsSerializer({
            'car': car,
            'chiqimliklar': chiqimliklar,
            'referenslar': referenslar,
            'arizalar': arizalar,
            'optollar': optollar,
            'balonlar': balonlar,
            'texniklar': texniklar
        })
        return Response({
            **serializer.data,
            "total_expense": total_expense,
            "details_expense": {
                "chiqimlik": total_chiqim,
                "optol": total_optol,
                "balon": total_balon,
                "service": total_service
            }
        })
    @swagger_auto_schema(
        operation_summary="📋 Список всех машин с рейсами",
        operation_description="""
    Возвращает список всех машин.  
    Каждая машина содержит данные по водителю, затратам.
    """,
        responses={200: openapi.Response(description="Успешный ответ со списком машин")}
    )
    def list(self, request):
        car_ids = models.RaysHistoryMod.objects.exclude(car=None).values_list("car_id", flat=True).distinct()
        result = []
        for car_id in car_ids:
            try:
                car = models.CarsMod.objects.get(id=car_id)
            except models.CarsMod.DoesNotExist:
                continue
            history = models.RaysHistoryMod.objects.filter(car=car).order_by('-created_at').first()
            driver = history.driver if history else None
            if not driver:
                continue
            chiqimliklar = models.ChiqimlikMod.objects.filter(driver=driver)
            referenslar = models.ReferensMod.objects.filter(driver=driver)
            arizalar = models.ArizaMod.objects.filter(driver=driver)
            optollar = models.OptolMod.objects.filter(car=car)
            balonlar = models.BalonMod.objects.filter(car=car)
            texniklar = models.Texnics.objects.filter(car=car)
            total_chiqim = chiqimliklar.aggregate(total=Sum('price'))['total'] or 0
            total_optol = optollar.aggregate(total=Sum('price'))['total'] or 0
            total_balon = balonlar.aggregate(total=Sum('price'))['total'] or 0
            total_service = texniklar.aggregate(total=Sum('price'))['total'] or 0
            total_expense = total_chiqim + total_optol + total_balon + total_service
            serializer = rest_api.CarDetailsSerializer({
                'car': car,
                'chiqimliklar': chiqimliklar,
                'referenslar': referenslar,
                'arizalar': arizalar,
                'optollar': optollar,
                'balonlar': balonlar,
                'texniklar': texniklar
            })
            result.append({
                **serializer.data,
                "total_expense": total_expense,
                "details_expense": {
                    "chiqimlik": total_chiqim,
                    "optol": total_optol,
                    "balon": total_balon,
                    "service": total_service
                }
            })
        return Response(result)

class CustomTokenObtainPairView(TokenObtainPairView):
    permission_classes = (AllowAny,)
class CustomTokenRefreshView(TokenRefreshView):
    permission_classes = (AllowAny,)

class AuthViewSet(viewsets.ViewSet):
    permission_classes = [AllowAny]
    @swagger_auto_schema(
        method='post',
        operation_summary="🔐 Логин",
        operation_description="Вход по имени пользователя и паролю. Возвращает access и refresh токены.",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            required=['username', 'password'],
            properties={
                'username': openapi.Schema(type=openapi.TYPE_STRING),
                'password': openapi.Schema(type=openapi.TYPE_STRING)
            }
        ),
        responses={200: "OK", 401: "Неверные учетные данные"}
    )
    @action(detail=False, methods=['post'], url_path='login')
    def login(self, request):
        username = request.data.get("username")
        password = request.data.get("password")

        if not username or not password:
            return Response({"error": "Необходимо указать имя пользователя и пароль"}, status=status.HTTP_400_BAD_REQUEST)

        user = authenticate(username=username, password=password)

        if user is None:
            return Response({"error": "Неверные учетные данные"}, status=status.HTTP_401_UNAUTHORIZED)

        # 🔥 Проверка: если водитель, то только с активным рейсом
        if user.status == 'driver':
            has_active_rays = models.RaysMod.objects.filter(driver=user, is_completed=False).exists()
            if not has_active_rays:
                return Response({"error": "⛔ У вас нет активного рейса. Вход запрещен."}, status=status.HTTP_403_FORBIDDEN)

        refresh = RefreshToken.for_user(user)
        return Response({
            "refresh": str(refresh),
            "access": str(refresh.access_token),
            "user": {
                "id": user.id,
                "username": user.username,
                "fullname": user.fullname,
                "phone_number": user.phone_number,
                "status": user.status
            }
        })

    @action(detail=False, methods=['get'], url_path='me', permission_classes=[permissions.IsAuthenticated])
    def me(self, request):
        user = request.user
        return Response({
            "id": user.id,
            "username": user.username,
            "fullname": getattr(user, 'fullname', ''),
            "phone_number": getattr(user, 'phone_number', ''),
            "status": getattr(user, 'status', ''),
            "photo": user.photo.url if getattr(user, 'photo', None) else None,
        })

    @swagger_auto_schema(
        method='post',
        operation_summary="📝 Регистрация",
        operation_description="Регистрация нового пользователя",
        request_body=rest_api.CustomUserSerializer,
        responses={201: "Пользователь зарегистрирован"}
    )
    @action(detail=False, methods=['post'], url_path='register')
    def register(self, request):
        serializer = rest_api.CustomUserSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        refresh = RefreshToken.for_user(user)
        return Response({
            "refresh": str(refresh),
            "access": str(refresh.access_token),
            "user": serializer.data
        }, status=status.HTTP_201_CREATED)
    
class RaysHistoryActionsViewSet(ViewSet):
    @swagger_auto_schema(
        method='get',
        operation_summary="Rays Restore",
        operation_description="Use /rayshistory-actions/<id>/restore/ — Получить статус восстановление рейса"
    )
    @swagger_auto_schema(
        method='post',
        operation_summary="Rays Restore",
        operation_description="Use /rayshistory-actions/<id>/restore/ — восстановление рейса"
    )
    @action(detail=True, methods=['post', 'get'], url_path='restore')
    def restore_rays(self, request, pk=None):
        try:
            history = models.RaysHistoryMod.objects.get(pk=pk)
        except models.RaysHistoryMod.DoesNotExist:
            return Response({"error": "❌ Рейс не найден в истории"}, status=status.HTTP_404_NOT_FOUND)

        if not history.can_restore():
            return Response({"error": "⛔ Восстановление невозможно — прошло более 2 дней."}, status=status.HTTP_400_BAD_REQUEST)

        # создаём новый рейс
        restored = models.RaysMod.objects.create(
            id=history.rays_id,
            country=history.country,
            driver=history.driver,
            car=history.car,
            fourgon=history.fourgon,
            price=history.price,
            dr_price=history.dr_price,
            dp_price=history.dp_price,
            kilometer=history.kilometer,
            dp_information=history.dp_information,
            count=history.count,
            is_completed=False,
        )
        restored.client.set(history.client.all())

        # обновляем продукты ДО удаления истории
        products = models.Product.objects.filter(rays_history=history)
        for product in products:
            product.rays = restored
            product.rays_history = None
            product.is_delivered = False  # 👈 Сбрасываем доставку обратно
            product.save()

        # обновляем транзакции
        models.CashTransactionHistory.objects.filter(rays__id=history.id).update(rays=restored)

        # удаляем историю
        history.delete()

        return Response({"success": f"✅ Рейс успешно восстановлен с ID {restored.id}"})
    @swagger_auto_schema(operayion_summary="Rays Restore", operation_description="Use /rayshistory-actions/<id>/restore/ — Получить статус восстановление рейса")
    def list(self, request):  # 👈 вот это обязательно
        return Response({"message": "Use /rayshistory-actions/<id>/restore/ to restore a ray"})
class RaysExportViewSet(ViewSet):
    @swagger_auto_schema(
        method='get',
        operation_summary="Export to Excel",
        operation_description="Use /rays-export/export/\nUse /rays-export/export/?period=week|month|year\nUse /rays-export/export/?from=YYYY-MM-DD&to=YYYY-MM-DD"
    )
    @action(detail=False, methods=['get'], url_path='export')
    def export_excel(self, request):
        period = request.query_params.get("period")
        from_date = request.query_params.get("from")
        to_date = request.query_params.get("to")
        queryset = models.RaysHistoryMod.objects.select_related(
            "country", "driver", "car", "fourgon"
        ).prefetch_related("client").all()
        today = now().date()
        if period == "week":
            queryset = queryset.filter(created_at__date__gte=today - timedelta(days=7))
        elif period == "month":
            queryset = queryset.filter(created_at__date__gte=today.replace(day=1))
        elif period == "year":
            queryset = queryset.filter(created_at__date__year=today.year)
        elif from_date and to_date:
            try:
                from_dt = datetime.strptime(from_date, "%Y-%m-%d").date()
                to_dt = datetime.strptime(to_date, "%Y-%m-%d").date()
                queryset = queryset.filter(created_at__date__range=(from_dt, to_dt))
            except ValueError:
                return Response({"error": "❌ Неверный формат даты. Используйте YYYY-MM-DD"}, status=400)
        wb = Workbook()
        ws = wb.active
        ws.title = "Rays Data"
        headers = [
            "Дата", "Страна", "Водитель", "Клиенты", "Машина", "Фургон",
            "Цена", "Цена Водителя", "Цена Диспетчера",
            "Километры", "Информация", "Количество товара"
        ]
        ws.append(headers)
        for obj in queryset:
            clients = ", ".join([f"{c.first_name} {c.last_name}" for c in obj.client.all()])
            ws.append([
                obj.created_at.strftime("%Y-%m-%d"),
                obj.country.name if obj.country else "",
                obj.driver.fullname if obj.driver else "",
                clients,
                obj.car.name if obj.car else "",
                obj.fourgon.name if obj.fourgon else "",
                obj.price,
                obj.dr_price,
                obj.dp_price,
                obj.kilometer,
                obj.dp_information,
                obj.count,
            ])
        response = HttpResponse(content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        filename = f"rays_export_{now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        wb.save(response)
        return response
    @swagger_auto_schema(
            operation_summary="📋 Получить список экспортов",
            operation_description="Возвращает список всех экспортов.",
            responses={200: openapi.Response("OK")}
    )
    def list(self, request):  # 👈 вот это обязательно
        return Response({"message": "Use /rays-export/export/?period=week or ?from=...&to=..."})
class CountryViewSet(viewsets.ModelViewSet):
    def get_permissions(self):
        if self.action in ['list', 'retrieve']:
            permission_classes = [permissions.IsAuthenticated]
        else:
            permission_classes = [IsOwnerOrCEO]
        return [permission() for permission in permission_classes]

    queryset = models.CountryMod.objects.all()
    serializer_class = rest_api.CountrySerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    @swagger_auto_schema(
        operation_summary="📋 Получить список стран",
        operation_description="Возвращает список всех стран.",
        responses={200: openapi.Response("OK")}
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @swagger_auto_schema(
        operation_summary="➕ Добавить новую страну",
        operation_description="Создает новую страну по переданным данным.",
        responses={201: openapi.Response("Создано")}
    )
    def create(self, request, *args, **kwargs):
        return super().create(request, *args, **kwargs)

    @swagger_auto_schema(
        operation_summary="🔍 Получить страну по ID",
        operation_description="Возвращает данные страны по её ID.",
        responses={200: openapi.Response("OK"), 404: openapi.Response("Не найдено")}
    )
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)

    @swagger_auto_schema(
        operation_summary="✏️ Обновить данные страны полностью",
        operation_description="Полностью обновляет данные страны по ID.",
        responses={200: openapi.Response("Обновлено"), 400: openapi.Response("Ошибка запроса")}
    )
    def update(self, request, *args, **kwargs):
        return super().update(request, *args, **kwargs)

    @swagger_auto_schema(
        operation_summary="🔧 Частичное обновление страны",
        operation_description="Обновляет отдельные поля страны по ID.",
        responses={200: openapi.Response("Обновлено"), 400: openapi.Response("Ошибка запроса")}
    )
    def partial_update(self, request, *args, **kwargs):
        return super().partial_update(request, *args, **kwargs)

    @swagger_auto_schema(
        operation_summary="🗑️ Удалить страну",
        operation_description="Удаляет страну по её ID.",
        responses={204: openapi.Response("Удалено"), 404: openapi.Response("Не найдено")}
    )
    def destroy(self, request, *args, **kwargs):
        return super().destroy(request, *args, **kwargs)

class ServiceViewSet(viewsets.ModelViewSet):
    def get_permissions(self):
        if self.action in ['list', 'retrieve']:
            permission_classes = [permissions.IsAuthenticated]
        else:
            permission_classes = [IsZaphosOrAdmin]
        return [permission() for permission in permission_classes]

    queryset = models.Service.objects.all()
    serializer_class = rest_api.ServiceSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    @swagger_auto_schema(
        operation_summary="📋 Список сервисов",
        operation_description="Получить список всех сервисных операций."
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @swagger_auto_schema(
        operation_summary="➕ Добавить сервис",
        operation_description="Создание новой записи обслуживания (service)."
    )
    def create(self, request, *args, **kwargs):
        return super().create(request, *args, **kwargs)

    @swagger_auto_schema(
        operation_summary="🔍 Получить сервис по ID",
        operation_description="Получить полную информацию по записи обслуживания."
    )
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)

    @swagger_auto_schema(
        operation_summary="✏️ Обновить сервис",
        operation_description="Полное обновление записи обслуживания."
    )
    def update(self, request, *args, **kwargs):
        return super().update(request, *args, **kwargs)

    @swagger_auto_schema(
        operation_summary="🔧 Частичное обновление сервиса",
        operation_description="Обновление только указанных полей обслуживания."
    )
    def partial_update(self, request, *args, **kwargs):
        return super().partial_update(request, *args, **kwargs)

    @swagger_auto_schema(
        operation_summary="🗑️ Удалить сервис",
        operation_description="Удалить запись обслуживания по ID."
    )
    def destroy(self, request, *args, **kwargs):
        return super().destroy(request, *args, **kwargs)
    @swagger_auto_schema(
        method='get',
        operation_summary="💸 Общая сумма расходов",
        operation_description="Возвращает сумму всех расходов (texnic, balon, chiqimlik, optol). Можно фильтровать по дате с параметрами `start` и `end` в формате YYYY-MM-DD."
    )
    @action(detail=False, methods=['get'], url_path='totals')
    def get_totals(self, request):
        rates = {rate.currency: float(rate.rate_to_uzs) for rate in models.CurrencyRate.objects.all()}
        usd_rate = rates.get('USD', 1) or 1

        # Функция перевода в USD
        def to_usd(amount, currency, rates, usd_rate):
            if currency == 'USD':
                return float(amount)
            elif currency == 'UZS':
                return float(amount) / usd_rate
            elif currency in rates:
                return (float(amount) * rates[currency]) / usd_rate
            return 0

        texnic_qs = models.Texnics.objects.select_related('currency').all()
        balon_qs = models.BalonMod.objects.select_related('currency').all()
        balonfurgon_qs = models.BalonFurgon.objects.select_related('currency').all()
        chiqimlik_qs = models.ChiqimlikMod.objects.select_related('currency').all()
        optol_qs = models.OptolMod.objects.select_related('currency').all()
        driversalary_qs = models.DriverSalary.objects.select_related('currency').all()
        
        # Prefetch categories for chiqimliklar to avoid N+1 in serializer later if needed
        # chiqimlik_qs = chiqimlik_qs.select_related('chiqimlar')

        texnic_total = sum(to_usd(x.price, getattr(x.currency, 'currency', 'USD'), rates, usd_rate) for x in texnic_qs)
        balon_total = sum(to_usd(x.price, getattr(x.currency, 'currency', 'USD'), rates, usd_rate) for x in balon_qs)
        balonfurgon_total = sum(to_usd(x.price, getattr(x.currency, 'currency', 'USD'), rates, usd_rate) for x in balonfurgon_qs)
        chiqimlik_total = sum(to_usd(x.price, getattr(x.currency, 'currency', 'USD'), rates, usd_rate) for x in chiqimlik_qs)
        optol_total = sum(to_usd(x.price, getattr(x.currency, 'currency', 'USD'), rates, usd_rate) for x in optol_qs)
        driversalary_total = sum(to_usd(x.amount, getattr(x.currency, 'currency', 'USD'), rates, usd_rate) for x in driversalary_qs)  # 👈 добавляем расчет

        total = texnic_total + balon_total + balonfurgon_total + chiqimlik_total + optol_total + driversalary_total

        return Response({
            'texnic': rest_api.TexSerializer(texnic_qs, many=True).data,
            'balon': rest_api.BalonSerializer(balon_qs, many=True).data,
            'balonfurgon': rest_api.BolonFurgonSerializer(balonfurgon_qs, many=True).data,
            'chiqimlik': rest_api.ChiqimlikSerializer(chiqimlik_qs, many=True).data,
            'optol': rest_api.OptolSerializer(optol_qs, many=True).data,
            'driversalary': rest_api.DriverSerializer(driversalary_qs, many=True).data,  # 👈 сериализация DriverSalary
            'totals': {
                'texnic': round(texnic_total, 2),
                'balon': round(balon_total, 2),
                'balonfurgon': round(balonfurgon_total, 2),
                'chiqimlik': round(chiqimlik_total, 2),
                'optol': round(optol_total, 2),
                'driversalary': round(driversalary_total, 2),  # 👈 добавляем total
                'total': round(total, 2)
            }
        })
    @swagger_auto_schema(
        method='get',
        operation_summary="💸 Общая сумма расходов в перемешку",
        operation_description="Возвращает сумму всех расходов (texnic, balon, chiqimlik, optol). Можно фильтровать по дате с параметрами `start` и `end` в формате YYYY-MM-DD."
    )
    @action(detail=False, methods=['get'], url_path='totals-date')
    def get_totals_by_date(self, request):
        start = request.query_params.get('start')
        end = request.query_params.get('end')

        start_date = parse_date(start) if start else None
        end_date = parse_date(end) if end else None

        rates = {r.currency: float(r.rate_to_uzs) for r in models.CurrencyRate.objects.all()}
        usd_rate = rates.get('USD', 1) or 1

        def apply_date_filter(qs, field='created_at'):
            if start_date and end_date:
                return qs.filter(**{f"{field}__range": (start_date, end_date)})
            return qs

        result = []

        texnic_items = apply_date_filter(models.Texnics.objects.select_related('currency', 'car').all())
        balon_items = apply_date_filter(models.BalonMod.objects.select_related('currency', 'car').all())
        balonfurgon_items = apply_date_filter(models.BalonFurgon.objects.select_related('currency', 'furgon').all())
        optol_items = apply_date_filter(models.OptolMod.objects.select_related('currency', 'car').all())
        chiqimlik_items = apply_date_filter(models.ChiqimlikMod.objects.select_related('currency', 'driver', 'chiqimlar').all())

        texnic_total = 0
        balon_total = 0
        balon_furgon_total = 0
        optol_total = 0
        chiqimlik_total = 0

        for item in texnic_items:
            if item.car:
                usd_value = to_usd(item.price, item.currency)
                texnic_total += usd_value
                result.append({
                    "type": "Техобслуживание",
                    "price": item.price,
                    "currency": item.currency.currency if item.currency else None,
                    "usd_value": round(usd_value, 2),
                    "car": item.car.id,
                    "car_name": item.car.name,
                    'kilometer': item.kilometer,
                    'created_at': item.created_at
                })

        for item in apply_date_filter(models.BalonMod.objects.all()):
            if item.car:
                usd_value = to_usd(item.price, item.currency)
                balon_total += usd_value
                result.append({
                    "type": "Баллон (Машина)",
                    "price": item.price,
                    "currency": item.currency.currency if item.currency else None,
                    "usd_value": round(usd_value, 2),
                    "car": item.car.id,
                    "car_name": item.car.name,
                    'count': item.count,
                    'kilometr': item.kilometr,
                    'created_at': item.created_at
                })

        for item in apply_date_filter(models.BalonFurgon.objects.all()):
            if item.furgon:
                usd_value = to_usd(item.price, item.currency)
                balon_furgon_total += usd_value
                result.append({
                    "type": "Баллон (Фургон)",
                    "price": item.price,
                    "currency": item.currency.currency if item.currency else None,
                    "usd_value": round(usd_value, 2),
                    "furgon": item.furgon.id,
                    "furgon_name": item.furgon.name,
                    'count': item.count,
                    'kilometr': item.kilometr,
                    'created_at': item.created_at
                })

        for item in apply_date_filter(models.OptolMod.objects.all()):
            if item.car:
                usd_value = to_usd(item.price, item.currency)
                optol_total += usd_value
                result.append({
                    "type": "Оптол",
                    "price": item.price,
                    "currency": item.currency.currency if item.currency else None,
                    "usd_value": round(usd_value, 2),
                    "car": item.car.id,
                    "car_name": item.car.name,
                    'kilometr': item.kilometr,
                    'created_at': item.created_at
                })

        for item in chiqimlik_items:
            usd_value = to_usd(item.price, item.currency)
            chiqimlik_total += usd_value
            result.append({
                "type": f"Чеки: {item.chiqimlar.name if item.chiqimlar else 'Без категории'}",
                "price": item.price,
                "currency": item.currency.currency if item.currency else None,
                "usd_value": round(usd_value, 2),
                "driver": item.driver.id if item.driver else None,
                "driver_name": item.driver.fullname if item.driver else None,
                'description': item.description,
                'created_at': item.created_at
            })

        return Response({
            "data": result,
            "totals": {
                "texnic": round(texnic_total, 2),
                "balon": round(balon_total, 2),
                "balon_furgon": round(balon_furgon_total, 2),
                "optol": round(optol_total, 2),
                "chiqimlik": round(chiqimlik_total, 2),
                "total": round(
                    texnic_total + balon_total + balon_furgon_total + optol_total + chiqimlik_total, 2
                )
            }
        })

class HistoryViewSet(ViewSet):
    @swagger_auto_schema(
        method='get',
        operation_summary="Car history full",
        operation_description="Use /history/{id}/car-history/"
    )
    @action(detail=True, methods=['get'], url_path='car-history')
    def car_history(self, request, pk=None):
        try:
            car = models.CarsMod.objects.get(pk=pk)
        except models.CarsMod.DoesNotExist:
            return Response({"error": "🚫 Машина не найдена"}, status=404)

        history = models.RaysHistoryMod.objects.filter(car=car)
        bolon = models.BalonMod.objects.filter(car=car)
        optol = models.OptolMod.objects.filter(car=car)
        texnic = models.Texnics.objects.filter(car=car)
        rays_data = rest_api.SimpleRaysHistorySerializer(history, many=True).data

        bolon_price_usd = sum(to_usd(x.price, x.currency) for x in bolon)
        optol_price_usd = sum(to_usd(x.price, x.currency) for x in optol)
        textic_price_usd = sum(to_usd(x.price, x.currency) for x in texnic)
        total_usd = bolon_price_usd + optol_price_usd + textic_price_usd

        return Response({
            "car": rest_api.CarsSerializer(car).data,
            'texnic':rest_api.TexSerializer(texnic,many=True).data,
            'bolon':rest_api.BalonSerializer(bolon,many=True).data,
            'optol':rest_api.OptolSerializer(optol,many=True).data,
            "total_usd": round(total_usd, 2),
            "details_expense_usd": {
                "bolon": round(bolon_price_usd, 2),
                "optol": round(optol_price_usd, 2),
                "texnic": round(textic_price_usd, 2),
            },
            "rays_history": rays_data,
            "rays_count": history.count()
        })
    @swagger_auto_schema(
        method='get',
        operation_summary="Client history full",
        operation_description="Use /history/{id}/client-history/ "
    )
    @action(detail=True, methods=['get'], url_path='client-history')
    def client_history(self, request, pk=None):
        try:
            client = models.ClientsMod.objects.get(pk=pk)
        except models.ClientsMod.DoesNotExist:
            return Response({"error": "🚫 Клиент не найден"}, status=404)

        history = models.RaysHistoryMod.objects.filter(client=client)
        rays_data = rest_api.SimpleRaysHistorySerializer(history, many=True).data

        # Получаем все оплаты клиента
        transactions = models.CashTransactionHistory.objects.filter(client=client)
        total_by_currency = defaultdict(Decimal)
        total_paid_usd = Decimal('0.00')

        for t in transactions:
            total_by_currency[t.currency.currency] += t.amount
            try:
                # ✅ передаем объект currency, а не строку
                usd_value = to_usd(t.amount, t.currency)
                total_paid_usd += usd_value
            except Exception as e:
                # если курс не найден или другая ошибка
                continue

        return Response({
            "client": rest_api.ClientsSerializer(client).data,
            "rays_history": rays_data,
            "rays_count": history.count(),
            "total_paid": {k: float(v) for k, v in total_by_currency.items()},
            "total_paid_usd": round(float(total_paid_usd), 2)
        })
    @swagger_auto_schema(operation_summary="📘 Справка по истории", operation_description="Возвращает описание доступных методов: car-history, client-history")
    def list(self, request):  # Чтобы router отображал
        return Response({
            "message": "Используйте /history/<id>/car-history/ или /history/<id>/client-history/"
        })
class OptolViewSet(viewsets.ModelViewSet):
    permission_classes = [IsZaphosOrAdmin]
    queryset = models.OptolMod.objects.all()
    serializer_class = rest_api.OptolSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    @swagger_auto_schema(
        operation_summary="📋 Получить список optol",
        operation_description="Возвращает список всех optol.",
        responses={200: openapi.Response("OK")}
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @swagger_auto_schema(
        operation_summary="➕ Добавить новую optol",
        operation_description="Создает новую optol по переданным данным.",
        responses={201: openapi.Response("Создано")}
    )
    def create(self, request, *args, **kwargs):
        return super().create(request, *args, **kwargs)

    @swagger_auto_schema(
        operation_summary="🔍 Получить optol по ID",
        operation_description="Возвращает данные optol по её ID.",
        responses={200: openapi.Response("OK"), 404: openapi.Response("Не найдено")}
    )
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)

    @swagger_auto_schema(
        operation_summary="✏️ Обновить данные optol полностью",
        operation_description="Полностью обновляет данные optol по ID.",
        responses={200: openapi.Response("Обновлено"), 400: openapi.Response("Ошибка запроса")}
    )
    def update(self, request, *args, **kwargs):
        return super().update(request, *args, **kwargs)

    @swagger_auto_schema(
        operation_summary="🔧 Частичное обновление optol",
        operation_description="Обновляет отдельные поля optol по ID.",
        responses={200: openapi.Response("Обновлено"), 400: openapi.Response("Ошибка запроса")}
    )
    def partial_update(self, request, *args, **kwargs):
        return super().partial_update(request, *args, **kwargs)

    @swagger_auto_schema(
        operation_summary="🗑️ Удалить optol",
        operation_description="Удаляет optol по её ID.",
        responses={204: openapi.Response("Удалено"), 404: openapi.Response("Не найдено")}
    )
    def destroy(self, request, *args, **kwargs):
        return super().destroy(request, *args, **kwargs)

class BalonFurgonViewSet(viewsets.ModelViewSet):
    permission_classes = [IsZaphosOrAdmin]
    queryset = models.BalonFurgon.objects.all()
    serializer_class = rest_api.BolonFurgonSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    @swagger_auto_schema(
        operation_summary="📋 Получить список bolon for furgon",
        operation_description="Возвращает список всех bolon for furgon.",
        responses={200: openapi.Response("OK")}
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @swagger_auto_schema(
        operation_summary="➕ Добавить новую bolon for furgon",
        operation_description="Создает новую bolon for furgon по переданным данным.",
        responses={201: openapi.Response("Создано")}
    )
    def create(self, request, *args, **kwargs):
        return super().create(request, *args, **kwargs)

    @swagger_auto_schema(
        operation_summary="🔍 Получить bolon for furgon по ID",
        operation_description="Возвращает данные bolon for furgon по её ID.",
        responses={200: openapi.Response("OK"), 404: openapi.Response("Не найдено")}
    )
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)

    @swagger_auto_schema(
        operation_summary="✏️ Обновить данные bolon for furgon полностью",
        operation_description="Полностью обновляет данные bolon for furgon по ID.",
        responses={200: openapi.Response("Обновлено"), 400: openapi.Response("Ошибка запроса")}
    )
    def update(self, request, *args, **kwargs):
        return super().update(request, *args, **kwargs)

    @swagger_auto_schema(
        operation_summary="🔧 Частичное обновление bolon for furgon",
        operation_description="Обновляет отдельные поля bolon for furgon по ID.",
        responses={200: openapi.Response("Обновлено"), 400: openapi.Response("Ошибка запроса")}
    )
    def partial_update(self, request, *args, **kwargs):
        return super().partial_update(request, *args, **kwargs)

    @swagger_auto_schema(
        operation_summary="🗑️ Удалить bolon for furgon",
        operation_description="Удаляет bolon for furgon по её ID.",
        responses={204: openapi.Response("Удалено"), 404: openapi.Response("Не найдено")}
    )
    def destroy(self, request, *args, **kwargs):
        return super().destroy(request, *args, **kwargs)

class BalonViewSet(viewsets.ModelViewSet):
    permission_classes = [IsZaphosOrAdmin]
    queryset = models.BalonMod.objects.all()
    serializer_class = rest_api.BalonSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    @swagger_auto_schema(
        operation_summary="📋 Получить список bolon",
        operation_description="Возвращает список всех bolon.",
        responses={200: openapi.Response("OK")}
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @swagger_auto_schema(
        operation_summary="➕ Добавить новую bolon",
        operation_description="Создает новую bolon по переданным данным.",
        responses={201: openapi.Response("Создано")}
    )
    def create(self, request, *args, **kwargs):
        return super().create(request, *args, **kwargs)

    @swagger_auto_schema(
        operation_summary="🔍 Получить bolon по ID",
        operation_description="Возвращает данные bolon по её ID.",
        responses={200: openapi.Response("OK"), 404: openapi.Response("Не найдено")}
    )
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)

    @swagger_auto_schema(
        operation_summary="✏️ Обновить данные bolon полностью",
        operation_description="Полностью обновляет данные bolon по ID.",
        responses={200: openapi.Response("Обновлено"), 400: openapi.Response("Ошибка запроса")}
    )
    def update(self, request, *args, **kwargs):
        return super().update(request, *args, **kwargs)

    @swagger_auto_schema(
        operation_summary="🔧 Частичное обновление bolon",
        operation_description="Обновляет отдельные поля bolon по ID.",
        responses={200: openapi.Response("Обновлено"), 400: openapi.Response("Ошибка запроса")}
    )
    def partial_update(self, request, *args, **kwargs):
        return super().partial_update(request, *args, **kwargs)

    @swagger_auto_schema(
        operation_summary="🗑️ Удалить bolon",
        operation_description="Удаляет bolon по её ID.",
        responses={204: openapi.Response("Удалено"), 404: openapi.Response("Не найдено")}
    )
    def destroy(self, request, *args, **kwargs):
        return super().destroy(request, *args, **kwargs)

class TexViewSet(viewsets.ModelViewSet):
    permission_classes = [IsZaphosOrAdmin]
    queryset = models.Texnics.objects.all()
    serializer_class = rest_api.TexSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    @swagger_auto_schema(
        operation_summary="📋 Получить список всех тех. обслуживаний",
        operation_description="📄 Получить список всех тех. обслуживаний",
        responses={200: rest_api.TexSerializer(many=True)}
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @swagger_auto_schema(
        operation_summary="🔍 Получить информацию по одному Tex",
        operation_description="🔍 Получить информацию по одному Tex",
        responses={200: rest_api.TexSerializer()}
    )
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)

    @swagger_auto_schema(
        operation_summary="➕ Создать новое Tex",
        operation_description="➕ Создать новое Tex",
        request_body=rest_api.TexSerializer,
        responses={201: rest_api.TexSerializer()}
    )
    def create(self, request, *args, **kwargs):
        return super().create(request, *args, **kwargs)

    @swagger_auto_schema(
        operation_summary="✏️ Полностью обновить Tex",
        operation_description="✏️ Полностью обновить Tex",
        request_body=rest_api.TexSerializer,
        responses={200: rest_api.TexSerializer()}
    )
    def update(self, request, *args, **kwargs):
        return super().update(request, *args, **kwargs)

    @swagger_auto_schema(
        operation_summary="🧩 Частично обновить Tex",
        operation_description="🧩 Частично обновить Tex",
        request_body=rest_api.TexSerializer,
        responses={200: rest_api.TexSerializer()}
    )
    def partial_update(self, request, *args, **kwargs):
        return super().partial_update(request, *args, **kwargs)

    @swagger_auto_schema(
        operation_summary="🗑 Удалить Tex",
        operation_description="🗑 Удалить Tex",
        responses={204: 'Удалено успешно'}
    )
    def destroy(self, request, *args, **kwargs):
        return super().destroy(request, *args, **kwargs)
    
class RaysHistoryFullViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = models.RaysHistoryMod.objects.select_related(
        'driver', 'car', 'fourgon', 'country'
    ).prefetch_related(
        'client', 
        'product_set',
        'rayshistoryexpense_set'
    ).all().order_by('-created_at')
    serializer_class = rest_api.ExtendedRaysHistorySerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    @action(detail=False,methods=['get'],url_path='rayshistory-overview')
    def rayshistory_overview(self, request):
        rayshistory = models.RaysHistoryMod.objects.all()
        rays_count = rayshistory.count()
        rays_kilometr = rayshistory.aggregate(total=Coalesce(Sum('kilometer'), Value(0), output_field=DecimalField()))['total']
        rays_price = rayshistory.aggregate(total=Coalesce(Sum('price'), Value(0), output_field=DecimalField()))['total']
        
        dr_sum = rayshistory.aggregate(total=Coalesce(Sum('dr_price'), Value(0), output_field=DecimalField()))['total']
        dp_sum = rayshistory.aggregate(total=Coalesce(Sum('dp_price'), Value(0), output_field=DecimalField()))['total']
        rays_total_price = rays_price - (dr_sum + dp_sum)

        return Response({
            'rays_count': rays_count,
            'rays_kilometr': rays_kilometr,
            'rays_price': rays_price,
            'rays_total_price': rays_total_price
        })

    @docs.rayshistory_locations_doc
    @action(detail=False, methods=['get'], url_path='locations')
    def location(self, request):
        result = defaultdict(lambda: {"rays_count": 0, "total_price": 0})
        rays_history = models.RaysHistoryMod.objects.prefetch_related('client')

        for rays in rays_history:
            clients = rays.client.all()
            products = models.Product.objects.filter(client__in=clients).select_related('from_location', 'to_location')

            for product in products:
                from_loc = product.from_location.name if product.from_location else "❌"
                to_loc = product.to_location.name if product.to_location else "❌"
                key = (from_loc, to_loc)

                result[key]["rays_count"] += 1
                result[key]["total_price"] += product.price

        # Формируем список и оставляем топ 5
        response_data = sorted([
            {
                "from_location": from_loc,
                "to_location": to_loc,
                "rays_count": data["rays_count"],
                "total_price": data["total_price"]
            }
            for (from_loc, to_loc), data in result.items()
        ], key=lambda x: x["rays_count"], reverse=True)[:5]  # 👈 добавлен срез топ-5

        return Response(response_data)

    @swagger_auto_schema(
        operation_summary="📜 История рейсов (только чтение)",
        operation_description="Возвращает историю всех завершённых рейсов в порядке убывания даты."
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @swagger_auto_schema(
        operation_summary="🔍 Один рейс из истории по ID",
        operation_description="Получить подробную информацию о конкретном рейсе из истории."
    )
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)
class RaysViewSet(viewsets.ModelViewSet):
    queryset = models.RaysMod.objects.select_related(
        'driver', 'car', 'fourgon', 'country', 'dp_currency'
    ).prefetch_related(
        'client', 
        'client_completed',
        'product_set'
    ).all().order_by('-created_at')
    serializer_class = rest_api.RaysSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    filter_backends = [DjangoFilterBackend, SearchFilter]
    filterset_fields = ['is_completed', 'driver', 'client']
    pagination_class = RaysPagination  # <--- здесь применяем

    @action(detail=False,methods=['get'],url_path='active-rays-overview')
    def active_overview(self,request):
        rays = models.RaysMod.objects.all()
        rays_price = rays.aggregate(total=Coalesce(Sum('price'), Value(0), output_field=DecimalField()))['total']
        rays_dr_price = rays.aggregate(total=Coalesce(Sum('dr_price'), Value(0), output_field=DecimalField()))['total']
        rays_dp_price = rays.aggregate(total=Coalesce(Sum('dp_price'), Value(0), output_field=DecimalField()))['total']
        rays_total_price = rays_price - (rays_dr_price + rays_dp_price)
        return Response({
            "rays_price": round(rays_price, 2),
            "rays_dr_price": round(rays_dr_price, 2),
            "rays_dp_price": round(rays_dp_price, 2),
            "rays_total_price": round(rays_total_price, 2)
        })

    @swagger_auto_schema(operation_summary="📋 Список рейсов")
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @swagger_auto_schema(operation_summary="➕ Создать рейс")
    def create(self, request, *args, **kwargs):
        response = super().create(request, *args, **kwargs)
        rays_id = response.data.get('id')
        if rays_id:
            rays = models.RaysMod.objects.get(id=rays_id)
            client_ids = request.data.get('client', [])  # ожидаем список id клиентов
            for client_id in client_ids:
                products = models.Product.objects.filter(client_id=client_id, rays__isnull=True)
                for product in products:
                    product.rays = rays
                    product.save()
        return response


    @swagger_auto_schema(operation_summary="🔍 Получить рейс по ID")
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)

    @swagger_auto_schema(operation_summary="✏️ Обновить рейс")
    def update(self, request, *args, **kwargs):
        return super().update(request, *args, **kwargs)

    @swagger_auto_schema(operation_summary="🔧 Частичное обновление рейса")
    def partial_update(self, request, *args, **kwargs):
        return super().partial_update(request, *args, **kwargs)

    @swagger_auto_schema(operation_summary="🗑️ Удалить рейс")
    def destroy(self, request, *args, **kwargs):
        return super().destroy(request, *args, **kwargs)
    
    @action(detail=True, methods=['post'], url_path='recalculate-price')
    def recalculate_price(self, request, pk=None):
        try:
            rays = self.get_object()
        except models.RaysMod.DoesNotExist:
            return Response({"error": "Рейс не найден"}, status=404)

        rays.update_prices_from_products_and_expenses()

        return Response({"success": f"✅ Цена и расходы рейса обновлены (в USD): price = {rays.price}, dr_price = {rays.dr_price}"})

    @swagger_auto_schema(
        method='get',
        operation_summary="(GET) Rays Finish",
        operation_description="Use /rays/{id}/complete-race/ — Получить статус завершения рейса"
    )
    @swagger_auto_schema(
        method='post',
        operation_summary="(POST) Rays Finish",
        operation_description="Use /rays/{id}/complete-race/ — Завершить все клиенты и перенести рейс в историю"
    )
    @action(detail=True, methods=['get', 'post'], url_path='complete-race')
    def complete_race(self, request, pk=None):
        try:
            rays = self.get_object()
        except models.RaysMod.DoesNotExist:
            return Response({"error": "Рейс не найден"}, status=404)

        try:
            # Выполняем завершение рейса, получаем объект RaysHistoryMod
            rays_history = rays.complete_whole_race()

            # Обновляем все связанные продукты
            products = models.Product.objects.filter(rays=rays)
            for product in products:
                product.rays_history = rays_history  # ✅ правильный тип
                product.rays = None
                product.save()

        except Exception as e:
            return Response({"error": str(e)}, status=400)

        return Response({"success": "Все клиенты завершены, рейс перенесён в историю."})
    @swagger_auto_schema(
        method='get',
        operation_summary="Driver cars, trucks and clients free",
        operation_description="Bo‘sh haydovchi, mashina, furgon va mijozlar ro‘yxati"
    )
    @action(detail=False, methods=['get'], url_path='available-data')
    def available_data(self, request):
        return Response({
            'drivers': rest_api.CustomUserSerializer(models.CustomUser.objects.filter(status='driver', is_busy=False), many=True).data,
            "cars": rest_api.CarsSerializer(models.CarsMod.objects.filter(is_busy=False), many=True).data,
            "furgons": rest_api.FurgonSerializer(models.FurgonMod.objects.filter(is_busy=False), many=True).data,
            "clients": rest_api.ClientsSerializer(models.ClientsMod.objects.all(), many=True).data,
            "products": rest_api.ProductSerializer(models.Product.objects.filter(is_busy=False), many=True).data
        })

class ClientsViewSet(viewsets.ModelViewSet):
    queryset = models.ClientsMod.objects.all()
    serializer_class = rest_api.ClientsSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    @swagger_auto_schema(operation_summary="📋 Список клиентов", operation_description="Получить список всех клиентов")
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @swagger_auto_schema(operation_summary="➕ Новый клиент", operation_description="Добавить нового клиента")
    def create(self, request, *args, **kwargs):
        return super().create(request, *args, **kwargs)

    @swagger_auto_schema(operation_summary="🔍 Клиент по ID", operation_description="Получить клиента по его ID")
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)

    @swagger_auto_schema(operation_summary="✏️ Обновление клиента", operation_description="Полное обновление данных клиента")
    def update(self, request, *args, **kwargs):
        return super().update(request, *args, **kwargs)

    @swagger_auto_schema(operation_summary="🔧 Частичное обновление клиента", operation_description="Изменение одного или нескольких полей клиента")
    def partial_update(self, request, *args, **kwargs):
        return super().partial_update(request, *args, **kwargs)

    @swagger_auto_schema(operation_summary="🗑️ Удаление клиента", operation_description="Удаляет клиента по его ID")
    def destroy(self, request, *args, **kwargs):
        return super().destroy(request, *args, **kwargs)

class CarsViewSet(viewsets.ModelViewSet):
    queryset = models.CarsMod.objects.all()
    serializer_class = rest_api.CarsSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    # 📋 Список машин
    @swagger_auto_schema(
        operation_summary="📋 Список машин",
        operation_description="Возвращает список всех машин."
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    # ➕ Добавление машины
    @swagger_auto_schema(
        operation_summary="➕ Создать машину",
        operation_description="Добавить новую машину в систему."
    )
    def create(self, request, *args, **kwargs):
        return super().create(request, *args, **kwargs)

    # 🔍 Получение одной машины по ID
    @swagger_auto_schema(
        operation_summary="🔍 Получить машину по ID",
        operation_description="Возвращает полную информацию о машине."
    )
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)

    # ✏️ Полное обновление
    @swagger_auto_schema(
        operation_summary="✏️ Обновить машину",
        operation_description="Обновляет все поля машины по ID."
    )
    def update(self, request, *args, **kwargs):
        return super().update(request, *args, **kwargs)

    # 🔧 Частичное обновление
    @swagger_auto_schema(
        operation_summary="🔧 Частичное обновление машины",
        operation_description="Обновляет только указанные поля машины."
    )
    def partial_update(self, request, *args, **kwargs):
        return super().partial_update(request, *args, **kwargs)

    # 🗑️ Удаление
    @swagger_auto_schema(
        operation_summary="🗑️ Удалить машину",
        operation_description="Удаляет машину по ID."
    )
    def destroy(self, request, *args, **kwargs):
        return super().destroy(request, *args, **kwargs)

    # 👇 Кастомный endpoint — статус машин
    @swagger_auto_schema(
        method='get',
        operation_summary="🚗 Статус машин (заняты/свободны)",
        operation_description="Возвращает список занятых и свободных машин. Заняты — в рейсах."
    )
    @action(detail=False, methods=['get'], url_path='status-summary')
    def status_summary(self, request):
        busy_cars_qs = models.CarsMod.objects.filter(is_busy=True)
        free_cars_qs = models.CarsMod.objects.filter(is_busy=False)
        busy_cars = self.get_serializer(busy_cars_qs, many=True).data
        free_cars = self.get_serializer(free_cars_qs, many=True).data
        return Response({
            "in_rays": {
                "count": busy_cars_qs.count(),
                "items": busy_cars
            },
            "available": {
                "count": free_cars_qs.count(),
                "items": free_cars
            }
        })

class CustomUserViewSet(viewsets.ModelViewSet):
    def get_permissions(self):
        if self.action in ['list', 'retrieve', 'by_status', 'drivers_status', 'top_drivers']:
            permission_classes = [permissions.IsAuthenticated]
        else:
            permission_classes = [IsOwnerOrCEO]
        return [permission() for permission in permission_classes]

    queryset = models.CustomUser.objects.annotate(
        rays_count=Count('rayshistorymod', distinct=True),
        total_rays_usd=Coalesce(
            Sum('rayshistorymod__price'),
            Value(0),
            output_field=DecimalField()
        )
    ).all()
    serializer_class = rest_api.CustomUserSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    filter_backends = [DjangoFilterBackend, SearchFilter]
    filterset_fields = ['status']
    search_fields = ['fullname', 'phone_number', 'username']

    @swagger_auto_schema(operation_summary="📋 Список пользователей")
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @swagger_auto_schema(operation_summary="➕ Создать пользователя")
    def create(self, request, *args, **kwargs):
        return super().create(request, *args, **kwargs)

    @swagger_auto_schema(operation_summary="🔍 Получить пользователя")
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)

    @swagger_auto_schema(operation_summary="✏️ Обновить пользователя (полностью)")
    def update(self, request, *args, **kwargs):
        return super().update(request, *args, **kwargs)

    @swagger_auto_schema(operation_summary="🔧 Частичное обновление пользователя")
    def partial_update(self, request, *args, **kwargs):
        return super().partial_update(request, *args, **kwargs)

    @swagger_auto_schema(operation_summary="🗑️ Удалить пользователя")
    def destroy(self, request, *args, **kwargs):
        return super().destroy(request, *args, **kwargs)
    @docs.custom_driver_history_doc
    @action(detail=True,methods=['get'],url_path='driver-history')
    def driver_history(self,request,pk=None):
        try:
            driver = models.CustomUser.objects.get(status='driver', id=pk)
        except models.CustomUser.DoesNotExist:
            return Response({'error': 'Driver not found'}, status=status.HTTP_404_NOT_FOUND)
        
        history = models.RaysHistoryMod.objects.filter(driver=driver)
        # serializer = rest_api.CustomUserSerializer(driver)
        return Response({
            # 'driver': serializer.data,
            'history':rest_api.ExtendedRaysHistorySerializer(history,many=True).data
            })

    @swagger_auto_schema(
        method='get',
        operation_summary="Get users by status",
        operation_description="Use /user/by-status/?role=driver"
    )
    @action(detail=False, methods=['get'], url_path='by-status')
    def by_status(self, request):
        role = request.query_params.get('role')  # например: driver, owner, ceo и т.д.
        if not role:
            return Response({"error": "❌ Параметр ?role= обязателен"}, status=400)
        users = models.CustomUser.objects.filter(status=role)
        serializer = self.get_serializer(users, many=True)
        return Response({
            "count": users.count(),
            "role": role,
            "items": serializer.data
        })
    @swagger_auto_schema(
        method='get',
        operation_summary="only drivers not busy",
        operation_description="Get only drivers free"
    )
    @action(detail=False, methods=['get'], url_path='drivers')
    def drivers_status(self, request):
        users = models.CustomUser.objects.filter(status='driver', is_busy=False)
        fullnames = users.values_list('fullname', flat=True)
        return Response({
            "count": users.count(),
            "items": list(fullnames)
        })
    @swagger_auto_schema(
        method='get',
        operation_summary="Top drivers",
        # operation_description=""
    )
    @action(detail=False, methods=['get'], url_path='top-drivers')
    def top_drivers(self, request):
        top_users = models.CustomUser.objects.filter(status='driver') \
            .annotate(rays_count=Count('rayshistorymod')) \
            .order_by('-rays_count')
        serializer = self.get_serializer(top_users, many=True)
        return Response(serializer.data)
    
class ChiqimlarCategoryViewSet(viewsets.ModelViewSet):
    queryset = models.ChiqimlarCategory.objects.all()
    serializer_class = rest_api.ChiqimlarCategorySerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    @swagger_auto_schema(operation_summary="📋 Категории расходов", operation_description="Список всех категорий расходов")
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @swagger_auto_schema(operation_summary="➕ Новая категория", operation_description="Создание новой категории расходов")
    def create(self, request, *args, **kwargs):
        return super().create(request, *args, **kwargs)

    @swagger_auto_schema(operation_summary="🔍 Категория по ID", operation_description="Получить категорию расходов по ID")
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)

    @swagger_auto_schema(operation_summary="✏️ Обновить категорию", operation_description="Полное обновление категории")
    def update(self, request, *args, **kwargs):
        return super().update(request, *args, **kwargs)

    @swagger_auto_schema(operation_summary="🔧 Частичное обновление", operation_description="Изменить отдельные поля категории")
    def partial_update(self, request, *args, **kwargs):
        return super().partial_update(request, *args, **kwargs)

    @swagger_auto_schema(operation_summary="🗑️ Удалить категорию", operation_description="Удалить категорию расходов по ID")
    def destroy(self, request, *args, **kwargs):
        return super().destroy(request, *args, **kwargs)

class ChiqimlikViewSet(viewsets.ModelViewSet):
    queryset = models.ChiqimlikMod.objects.select_related('driver', 'chiqimlar', 'currency').all()
    serializer_class = rest_api.ChiqimlikSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    @swagger_auto_schema(operation_summary="📋 Список чеков", operation_description="Получить список всех чеков (chiqimlik)")
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @swagger_auto_schema(operation_summary="➕ Новый чек", operation_description="Добавить новый расход (чек)")
    def create(self, request, *args, **kwargs):
        return super().create(request, *args, **kwargs)

    @swagger_auto_schema(operation_summary="🔍 Чек по ID", operation_description="Получить чек по ID")
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)

    @swagger_auto_schema(operation_summary="✏️ Обновить чек", operation_description="Полностью обновить чек по ID")
    def update(self, request, *args, **kwargs):
        return super().update(request, *args, **kwargs)

    @swagger_auto_schema(operation_summary="🔧 Частично обновить чек", operation_description="Изменить отдельные поля чека по ID")
    def partial_update(self, request, *args, **kwargs):
        return super().partial_update(request, *args, **kwargs)

    @swagger_auto_schema(operation_summary="🗑️ Удалить чек", operation_description="Удалить чек по ID")
    def destroy(self, request, *args, **kwargs):
        return super().destroy(request, *args, **kwargs)

class ReferensViewSet(viewsets.ModelViewSet):
    queryset = models.ReferensMod.objects.all()
    serializer_class = rest_api.ReferensSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    @swagger_auto_schema(operation_summary="📋 Список референсов", operation_description="Получить список всех записей referens")
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @swagger_auto_schema(operation_summary="➕ Новый референс", operation_description="Добавить новую запись referens")
    def create(self, request, *args, **kwargs):
        return super().create(request, *args, **kwargs)

    @swagger_auto_schema(operation_summary="🔍 Референс по ID", operation_description="Получить запись по ID")
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)

    @swagger_auto_schema(operation_summary="✏️ Обновить референс", operation_description="Полное обновление записи")
    def update(self, request, *args, **kwargs):
        return super().update(request, *args, **kwargs)

    @swagger_auto_schema(operation_summary="🔧 Частичное обновление", operation_description="Изменение отдельных полей записи")
    def partial_update(self, request, *args, **kwargs):
        return super().partial_update(request, *args, **kwargs)

    @swagger_auto_schema(operation_summary="🗑️ Удалить запись", operation_description="Удалить запись referens по ID")
    def destroy(self, request, *args, **kwargs):
        return super().destroy(request, *args, **kwargs)
    
class ArizaViewSet(viewsets.ModelViewSet):
    queryset = models.ArizaMod.objects.all()
    serializer_class = rest_api.ArizaSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    @swagger_auto_schema(operation_summary="📋 Список заявок", operation_description="Получить список всех заявок (ariza)")
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @swagger_auto_schema(operation_summary="➕ Новая заявка", operation_description="Создать новую заявку")
    def create(self, request, *args, **kwargs):
        return super().create(request, *args, **kwargs)

    @swagger_auto_schema(operation_summary="🔍 Заявка по ID", operation_description="Получить заявку по её ID")
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)

    @swagger_auto_schema(operation_summary="✏️ Обновить заявку", operation_description="Полное обновление заявки")
    def update(self, request, *args, **kwargs):
        return super().update(request, *args, **kwargs)

    @swagger_auto_schema(operation_summary="🔧 Частичное обновление заявки", operation_description="Изменение некоторых полей заявки")
    def partial_update(self, request, *args, **kwargs):
        return super().partial_update(request, *args, **kwargs)

    @swagger_auto_schema(operation_summary="🗑️ Удалить заявку", operation_description="Удалить заявку по ID")
    def destroy(self, request, *args, **kwargs):
        return super().destroy(request, *args, **kwargs)

class FurgonViewSet(viewsets.ModelViewSet):
    queryset = models.FurgonMod.objects.all()
    serializer_class = rest_api.FurgonSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    @swagger_auto_schema(
        operation_summary="📋 Список фургонов",
        operation_description="Получить список всех фургонов."
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @swagger_auto_schema(
        operation_summary="➕ Добавить фургон",
        operation_description="Создать новый фургон в системе."
    )
    def create(self, request, *args, **kwargs):
        return super().create(request, *args, **kwargs)

    @swagger_auto_schema(
        operation_summary="🔍 Получить фургон по ID",
        operation_description="Возвращает полную информацию о фургоне."
    )
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)

    @swagger_auto_schema(
        operation_summary="✏️ Обновить фургон",
        operation_description="Полностью обновить данные фургона."
    )
    def update(self, request, *args, **kwargs):
        return super().update(request, *args, **kwargs)

    @swagger_auto_schema(
        operation_summary="🔧 Частичное обновление фургона",
        operation_description="Обновляет только переданные поля фургона."
    )
    def partial_update(self, request, *args, **kwargs):
        return super().partial_update(request, *args, **kwargs)

    @swagger_auto_schema(
        operation_summary="🗑️ Удалить фургон",
        operation_description="Удалить фургон по его ID."
    )
    def destroy(self, request, *args, **kwargs):
        return super().destroy(request, *args, **kwargs)

    @swagger_auto_schema(
        method='get',
        operation_summary="🚚 Статус фургонов (заняты/свободны)",
        operation_description="Возвращает список занятых и свободных фургонов. Заняты — в активных рейсах."
    )
    @action(detail=False, methods=['get'], url_path='status-summary')
    def status_summary(self, request):
        busy_qs = models.FurgonMod.objects.filter(is_busy=True)
        free_qs = models.FurgonMod.objects.filter(is_busy=False)
        busy_data = rest_api.FurgonSerializer(busy_qs, many=True).data
        free_data = rest_api.FurgonSerializer(free_qs, many=True).data
        return Response({
            "in_rays": {
                "count": busy_qs.count(),
                "items": busy_data
            },
            "available": {
                "count": free_qs.count(),
                "items": free_data
            }
        })

class ProductViewSet(viewsets.ModelViewSet):
    queryset = models.Product.objects.select_related(
        'rays', 'rays_history', 'client', 'currency', 'from_location', 'to_location'
    ).all()
    serializer_class = rest_api.ProductSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    @swagger_auto_schema(operation_summary="📋 Список продуктов", operation_description="Получить список всех продуктов")
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @swagger_auto_schema(operation_summary="➕ Новый продукт", operation_description="Добавить новый продукт")
    def create(self, request, *args, **kwargs):
        return super().create(request, *args, **kwargs)

    @swagger_auto_schema(operation_summary="🔍 Продукт по ID", operation_description="Получить продукт по его ID")
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)

    @swagger_auto_schema(operation_summary="✏️ Обновить продукт", operation_description="Полное обновление продукта")
    def update(self, request, *args, **kwargs):
        return super().update(request, *args, **kwargs)

    @swagger_auto_schema(operation_summary="🔧 Частичное обновление продукта", operation_description="Изменение полей продукта")
    def partial_update(self, request, *args, **kwargs):
        return super().partial_update(request, *args, **kwargs)

    @swagger_auto_schema(operation_summary="🗑️ Удалить продукт", operation_description="Удалить продукт по ID")
    def destroy(self, request, *args, **kwargs):
        return super().destroy(request, *args, **kwargs)
