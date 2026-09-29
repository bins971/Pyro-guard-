import paramiko

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect('192.168.1.21', username='pyroguard', password='pyroguard041505', timeout=5)

remote_py = """
import time, torch, numpy as np
from ultralytics import YOLO

m = YOLO('/home/pyroguard/pyro-guard/backend/models/fire_yolov8.pt')
torch.set_num_threads(2)
dummy = np.zeros((480, 640, 3), dtype=np.uint8)

# warm up
m(dummy, imgsz=480, verbose=False)

for sz in [320, 416, 480, 640]:
    t0 = time.time()
    for _ in range(5):
        m(dummy, imgsz=sz, verbose=False)
    el = (time.time() - t0) / 5
    print(f'imgsz={sz}: {el*1000:.1f}ms ({1/el:.1f} FPS)')
"""

stdin, stdout, stderr = client.exec_command(f"/home/pyroguard/pyro-guard/backend/venv/bin/python3 -c \"{remote_py}\"")
print(stdout.read().decode())
print(stderr.read().decode())
client.close()
