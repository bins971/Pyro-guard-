import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('192.168.1.21', username='pyroguard', password='pyroguard041505', timeout=5)

cmd = """
echo "=== 1. CLEANING REDUNDANT FILES ON PI ==="
rm -f /home/pyroguard/pyro-guard/backend/models/fire_yolov8_old_backup.pt
rm -rf /home/pyroguard/pyro-guard/backend/models/fire_yolov8_ncnn_model
rm -rf /home/pyroguard/pyro-guard/backend/runs
rm -f /home/pyroguard/pyro-guard/backend/*.log
rm -f /home/pyroguard/pyro-guard/backend.log

echo "=== 2. MODELS REMAINING ON PI ==="
ls -lh /home/pyroguard/pyro-guard/backend/models/

echo "=== 3. CHECKING PYTHON CAMERAS DB ==="
/home/pyroguard/pyro-guard/backend/venv/bin/python3 -c "
from app.database import SessionLocal
from app.models import Camera
db = SessionLocal()
cams = db.query(Camera).all()
print(f'Total Cameras: {len(cams)}')
for c in cams:
    print(f'  ID: {c.id}, Name: {c.name}, RTSP: {c.rtsp_url}, Active: {c.is_active}')
db.close()
"

echo "=== 4. RESTARTING PYROGUARD SERVICE ==="
sudo systemctl restart pyroguard.service
sleep 2
systemctl status pyroguard.service | head -n 8
"""

stdin, stdout, stderr = ssh.exec_command(cmd)
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
print(stdout.read().decode('utf-8', errors='replace'))
print('ERR:', stderr.read().decode('utf-8', errors='replace'))
ssh.close()
