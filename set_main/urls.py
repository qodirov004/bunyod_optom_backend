from . import views
from django.urls import path,include,re_path
from rest_framework.routers import DefaultRouter

router = DefaultRouter()
router.register(r'currency', views.CurrencyRateViewSet)
router.register(r'driversalary',views.DriverViewSet)
router.register(r'casacategory',views.CashCategoryViewSet)
router.register(r'casa',views.CashTransactionViewSet)
router.register(r'casahistory', views.CashierHistoryViewSet)
router.register(r'customusers', views.CustomUserViewSet, basename='customusers')
router.register(r'country', views.CountryViewSet)
router.register(r'rays', views.RaysViewSet)
router.register(r'rayshistory', views.RaysHistoryFullViewSet)
router.register(r'service', views.ServiceViewSet)
router.register(r'texnic', views.TexViewSet)
router.register(r'optol', views.OptolViewSet)
router.register(r'balon', views.BalonViewSet)
router.register(r'balonfurgon', views.BalonFurgonViewSet)
router.register(r'clients', views.ClientsViewSet)
router.register(r'chiqimlarcategory', views.ChiqimlarCategoryViewSet)
router.register(r'chiqimlik', views.ChiqimlikViewSet)
router.register(r'referens', views.ReferensViewSet)
router.register(r'ariza', views.ArizaViewSet)
router.register(r'cars', views.CarsViewSet)
router.register(r'furgon', views.FurgonViewSet)
router.register(r'fromlocation', views.FromLocationViewSet)
router.register(r'tolocation', views.ToLocationViewSet)
router.register(r'product', views.ProductViewSet)
# 👇 Добавь эти два ViewSet

router.register(r'rays-export', views.RaysExportViewSet, basename='rays-export')
router.register(r'rayshistory-actions', views.RaysHistoryActionsViewSet, basename='rayshistory-actions')
router.register(r'history', views.HistoryViewSet, basename='history')
router.register(r'auth', views.AuthViewSet, basename='auth')
router.register(r'car-active', views.CarActiveDetailViewSet, basename='car-active')
router.register(r'car-history-full', views.CarFullHistoryViewSet, basename='car-history-full')

urlpatterns = [
  path('',include(router.urls)),
  # path('token/', views.CustomTokenObtainPairView.as_view(), name='token_obtain_pair'),
  # path('token/refresh/', views.CustomTokenRefreshView.as_view(), name='token_refresh'),
  # path('register/', views.RegisterView.as_view(), name='register'),
  # path('login/', views.LoginView.as_view(), name='login'),
  # path("rayshistory/<int:pk>/restore/", views.RestoreRaysAPIView.as_view(), name="rays-restore"),
  # path("api/rays/export/", views.export_rays_excel, name="export_rays_excel"),
  # path("rays/export/", views.ExportRaysExcelAPIView.as_view(), name="rays-export"),
  # path("car-history/<int:id>/", views.CarHistoryView.as_view(), name="car-history"),
  # path("client-history/<int:id>/", views.ClientHistoryView.as_view(), name="client-history"),
]
