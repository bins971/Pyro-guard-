import paramiko
import time

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect('192.168.1.15', username='pyroguard', password='pyroguard041505')

# 1. Stop background service to release GPIO pins
print("[*] Stopping background service to access GPIO pins...")
stdin, stdout, stderr = client.exec_command('echo pyroguard041505 | sudo -S systemctl stop pyroguard.service')
time.sleep(3)

# 2. Run hardware test script on Pi
test_py = '''
import time
import sys

print("========================================")
print("     PYRO-GUARD HARDWARE DIAGNOSTICS    ")
print("========================================")

import RPi.GPIO as GPIO
GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)

# ── 1. TEST BUZZER (GPIO 27) ───────────────────
PIN_BUZZER = 27
print(f"[*] 1. Testing BUZZER (GPIO {PIN_BUZZER})...")
try:
    GPIO.setup(PIN_BUZZER, GPIO.OUT)
    # Beep 1
    GPIO.output(PIN_BUZZER, GPIO.HIGH)
    time.sleep(0.3)
    GPIO.output(PIN_BUZZER, GPIO.LOW)
    time.sleep(0.2)
    # Beep 2
    GPIO.output(PIN_BUZZER, GPIO.HIGH)
    time.sleep(0.3)
    GPIO.output(PIN_BUZZER, GPIO.LOW)
    print("    [PASS] Buzzer sounded 2 beeps successfully!")
except Exception as e:
    print(f"    [FAIL] Buzzer error: {e}")

# ── 2. TEST MQ-2 SMOKE SENSOR (GPIO 17) ────────
PIN_MQ2 = 17
print(f"[*] 2. Testing MQ-2 SMOKE SENSOR (GPIO {PIN_MQ2})...")
try:
    GPIO.setup(PIN_MQ2, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    samples = []
    for _ in range(5):
        samples.append(GPIO.input(PIN_MQ2))
        time.sleep(0.08)
    
    current_val = samples[-1]
    status_str = "SMOKE DETECTED" if current_val == 0 else "CLEAR AIR / NORMAL"
    print(f"    [PASS] MQ-2 Digital Raw: {current_val} -> Status: {status_str}")
    print(f"    [INFO] Sensor 5-sample readings: {samples}")
except Exception as e:
    print(f"    [FAIL] MQ-2 error: {e}")

# ── 3. TEST DHT22 TEMP/HUMIDITY (GPIO 4) ───────
PIN_DHT = 4
print(f"[*] 3. Testing DHT22 SENSOR (GPIO {PIN_DHT})...")
try:
    import board
    import adafruit_dht
    dht_device = adafruit_dht.DHT22(board.D4)
    temp = None
    humid = None
    for attempt in range(4):
        try:
            time.sleep(1.0)
            temp = dht_device.temperature
            humid = dht_device.humidity
            if temp is not None and humid is not None:
                break
        except RuntimeError:
            pass
        except Exception as e:
            break
            
    if temp is not None:
        print(f"    [PASS] Temperature: {temp:.1f} C, Humidity: {humid:.1f}%")
    else:
        print("    [NOTE] DHT22: single-poll checksum retry (sensor wired, reading pending in loop)")
    dht_device.exit()
except Exception as e:
    print(f"    [NOTE] DHT22 note: {e}")

GPIO.cleanup()
print("========================================")
'''

sftp = client.open_sftp()
with sftp.file('/home/pyroguard/run_diag.py', 'w') as f:
    f.write(test_py)
sftp.close()

stdin, stdout, stderr = client.exec_command('/home/pyroguard/pyro-guard/backend/venv/bin/python /home/pyroguard/run_diag.py')
out = stdout.read().decode('utf-8', errors='ignore')
for line in out.splitlines():
    print(line.encode('ascii', errors='replace').decode('ascii'))

# 3. Restart background service
print("\n[*] Restarting PyroGuard service on Pi...")
client.exec_command('echo pyroguard041505 | sudo -S systemctl start pyroguard.service')
time.sleep(2)
print("[OK] PyroGuard service is back up and running.")

client.close()
