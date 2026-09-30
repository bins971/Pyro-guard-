import os
import sys
import paramiko
from pathlib import Path

import socket

PI_IP = "10.112.96.27"
for h in ["pyroguard.local", "10.112.96.27", "192.168.1.21"]:
    try:
        resolved = socket.gethostbyname(h)
        s = socket.socket()
        s.settimeout(0.8)
        if s.connect_ex((resolved, 22)) == 0:
            PI_IP = resolved
            s.close()
            break
        s.close()
    except Exception:
        pass

PI_USER = "pyroguard"
PI_PASS = "pyroguard041505"

LOCAL_ROOT = Path(__file__).resolve().parent.parent
LOCAL_APP = LOCAL_ROOT / "backend" / "app"
REMOTE_BASE = "/home/pyroguard/pyro-guard"
REMOTE_APP = f"{REMOTE_BASE}/backend/app"

print("=" * 60)
print(f"Deploying updated app code and config to Pi ({PI_IP})...")
print("=" * 60)

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(PI_IP, username=PI_USER, password=PI_PASS, timeout=10)

sftp = client.open_sftp()

def ensure_remote_dir(remote_dir):
    parts = remote_dir.strip("/").split("/")
    cur = ""
    for p in parts:
        cur += "/" + p
        try:
            sftp.stat(cur)
        except IOError:
            try:
                sftp.mkdir(cur)
            except IOError:
                pass

def upload_dir(local_dir: Path, remote_dir: str):
    ensure_remote_dir(remote_dir)
    for root, dirs, files in os.walk(local_dir):
        if "__pycache__" in root:
            continue
        rel = Path(root).relative_to(local_dir)
        target_dir = f"{remote_dir}/{rel}".replace("\\", "/")
        ensure_remote_dir(target_dir)

        for f in files:
            if f.endswith(".pyc"):
                continue
            local_file = Path(root) / f
            remote_file = f"{target_dir}/{f}".replace("\\", "/")
            print(f"  -> Uploading: {rel / f if str(rel) != '.' else f}")
            sftp.put(str(local_file), remote_file)

# Stop service and kill any lingering processes to avoid port 8000 or /dev/video0 conflict
print("[*] Stopping service and clearing any lingering processes...")
stop_cmd = f"echo '{PI_PASS}' | sudo -S systemctl stop pyroguard.service; sleep 1; echo '{PI_PASS}' | sudo -S pkill -9 -f uvicorn || true"
client.exec_command(stop_cmd)[1].read()

upload_dir(LOCAL_APP, REMOTE_APP)
print("  -> Uploading: backend/.env")
sftp.put(str(LOCAL_ROOT / "backend" / ".env"), f"{REMOTE_BASE}/backend/.env")
sftp.close()

# Ensure HARDWARE_MODE=raspberry_pi in remote .env
client.exec_command(f"sed -i 's/^HARDWARE_MODE=.*/HARDWARE_MODE=raspberry_pi/' {REMOTE_BASE}/backend/.env")[1].read()

# Ensure cameras are properly active in database
ensure_cam_cmd = """python3 -c "
import sqlite3
conn = sqlite3.connect('/home/pyroguard/pyro-guard/backend/pyroguard.db')
tapo_url = 'rtsp://pyroguard:pyroguard041505@192.168.1.12:554/stream2'
conn.execute('''
    UPDATE cameras 
    SET name='Tapo C200C', location='Surveillance', rtsp_url=?, is_active=1 
    WHERE id=1
''', (tapo_url,))
conn.execute('''
    UPDATE cameras 
    SET is_active=1 
    WHERE id=0
''')
conn.commit()
print('Cameras in DB:', conn.execute('SELECT id, name, is_active FROM cameras').fetchall())
" """
stdin, stdout, stderr = client.exec_command(ensure_cam_cmd)
print(stdout.read().decode().strip())

# Start pyroguard systemd service on Pi
print("\n[*] Starting pyroguard.service on Pi...")
restart_cmd = f"echo '{PI_PASS}' | sudo -S systemctl start pyroguard.service && sleep 3 && systemctl is-active pyroguard.service"
stdin, stdout, stderr = client.exec_command(restart_cmd)
status_output = stdout.read().decode().strip()
print(f"[+] Service status: {status_output}")

# Tail log
_, stdout, _ = client.exec_command("tail -n 25 /home/pyroguard/pyro-guard/backend/backend.log")
print("\n--- Recent Logs ---")
print(stdout.read().decode('utf-8', errors='replace'))

client.close()
print("\n[+] Pi backend update and restart complete!")
