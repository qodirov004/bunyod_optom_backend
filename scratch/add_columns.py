import sqlite3
import os

db_path = 'db.sqlite3'
if os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    def add_column(table, column, definition):
        try:
            print(f"{table} jadvaliga {column} ustuni qo'shilmoqda...")
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
            print(f"✅ {column} muvaffaqiyatli qo'shildi.")
        except sqlite3.OperationalError as e:
            if "duplicate column name" in str(e):
                print(f"ℹ️ {column} allaqachon mavjud.")
            else:
                print(f"❌ Xato: {e}")

    # RaysHistoryMod uchun rays_id va returned_advance
    add_column('set_main_rayshistorymod', 'rays_id', 'BIGINT')
    add_column('set_main_rayshistorymod', 'returned_advance', 'BIGINT DEFAULT 0')
    add_column('set_main_rayshistorymod', 'driver_expense', 'BIGINT DEFAULT 0')
    
    # RaysMod uchun returned_advance
    add_column('set_main_raysmod', 'returned_advance', 'BIGINT DEFAULT 0')
    add_column('set_main_raysmod', 'driver_expense', 'BIGINT DEFAULT 0')

    conn.commit()
    conn.close()
    print("\nBarcha operatsiyalar yakunlandi. Endi sahifani yangilab ko'ring.")
else:
    print("Database not found")
