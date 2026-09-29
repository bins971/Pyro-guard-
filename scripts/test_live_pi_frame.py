import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('192.168.1.21', username='pyroguard', password='pyroguard041505', timeout=5)

test_script = """
import sys
sys.path.insert(0, '/home/pyroguard/pyro-guard/backend')
import cv2
from app.detection.detector import FireDetector
from app.config import settings

det = FireDetector()
cap = cv2.VideoCapture(0)
ret, frame = cap.read()
cap.release()

if ret:
    print('Frame shape:', frame.shape)
    settings.ENABLE_COLOR_FALLBACK = False
    boxes, lvl, conf = det.detect(frame, camera_id=1)
    print('YOLO ONLY: boxes=', len(boxes), 'level=', lvl, 'conf=', conf)
    for b in boxes:
        print('  YOLO Box:', b)
        
    settings.ENABLE_COLOR_FALLBACK = True
    c_boxes, c_lvl, c_conf = det.detect(frame, camera_id=1)
    print('WITH COLOR FALLBACK: boxes=', len(c_boxes), 'level=', c_lvl, 'conf=', c_conf)
    for b in c_boxes:
        print('  Color Box:', b)
else:
    print('Failed to grab frame from /dev/video0')
"""

sftp = ssh.open_sftp()
with sftp.file('/tmp/test_frame.py', 'w') as f:
    f.write(test_script)
sftp.close()

stdin, stdout, stderr = ssh.exec_command('/home/pyroguard/pyro-guard/backend/venv/bin/python3 /tmp/test_frame.py')
print(stdout.read().decode('utf-8', errors='replace'))
print('ERR:', stderr.read().decode('utf-8', errors='replace'))
ssh.close()
