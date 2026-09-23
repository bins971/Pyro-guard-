import sqlite3
tapo_url = "rtsp://pyroguard:pyroguard041505@192.168.1.12:554/stream2"
db_path = "/home/pyroguard/pyro-guard/backend/pyroguard.db"

try:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    cursor.execute("SELECT id FROM cameras WHERE name='Tapo C200C'")
    result = cursor.fetchone()
    
    if result:
        cursor.execute("UPDATE cameras SET rtsp_url = ? WHERE name = 'Tapo C200C'", (tapo_url,))
        print("Updated existing Tapo C200C camera!")
    else:
        cursor.execute("""
            INSERT INTO cameras (name, location, rtsp_url, is_active, status) 
            VALUES ('Tapo C200C', 'Surveillance', ?, 1, 0)
        """, (tapo_url,))
        print("Added new Tapo C200C camera!")
        
    conn.commit()
    conn.close()
except Exception as e:
    print("Database Error:", e)
