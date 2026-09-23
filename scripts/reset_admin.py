import sys
sys.path.insert(0, '/home/pyroguard/pyro-guard/backend')

import bcrypt

# Monkeypatch for passlib compatibility
if not hasattr(bcrypt, "__about__"):
    class _About:
        __version__ = "3.2.2"
    bcrypt.__about__ = _About

from passlib.context import CryptContext
import sqlite3

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
new_hash = pwd_context.hash("admin123")
print(f"New hash: {new_hash}")

conn = sqlite3.connect('/home/pyroguard/pyro-guard/backend/pyroguard.db')
cursor = conn.cursor()
cursor.execute("UPDATE users SET hashed_password = ? WHERE username = 'admin'", (new_hash,))
conn.commit()
print(f"Rows updated: {cursor.rowcount}")
conn.close()
print("Admin password reset to admin123 successfully!")
