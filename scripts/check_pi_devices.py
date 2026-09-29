import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('192.168.1.21', username='pyroguard', password='pyroguard041505', timeout=5)

cmd = """
echo "=== VIDEO DEVICES ==="
ls -l /dev/video* 2>/dev/null || echo "No /dev/video* found"
echo "=== CAMERAS IN DB ==="
sqlite3 /home/pyroguard/pyro-guard/backend/pyroguard.db "SELECT id, name, rtsp_url, is_active FROM cameras;" 2>/dev/null || echo "Cannot read DB"
echo "=== MODELS ON PI ==="
ls -lh /home/pyroguard/pyro-guard/backend/models/
"""

stdin, stdout, stderr = ssh.exec_command(cmd)
print(stdout.read().decode('utf-8', errors='replace'))
print('ERR:', stderr.read().decode('utf-8', errors='replace'))
ssh.close()
