import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('192.168.1.21', username='pyroguard', password='pyroguard041505', timeout=5)

# 1. Inspect recent detections in database
check_cmd = """/home/pyroguard/pyro-guard/backend/venv/bin/python3 -c "
import sqlite3
conn = sqlite3.connect('/home/pyroguard/pyro-guard/backend/pyroguard.db')
c = conn.cursor()
c.execute('SELECT COUNT(*) FROM detections WHERE confidence >= 0.400 AND confidence <= 0.402')
print('Matches with ~0.400 conf (color fallback):', c.fetchone()[0])
c.execute('SELECT id, timestamp, confidence, fire_level FROM detections ORDER BY id DESC LIMIT 8')
for r in c.fetchall():
    print(r)
" """
stdin, stdout, stderr = ssh.exec_command(check_cmd)
print("=== DB INSPECTION ===")
print(stdout.read().decode('utf-8', errors='replace'))

# 2. Update .env on Pi to disable color fallback and enforce strict neural verification
print("=== UPDATING .ENV ON PI ===")
update_env_cmd = """/home/pyroguard/pyro-guard/backend/venv/bin/python3 -c "
path = '/home/pyroguard/pyro-guard/backend/.env'
with open(path, 'r') as f:
    content = f.read()

# Disable color fallback
content = content.replace('ENABLE_COLOR_FALLBACK=true', 'ENABLE_COLOR_FALLBACK=false')
content = content.replace('ENABLE_COLOR_FALLBACK=True', 'ENABLE_COLOR_FALLBACK=false')

# Require genuine YOLO confidence
content = content.replace('CONFIDENCE_THRESHOLD=0.25', 'CONFIDENCE_THRESHOLD=0.35')
content = content.replace('SMALL_FIRE_CONFIDENCE_THRESHOLD=0.25', 'SMALL_FIRE_CONFIDENCE_THRESHOLD=0.35')

# Enable temporal flicker verification to reject static objects
content = content.replace('ENABLE_FLICKER_VERIFICATION=false', 'ENABLE_FLICKER_VERIFICATION=true')

# Persistence frames: require 3 consecutive frames
content = content.replace('DETECTION_PERSISTENCE_FRAMES=2', 'DETECTION_PERSISTENCE_FRAMES=3')

with open(path, 'w') as f:
    f.write(content)
print('Pi .env successfully updated!')
" """
stdin, stdout, stderr = ssh.exec_command(update_env_cmd)
print(stdout.read().decode('utf-8', errors='replace'))
print(stderr.read().decode('utf-8', errors='replace'))

# 3. Clean up the recent false alarm detections from the database (from 23:00 onwards today)
print("=== CLEANING FALSE DETECTIONS FROM DB ===")
cleanup_db_cmd = """/home/pyroguard/pyro-guard/backend/venv/bin/python3 -c "
import sqlite3
conn = sqlite3.connect('/home/pyroguard/pyro-guard/backend/pyroguard.db')
c = conn.cursor()
c.execute('DELETE FROM detections WHERE confidence >= 0.400 AND confidence <= 0.402')
deleted = c.rowcount
conn.commit()
print(f'Deleted {deleted} false color-fallback detections from database.')
" """
stdin, stdout, stderr = ssh.exec_command(cleanup_db_cmd)
print(stdout.read().decode('utf-8', errors='replace'))

# 4. Restart pyroguard.service on Pi
print("=== RESTARTING PYROGUARD SERVICE ===")
stdin, stdout, stderr = ssh.exec_command('echo pyroguard041505 | sudo -S systemctl restart pyroguard.service')
exit_code = stdout.channel.recv_exit_status()
print(f'Restart exit code: {exit_code}')

# 5. Check service status
stdin, stdout, stderr = ssh.exec_command('systemctl is-active pyroguard.service')
print('Service active:', stdout.read().decode().strip())

ssh.close()
