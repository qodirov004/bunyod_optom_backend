from . import models
from django.contrib import admin
from unfold.admin import ModelAdmin

@admin.register(models.ReferensMod)
class ReferenceAdmin(ModelAdmin):
    list_display = ('driver', 'description', 'created_at')

@admin.register(models.RaysMod)
class RaysModAdmin(ModelAdmin):
    list_display = ('driver',)

@admin.register(models.RaysHistoryMod)
class RaysHistoryModAdmin(ModelAdmin):
    list_display = ('driver', )

@admin.register(models.CustomUser)
class CustomUserAdmin(ModelAdmin):
    list_display = ('username', 'fullname', 'phone_number', 'status', 'date', 'is_active')
    search_fields = ('username', 'fullname', 'phone_number')
    list_filter = ('status', 'is_active')

@admin.register(models.ClientsMod)
class ClientsModAdmin(ModelAdmin):
    list_display = ('first_name', 'last_name', 'city', 'number')
    search_fields = ('first_name', 'last_name', 'number')
    list_filter = ('city',)

@admin.register(models.ChiqimlarCategory)
class ChiqimlarCategoryAdmin(ModelAdmin):
    list_display = ('name',)
    search_fields = ('name',)

@admin.register(models.ChiqimlikMod)
class ChiqimlikModAdmin(ModelAdmin):
    list_display = ('driver', 'chiqimlar', 'price', 'created_at')
    search_fields = ('driver__username', 'chiqmlar__name')
    list_filter = ('created_at',)

@admin.register(models.ArizaMod)
class ArizaModAdmin(ModelAdmin):
    list_display = ('driver', 'description', 'created_at')
    search_fields = ('driver__username', 'description')
    list_filter = ('created_at',)

@admin.register(models.CarsMod)
class CarsModAdmin(ModelAdmin):
    list_display = ('name', 'number', 'year', 'holat')
    search_fields = ('name', 'number', 'car_number')
    list_filter = ('holat', 'year')

@admin.register(models.FurgonMod)
class FurgonModAdmin(ModelAdmin):
    list_display = ('name', 'number')
    search_fields = ('name', 'number', 'car__name')

@admin.register(models.Product)
class ProductAdmin(ModelAdmin):
    list_display = ('name', 'price', 'count')
    search_fields = ('name', 'furgon_mod__name')
    list_filter = ('price',)

@admin.register(models.CountryMod)
class CountryModAdmin(ModelAdmin):
    list_display = ('name',)
    search_fields = ('name',)

@admin.register(models.FromLocation)
class FromLocationAdmin(ModelAdmin):
    list_display = ('name',)
    search_fields = ('name',)

@admin.register(models.ToLocation)
class ToLocationAdmin(ModelAdmin):
    list_display = ('name',)
    search_fields = ('name',)

@admin.register(models.CashCategory)
class CashCategoryAdmin(ModelAdmin):
    list_display = ('name',)
    search_fields = ('name',)

@admin.register(models.CashTransactionMod)
class CashTransactionModAdmin(ModelAdmin):
    list_display = ('client', 'rays', 'amount', 'status', 'payment_way', 'created_at')
    list_filter = ('status', 'payment_way', 'created_at')
    search_fields = ('client__first_name', 'client__last_name', 'comment')

@admin.register(models.CashTransactionHistory)
class CashTransactionHistoryAdmin(ModelAdmin):
    list_display = ('client', 'rays', 'amount', 'status', 'payment_way', 'created_at', 'moved_at')
    list_filter = ('status', 'payment_way', 'created_at', 'moved_at')
    search_fields = ('client__first_name', 'client__last_name', 'comment')
