from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from .. import rest_api

rayshistory_locations_doc = swagger_auto_schema(
    operation_summary="List rayshistory locations",
    operation_description="List all rayshistory locations",
)

custom_driver_history_doc = swagger_auto_schema(
    operation_summary="List custom driver history",
    operation_description="List all custom driver history",
)

casa_confirm_doc = swagger_auto_schema(
    operation_summary="Подтвердить оплату",
    operation_description="Подтвердить оплату",
)

casa_client_debt_all_doc = swagger_auto_schema(
    operation_summary="Долг всех клиента",
    operation_description="Долг всех клиента",
)

casa_client_debt_doc = swagger_auto_schema(
    operation_summary="Долг клиента нужно передавать id клиента",
    operation_description="Долг клиента нужно передавать id клиента\n/casa/client-debt/?client_id=11",
)

casa_overview_doc = swagger_auto_schema(
    operation_summary="Деньгы на кассе",
    operation_description="Деньгы на кассе",
)

driver_history_doc = swagger_auto_schema(
    operation_summary="List driver history",
    operation_description="List all driver history",
)

payment_list_doc = swagger_auto_schema(
    operation_summary="List payment",
    operation_description="List all payment",
)

payment_create_doc = swagger_auto_schema(
    operation_summary="📋 Создать оплату",
    operation_description="Создает новую оплату.",
    responses={200: openapi.Response("OK")}
)

payment_retrieve_doc = swagger_auto_schema(
    operation_summary="📋 Получить оплату",
    operation_description="Возвращает оплату.",
    responses={200: openapi.Response("OK")}
)

payment_update_doc = swagger_auto_schema(
    operation_summary="📋 Обновить оплату",
    operation_description="Обновляет оплату.",
    responses={200: openapi.Response("OK")}
)

payment_partial_update_doc = swagger_auto_schema(
    operation_summary="📋 Обновить оплату",
    operation_description="Обновляет оплату.",
    responses={200: openapi.Response("OK")}
)

payment_destroy_doc = swagger_auto_schema(
    operation_summary="📋 Удалить оплату",
    operation_description="Удаляет оплату.",
    responses={200: openapi.Response("OK")}
)

auth_login_doc = swagger_auto_schema(
    method='post',
    operation_summary="🔐 Логин",
    operation_description="Вход по имени пользователя и паролю. Возвращает access и refresh токены.",
    request_body=openapi.Schema(
        type=openapi.TYPE_OBJECT,
        required=['username', 'password'],
        properties={
            'username': openapi.Schema(type=openapi.TYPE_STRING, description='Имя пользователя'),
            'password': openapi.Schema(type=openapi.TYPE_STRING, description='Пароль')
        }
    ),
    responses={200: openapi.Response(description="Успешный вход с токенами"), 401: "Неверные учетные данные"}
)

auth_register_doc = swagger_auto_schema(
    method='post',
    operation_summary="📝 Регистрация",
    operation_description="Регистрация нового пользователя. Возвращает access и refresh токены и данные пользователя.",
    request_body=rest_api.CustomUserSerializer,
    responses={201: openapi.Response(description="Успешная регистрация")}
)

auth_token_obtain_doc = swagger_auto_schema(
    method='post',
    operation_summary="🛡️ Получить токен",
    operation_description="Получение JWT access/refresh токена через username и password.",
    request_body=openapi.Schema(
        type=openapi.TYPE_OBJECT,
        required=['username', 'password'],
        properties={
            'username': openapi.Schema(type=openapi.TYPE_STRING),
            'password': openapi.Schema(type=openapi.TYPE_STRING)
        }
    ),
    responses={200: "Токен выдан", 401: "Ошибка авторизации"}
)

auth_token_refresh_doc = swagger_auto_schema(
    method='post',
    operation_summary="♻️ Обновление токена",
    operation_description="Обновление access токена с помощью refresh токена.",
    request_body=openapi.Schema(
        type=openapi.TYPE_OBJECT,
        required=['refresh'],
        properties={
            'refresh': openapi.Schema(type=openapi.TYPE_STRING, description='Refresh токен')
        }
    ),
    responses={200: "Access токен обновлен", 401: "Неверный refresh токен"}
)

auth_list_doc = swagger_auto_schema(
    operation_summary="ℹ️ Описание эндпоинтов авторизации",
    operation_description="Документация по всем маршрутам: логин, регистрация, получение и обновление токена.",
    responses={200: "Описание маршрутов"}
)

car_retrieve_doc = swagger_auto_schema(
    operation_summary="🔍 Получить активную информацию по машине",
    operation_description="""
    Возвращает текущую информацию по машине с учётом активного рейса.  
    В ответе будут данные по водителю, затратам (чек, референс, заявка, оплат, баллон, тех.обслуживание) и их суммарные значения.
    """,
    responses={200: openapi.Response(description="Успешный ответ с данными по машине и затратам"),
    404: openapi.Response(description="Машина не найдена или не в активном рейсе")}
)

car_list_doc = swagger_auto_schema(
    operation_summary="📋 Список всех активных машин с рейсами",
    operation_description="""
    Возвращает список всех машин, участвующих в активных рейсах.  
    Каждая машина содержит данные по водителю, затратам, началу рейса и деталям затрат.
    """,
    responses={200: openapi.Response(description="Успешный ответ со списком машин")}
)

optol_list_doc = swagger_auto_schema(
    operation_summary="📋 Получить список optol",
    operation_description="Возвращает список всех optol.",
    responses={200: openapi.Response("OK")}
)

optol_create_doc = swagger_auto_schema(
    operation_summary="➕ Добавить новую optol",
    operation_description="Создает новую optol по переданным данным.",
    responses={201: openapi.Response("Создано")}
)

optol_retrieve_doc = swagger_auto_schema(
    operation_summary="🔍 Получить optol по ID",
    operation_description="Возвращает данные optol по её ID.",
    responses={200: openapi.Response("OK"), 404: openapi.Response("Не найдено")}
)

optol_update_doc = swagger_auto_schema(
    operation_summary="✏️ Обновить данные optol полностью",
    operation_description="Полностью обновляет данные optol по ID.",
    responses={200: openapi.Response("Обновлено"), 400: openapi.Response("Ошибка запроса")}
)

optol_partial_update_doc = swagger_auto_schema(
    operation_summary="🔧 Частичное обновление optol",
    operation_description="Обновляет отдельные поля optol по ID.",
    responses={200: openapi.Response("Обновлено"), 400: openapi.Response("Ошибка запроса")}
)

optol_destroy_doc = swagger_auto_schema(
    operation_summary="🗑️ Удалить optol",
    operation_description="Удаляет optol по её ID.",
    responses={204: openapi.Response("Удалено"), 404: openapi.Response("Не найдено")}
)

paymenthistory_list_doc = swagger_auto_schema(
    operation_summary="List payment history",
    operation_description="List all payment history",
)

paymenthistory_create_doc = swagger_auto_schema(
    operation_summary="📋 Создать оплату",
    operation_description="Создает новую оплату.",
    responses={200: openapi.Response("OK")}
)

paymenthistory_retrieve_doc = swagger_auto_schema(
    operation_summary="📋 Получить оплату",
    operation_description="Возвращает оплату.",
    responses={200: openapi.Response("OK")}
)

paymenthistory_update_doc = swagger_auto_schema(
    operation_summary="📋 Обновить оплату",
    operation_description="Обновляет оплату.",
    responses={200: openapi.Response("OK")}
)

paymenthistory_partial_update_doc = swagger_auto_schema(
    operation_summary="📋 Обновить оплату",
    operation_description="Обновляет оплату.",
    responses={200: openapi.Response("OK")}
)

paymenthistory_destroy_doc = swagger_auto_schema(
    operation_summary="📋 Удалить оплату",
    operation_description="Удаляет оплату.",
    responses={200: openapi.Response("OK")}
)

raysH_get_doc = swagger_auto_schema(
    method='get',
    operation_summary="Rays Restore",
    operation_description="Use /rayshistory-actions/<id>/restore/ — Получить статус восстановление рейса"
)

raysH_post_doc = swagger_auto_schema(
    method='post',
    operation_summary="Rays Restore",
    operation_description="Use /rayshistory-actions/<id>/restore/ — восстановление рейса"
)

raysH_list_doc = swagger_auto_schema(
    operayion_summary="Rays Restore", 
    operation_description="Use /rayshistory-actions/<id>/restore/ — Получить статус восстановление рейса"
)

rays_export_doc = swagger_auto_schema(
    method='get',
    operation_summary="Export to Excel",
    operation_description="Use /rays-export/export/\nUse /rays-export/export/?period=week|month|year\nUse /rays-export/export/?from=YYYY-MM-DD&to=YYYY-MM-DD"
)

rays_ex_list_doc = swagger_auto_schema(
    operation_summary="📋 Получить список экспортов",
    operation_description="Возвращает список всех экспортов.",
    responses={200: openapi.Response("OK")}
)

country_list_doc = swagger_auto_schema(
    operation_summary="📋 Получить список стран",
    operation_description="Возвращает список всех стран.",
    responses={200: openapi.Response("OK")}
)

country_create_doc = swagger_auto_schema(
    operation_summary="➕ Добавить новую страну",
    operation_description="Создает новую страну по переданным данным.",
    responses={201: openapi.Response("Создано")}
)

country_retrieve_doc = swagger_auto_schema(
    operation_summary="🔍 Получить страну по ID",
    operation_description="Возвращает данные страны по её ID.",
    responses={200: openapi.Response("OK"), 404: openapi.Response("Не найдено")}
)

country_update_doc = swagger_auto_schema(
    operation_summary="✏️ Обновить данные страны полностью",
    operation_description="Полностью обновляет данные страны по ID.",
    responses={200: openapi.Response("Обновлено"), 400: openapi.Response("Ошибка запроса")}
)

country_partial_update_doc = swagger_auto_schema(
    operation_summary="🔧 Частичное обновление страны",
    operation_description="Обновляет отдельные поля страны по ID.",
    responses={200: openapi.Response("Обновлено"), 400: openapi.Response("Ошибка запроса")}
)

country_destroy_doc = swagger_auto_schema(
    operation_summary="🗑️ Удалить страну",
    operation_description="Удаляет страну по её ID.",
    responses={204: openapi.Response("Удалено"), 404: openapi.Response("Не найдено")}
)
