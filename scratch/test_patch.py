import os
import sys
import django
from django.test import Client

# Add project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'set_app.settings')
django.setup()

from set_main.models import CashTransactionMod, CustomUser

print("Creating test transaction...")
tx = CashTransactionMod.objects.create(client_id=3, amount=1000, status='pending')
print(f"Created transaction ID: {tx.id}, status: {tx.status}, is_confirmed: {tx.is_confirmed_by_cashier}")

user = CustomUser.objects.filter(status='cashier').first()
if not user:
    user = CustomUser.objects.first()
print(f"Using user: {user.username if user else 'None'}")

c = Client()
if user:
    c.force_login(user)

print("\nPATCHing transaction to set is_confirmed_by_cashier=True...")
response = c.patch(f'/casa/{tx.id}/', {'is_confirmed_by_cashier': True}, content_type='application/json')
print(f"Response status code: {response.status_code}")
print(f"Response data: {response.content.decode()}")

tx.refresh_from_db()
print(f"\nAfter PATCH status: {tx.status}, is_confirmed: {tx.is_confirmed_by_cashier}")

# Clean up
tx.delete()
