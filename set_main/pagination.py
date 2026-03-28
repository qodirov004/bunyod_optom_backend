
from rest_framework.pagination import PageNumberPagination

class RaysPagination(PageNumberPagination):
    page_size = 10  # сколько по умолчанию
    page_size_query_param = 'page_size'  # ?page_size=20
    max_page_size = 100