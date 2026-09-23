import sqlite3
from app.database import engine, Base
from app.models import User

def update_db():
    print("Creating new tables...")
    Base.metadata.create_all(bind=engine)
    
    print("Altering existing tables...")
    conn = sqlite3.connect('pyroguard.db')
    cursor = conn.cursor()
    
    try:
        cursor.execute("ALTER TABLE cameras ADD COLUMN ptz_enabled BOOLEAN DEFAULT 0")
        cursor.execute("ALTER TABLE cameras ADD COLUMN ptz_user VARCHAR(100)")
        cursor.execute("ALTER TABLE cameras ADD COLUMN ptz_password VARCHAR(100)")
        cursor.execute("ALTER TABLE cameras ADD COLUMN ptz_port INTEGER DEFAULT 80")
        print("Successfully added PTZ columns to cameras table.")
    except sqlite3.OperationalError as e:
        print(f"Columns might already exist: {e}")
        
    conn.commit()
    conn.close()
    
    print("Database update complete.")

if __name__ == "__main__":
    update_db()
