## Requirements

You'll need:
- Python 3.10 or newer
- Node.js 18+
- A webcam or IP camera

## Setup

### Backend

```bash
cd backend
pip install -r requirements.txt
copy .env.example .env
```

### Frontend

```bash
cd frontend
npm install
copy .env.example .env.local
```

## Running it

Just use the batch files:

```bash
# Backend
cd backend
.\run.bat

# Frontend (separate terminal)
cd frontend
.\run.bat
```

Then open http://localhost:3000 in your browser.

## Testing

Start everything up, go to the dashboard, and use a lighter or candle in front of your camera. You should see bounding boxes appear around the flame.



**Dependencies won't install**: Try upgrading pip first
```bash
pip install --upgrade pip
```

## Dependencies

Backend uses FastAPI, YOLOv8, OpenCV, PyTorch, and SQLAlchemy.
Frontend is Next.js with TypeScript and Tailwind.

Full list in `requirements.txt` and `package.json`.
