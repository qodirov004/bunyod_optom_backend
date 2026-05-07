import sqlite3
import os

db_path = 'db.sqlite3'
if os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Mashinalar rasmlarini bo'shatish
    print("Mashinalar rasmlari tozalanmoqda...")
    cursor.execute("UPDATE set_main_carsmod SET photo = ''")
    
    # Furgonlar rasmlarini ham tozalash (ehtiyotdan)
    print("Furgonlar rasmlari tozalanmoqda...")
    cursor.execute("UPDATE set_main_furgonmod SET photo = ''")
    
    conn.commit()
    print("Muvaffaqiyatli yakunlandi! Endi barcha mashinalarda standart rasm ko'rinadi.")
    conn.close()
else:
    print("Database not found")
