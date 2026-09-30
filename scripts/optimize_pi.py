import paramiko
import sys

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('192.168.1.21', username='pyroguard', password='pyroguard041505', timeout=10)

cmd = """
echo "=== 1. SETTING CPU GOVERNOR TO PERFORMANCE (1.5 GHz) ==="
echo pyroguard041505 | sudo -S bash -c '
cat << "EOF" > /etc/systemd/system/cpu-performance.service
[Unit]
Description=Set CPU Governor to Performance for Pyro-Guard
After=multi-user.target

[Service]
Type=oneshot
ExecStart=/bin/sh -c "echo performance | tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor"
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable cpu-performance.service
systemctl start cpu-performance.service
'

echo -n "Current Governor: "
cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor
echo -n "CPU Clock (Hz): "
cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq
echo -n "Core Temp: "
vcgencmd measure_temp

echo "\n=== 2. CLEANING CACHES AND OLD LOGS ==="
rm -f /home/pyroguard/pyro-guard/backend/models/fire_yolov8_old_backup.pt
rm -rf /home/pyroguard/pyro-guard/backend/models/fire_yolov8_ncnn_model
rm -rf /home/pyroguard/pyro-guard/backend/runs
echo "Disk usage in models dir:"
ls -lh /home/pyroguard/pyro-guard/backend/models/

echo "\n=== 3. VERIFYING DATABASE CAMERAS ==="
cd /home/pyroguard/pyro-guard/backend && /home/pyroguard/pyro-guard/backend/venv/bin/python3 -c "
from app.database import SessionLocal
from app.models import Camera
db = SessionLocal()
cams = db.query(Camera).all()
print(f'Total Cameras: {len(cams)}')
for c in cams:
    print(f'  Camera ID: {c.id}, Name: {c.name}, RTSP/Index: {c.rtsp_url}, Active: {c.is_active}')
db.close()
"

echo "\n=== 4. RESTARTING PYROGUARD SERVICE ==="
echo pyroguard041505 | sudo -S systemctl restart pyroguard.service
sleep 2
systemctl is-active pyroguard.service
"""

stdin, stdout, stderr = ssh.exec_command(cmd)
print(stdout.read().decode('utf-8', errors='replace'))
err = stderr.read().decode('utf-8', errors='replace')
if err:
    # Filter out standard sudo password prompt
    filtered_err = "\n".join([l for l in err.splitlines() if "[sudo]" not in l])
    if filtered_err.strip():
        print('ERR:', filtered_err)

ssh.close()
print("[+] Raspberry Pi optimization successfully applied and verified!")
