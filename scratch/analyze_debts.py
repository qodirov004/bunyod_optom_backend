import os
import django
import sys
from decimal import Decimal

# Setup Django
sys.path.append(r'd:\Projects\bunyod_optom\bunyod_optom_backend')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'set_app.settings')
django.setup()

from set_main import models

def analyze_debts():
    print("--- Qarzdorlik Tahlili ---")
    
    # 1. Total debts from CashTransactionMod (confirmed only)
    transactions = models.CashTransactionMod.objects.filter(is_debt=True, status='confirmed')
    total_debt_usd = sum(tx.remaining_debt for tx in transactions if tx.remaining_debt)
    
    print(f"Tasdiqlangan jami qarz (USD): {total_debt_usd}")
    print(f"Tranzaksiyalar soni: {transactions.count()}")
    
    # 2. Top debtors
    from django.db.models import Sum
    debtors = models.CashTransactionMod.objects.filter(is_debt=True, status='confirmed')\
        .values('client__company', 'client__last_name', 'client__first_name')\
        .annotate(total_remaining=Sum('remaining_debt'))\
        .order_by('-total_remaining')[:10]
    
    print("\nEng ko'p qarzga ega mijozlar:")
    for d in debtors:
        name = d['client__company'] or f"{d['client__last_name']} {d['client__first_name']}"
        print(f"- {name}: {d['total_remaining']} USD")

    # 3. Check for potential duplicates or anomalies
    # Maybe some transactions have huge numbers?
    huge_tx = models.CashTransactionMod.objects.filter(remaining_debt__gt=100000)
    if huge_tx.exists():
        print("\nDIQQAT: Juda katta summali tranzaksiyalar topildi:")
        for tx in huge_tx:
            print(f"- ID: {tx.id}, Mijoz: {tx.client}, Summa: {tx.remaining_debt} USD, Sana: {tx.created_at}")

if __name__ == "__main__":
    analyze_debts()
