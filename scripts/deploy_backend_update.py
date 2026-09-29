import os
import sys
import paramiko
from pathlib import Path

PI_IP = "192.168.1.21"
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

upload_dir(LOCAL_APP, REMOTE_APP)
print("  -> Uploading: backend/.env")
sftp.put(str(LOCAL_ROOT / "backend" / ".env"), f"{REMOTE_BASE}/backend/.env")
sftp.close()

# Restart pyroguard systemd service on Pi
print("\n[*] Restarting pyroguard.service on Pi...")
restart_cmd = f"echo '{PI_PASS}' | sudo -S systemctl restart pyroguard.service && sleep 2 && systemctl is-active pyroguard.service"
stdin, stdout, stderr = client.exec_command(restart_cmd)
status_output = stdout.read().decode().strip()
print(f"[+] Service status: {status_output}")

client.close()
print("[+] Pi backend update and restart complete!")
