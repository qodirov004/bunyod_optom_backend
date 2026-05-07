import sqlite3
import os

db_path = 'db.sqlite3'
if os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    print("--- Mashinalar ma'lumotlari ---")
    cursor.execute("SELECT id, name, photo FROM set_main_carsmod LIMIT 5")
    rows = cursor.fetchall()
    for row in rows:
        print(f"ID: {row[0]}, Nomi: {row[1]}, Rasm yo'li: {row[2]}")
    conn.close()
else:
    print("Database not found")
