import sqlite3

conn = sqlite3.connect("uraas.db")
cursor = conn.cursor()

cursor.execute(
    "SELECT title, institution, created_at FROM items WHERE institution = 'Addis Ababa University' ORDER BY created_at DESC;"
)
rows = cursor.fetchall()

if not rows:
    print("No papers found for Addis Ababa University.")
else:
    print(f"Found {len(rows)} papers total:")
    for row in rows:
        print(f"- {row[0][:50]}... | {row[1]} | {row[2]}")

conn.close()
