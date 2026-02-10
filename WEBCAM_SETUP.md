# Webcam Setup for Fire Detection

## Quick Start (5 minutes)

### 1. Install Requirements
- Python 3.10+: https://www.python.org/downloads/
- Node.js 18+: https://nodejs.org/

### 2. Clone & Setup
```bash
git clone https://github.com/bins971/Pyro-guard-.git
cd "PYRO-GUARD A VISION-BASED SYSTEM FOR FIRE LEVEL DETECTION IN SURVEILLANCE NETWORKS"

# Backend
cd backend
pip install -r requirements.txt
copy .env.example .env

# Frontend  
cd ../frontend
npm install
copy .env.example .env.local
```

### 3. Add Your Webcam
```bash
cd backend
python seed_data.py
```

You should see: `✅ Added default camera: 'Main Feed' (Source: Webcam 0)`

### 4. Run the Application

**Terminal 1 (Backend):**
```bash
cd backend
.\run.bat
```

**Terminal 2 (Frontend):**
```bash
cd frontend
.\run.bat
```

### 5. Open Browser
Go to: **http://localhost:3000**

Your webcam feed should appear under "Main Feed"

---

## Troubleshooting

### Black Screen / No Video

**1. Allow camera permissions**
- Windows may ask for camera access
- Click "Allow"

**2. Close other apps using the camera**
- Close Zoom, Teams, Skype, Camera app
- They can block access

**3. Test camera directly**
```bash
cd backend
python -c "import cv2; cap = cv2.VideoCapture(0); print('Camera works:', cap.isOpened()); cap.release()"
```

Should print: `Camera works: True`

**4. Hard refresh browser**
- Press `Ctrl + Shift + R` to clear cache

**5. Backend needs restart**
If you ran `seed_data.py` AFTER starting the backend:
- Stop backend (Ctrl+C)
- Run `.\run.bat` again

### Different Webcam ID

If your webcam isn't device 0, edit the database:
1. Stop the backend
2. Delete `pyroguard.db`
3. Edit `backend/seed_data.py` line 21:
   ```python
   rtsp_url="0",  # Change to "1" or "2"
   ```
4. Run `python seed_data.py` again
5. Restart backend

### Performance is Slow

Normal for CPU-only systems. See `deployment_recommendations.md` for GPU upgrade options.

---

## Testing Fire Detection

1. Open the dashboard (http://localhost:3000)
2. Click on "Main Feed"
3. Use a **lighter or candle** in front of the camera
4. You should see:
   - Red bounding box around the flame
   - Fire level classification
   - Confidence score

**Note:** Small flames may need to be 6-12 inches from camera to detect.

---

## Need Help?

- Check backend terminal for error messages
- Check browser console (F12) for frontend errors
- Make sure both servers are running (backend port 8000, frontend port 3000)
