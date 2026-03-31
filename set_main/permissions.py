from rest_framework import permissions

class IsOwnerOrCEO(permissions.BasePermission):
    """
    Ruxsat: Faqat Owner va CEO (barcha huquqlarga ega).
    """
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.status in ['owner', 'ceo'])

class IsCashierOrAdmin(permissions.BasePermission):
    """
    Ruxsat: Cashier, tayinlangan Bugalter, CEO yoki Owner
    """
    def has_permission(self, request, view):
        return bool(
            request.user and 
            request.user.is_authenticated and 
            request.user.status in ['cashier', 'bugalter', 'ceo', 'owner']
        )

class IsZaphosOrAdmin(permissions.BasePermission):
    """
    Ruxsat: Zaphos, CEO yoki Owner
    """
    def has_permission(self, request, view):
        return bool(
            request.user and 
            request.user.is_authenticated and 
            request.user.status in ['zaphos', 'ceo', 'owner']
        )

class IsDriverOrAdmin(permissions.BasePermission):
    """
    Ruxsat: Haydovchi, yoki ma'muriyat
    """
    def has_permission(self, request, view):
        return bool(
            request.user and 
            request.user.is_authenticated and 
            request.user.status in ['driver', 'zaphos', 'cashier', 'bugalter', 'ceo', 'owner']
        )
class IsBugalterOrAdmin(permissions.BasePermission):
    """
    Ruxsat: Bugalter, CEO yoki Owner
    """
    def has_permission(self, request, view):
        return bool(
            request.user and 
            request.user.is_authenticated and 
            request.user.status in ['bugalter', 'ceo', 'owner']
        )
