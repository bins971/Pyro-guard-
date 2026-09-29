import paramiko

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect('192.168.1.21', username='pyroguard', password='pyroguard041505', timeout=5)

def run_cmd(title, cmd):
    print(f"=== {title} ===")
    stdin, stdout, stderr = client.exec_command(cmd)
    out = stdout.read().decode('utf-8', 'ignore').strip()
    err = stderr.read().decode('utf-8', 'ignore').strip()
    safe_out = out.encode('ascii', 'replace').decode()
    safe_err = err.encode('ascii', 'replace').decode()
    if safe_out:
        print(safe_out)
    if safe_err:
        print("ERR:", safe_err)

# 1. Config
run_cmd("1. config.py settings on Pi", 
        "cd /home/pyroguard/pyro-guard/backend && venv/bin/python3 -c \"from app.config import settings; print('INFERENCE_SIZE:', settings.INFERENCE_SIZE); print('CONFIDENCE_THRESHOLD:', settings.CONFIDENCE_THRESHOLD); print('ENABLE_COLOR_FALLBACK:', settings.ENABLE_COLOR_FALLBACK); print('DETECTION_PERSISTENCE_FRAMES:', settings.DETECTION_PERSISTENCE_FRAMES)\"")

# 2. Classifier
run_cmd("2. classifier.py severity names on Pi", 
        "cd /home/pyroguard/pyro-guard/backend && venv/bin/python3 -c \"from app.detection.classifier import FireLevelClassifier; c = FireLevelClassifier(); print('Level 1:', c.get_level_description(1)); print('Level 2:', c.get_level_description(2)); print('Level 3:', c.get_level_description(3))\"")

# 3. Alert Service
run_cmd("3. alert_service.py severity names on Pi",
        "grep -A 4 'level_names = {' /home/pyroguard/pyro-guard/backend/app/services/alert_service.py | head -n 5")

# 4. Service status & uptime
run_cmd("4. pyroguard.service status",
        "systemctl status pyroguard.service | head -n 6")

client.close()
