from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from .config import settings

engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    echo=False
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


from sqlalchemy import text

def init_db():
    Base.metadata.create_all(bind=engine)
    with engine.connect() as conn:
        try:
            result = conn.execute(text("PRAGMA table_info(users)")).fetchall()
            columns = [row[1] for row in result]
            if "role" not in columns:
                conn.execute(text("ALTER TABLE users ADD COLUMN role VARCHAR(20) DEFAULT 'operator'"))
                conn.execute(text("UPDATE users SET role = 'admin' WHERE is_admin = 1"))
                conn.commit()
        except Exception as e:
            print(f"Migration check notice: {e}")

