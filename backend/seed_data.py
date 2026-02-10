
import sys
import os

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.database import SessionLocal
from app.models import Camera

def seed_camera():
    db = SessionLocal()
    try:
        # Check if camera exists
        existing = db.query(Camera).filter(Camera.name == "Main Feed").first()
        if existing:
            print("Camera 'Main Feed' already exists.")
            return

        camera = Camera(
            name="Main Feed",
            location="Main Entrance",
            rtsp_url="0", 
            is_active=True
        )
        db.add(camera)
        db.commit()
        print("✅ Added default camera: 'Main Feed' (Source: Webcam 0)")
        
    except Exception as e:
        print(f"❌ Error seeding camera: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    seed_camera()
