import os
import sys
import paramiko
from pathlib import Path

PI_IP = "192.168.1.15"
PI_USER = "pyroguard"
PI_PASS = "pyroguard041505"

LOCAL_ROOT = Path(__file__).resolve().parent.parent
LOCAL_BACKEND = LOCAL_ROOT / "backend"
REMOTE_BASE = "/home/pyroguard/pyro-guard"
REMOTE_BACKEND = f"{REMOTE_BASE}/backend"

print("=" * 60)
print(" PYRO-GUARD Deployment to Raspberry Pi")
print("=" * 60)

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
try:
    print(f"[*] Connecting to {PI_USER}@{PI_IP}...")
    client.connect(PI_IP, username=PI_USER, password=PI_PASS, timeout=10)
    print("[+] SSH connection established!")
except Exception as e:
    print(f"[-] Connection failed: {e}")
    sys.exit(1)

# 1. Stop any running backend and remove old models / old repo
print("\n[*] Stopping any running processes and cleaning old backend/models...")
clean_cmds = [
    "pkill -f uvicorn || true",
    f"rm -rf {REMOTE_BACKEND}/models",
    "sudo find /home /opt /tmp -name '*fire_yolov8*' -exec rm -rf {} + 2>/dev/null || true",
    f"mkdir -p {REMOTE_BACKEND}/models",
    f"mkdir -p {REMOTE_BACKEND}/detections",
]
for cmd in clean_cmds:
    stdin, stdout, stderr = client.exec_command(cmd)
    stdout.channel.recv_exit_status()
print("[+] Old models and processes cleared on Pi!")

# 2. Open SFTP session
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
        if "__pycache__" in root or "runs" in root or "venv" in root:
            continue
        rel = Path(root).relative_to(local_dir)
        target_dir = f"{remote_dir}/{rel}".replace("\\", "/")
        ensure_remote_dir(target_dir)

        for f in files:
            if f.endswith(".pyc") or f == "backend.log":
                continue
            local_file = Path(root) / f
            remote_file = f"{target_dir}/{f}".replace("\\", "/")
            print(f"  -> Uploading: {rel / f if str(rel) != '.' else f}")
            sftp.put(str(local_file), remote_file)

print("\n[*] Uploading fresh backend code and models to Raspberry Pi...")
# Upload app directory
print("[*] Uploading app/ directory...")
upload_dir(LOCAL_BACKEND / "app", f"{REMOTE_BACKEND}/app")

# Upload models directory
print("[*] Uploading new models/ directory (PyTorch + NCNN)...")
upload_dir(LOCAL_BACKEND / "models", f"{REMOTE_BACKEND}/models")

# Upload config and database files
files_to_copy = ["requirements.txt", "pyroguard.db", "package.json"]
for fname in files_to_copy:
    fpath = LOCAL_BACKEND / fname
    if fpath.exists():
        print(f"  -> Uploading: {fname}")
        sftp.put(str(fpath), f"{REMOTE_BACKEND}/{fname}")

# Prepare .env for Raspberry Pi (HARDWARE_MODE=raspberry_pi)
env_path = LOCAL_BACKEND / ".env"
if env_path.exists():
    with open(env_path, "r", encoding="utf-8") as f:
        env_content = f.read()
    # Ensure hardware mode is set for Raspberry Pi hardware
    if "HARDWARE_MODE=pc" in env_content:
        env_content = env_content.replace("HARDWARE_MODE=pc", "HARDWARE_MODE=raspberry_pi")
    
    remote_env = f"{REMOTE_BACKEND}/.env"
    with sftp.open(remote_env, "w") as f:
        f.write(env_content)
    print("  -> Uploaded .env (configured for HARDWARE_MODE=raspberry_pi)")

sftp.close()
print("[+] All files uploaded successfully!")

# 3. Create start script on Pi
start_script = f"""#!/bin/bash
cd {REMOTE_BACKEND}
if [ ! -d "venv" ]; then
    echo "Creating virtual environment on Raspberry Pi..."
    python3 -m venv venv --system-site-packages
fi

echo "Installing/verifying dependencies..."
venv/bin/pip install --upgrade pip
venv/bin/pip install -r requirements.txt

echo "Starting Pyro-Guard Backend..."
pkill -f uvicorn || true
nohup venv/bin/python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 > backend.log 2>&1 &
echo "Started with PID $!"
"""

start_sh_path = f"{REMOTE_BACKEND}/start.sh"
stdin, stdout, stderr = client.exec_command(f"cat > {start_sh_path} << 'EOF'\n{start_script}\nEOF\nchmod +x {start_sh_path}")
stdout.channel.recv_exit_status()

print(f"[+] Created start script at {start_sh_path}")
print("[*] Launching backend on Raspberry Pi...")
client.exec_command(f"nohup {start_sh_path} > {REMOTE_BACKEND}/setup.log 2>&1 &")

print("\n" + "=" * 60)
print(f"🎉 Deployment completed!")
print(f"Backend is initializing on: http://{PI_IP}:8000")
print(f"Check setup logs on Pi anytime via SSH.")
print("=" * 60)

client.close()
