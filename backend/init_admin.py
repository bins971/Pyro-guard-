from app.database import SessionLocal
from app.models import User
from app.api.auth import get_password_hash

def init_admin():
    db = SessionLocal()
    admin = db.query(User).filter(User.username == "admin").first()
    if not admin:
        new_admin = User(
            username="admin",
            hashed_password=get_password_hash("admin123"),
            is_admin=True,
            role="admin"
        )
        db.add(new_admin)
        db.commit()
        print("Admin user created: admin / admin123")
    else:
        print("Admin user already exists.")
    db.close()

if __name__ == "__main__":
    init_admin()
