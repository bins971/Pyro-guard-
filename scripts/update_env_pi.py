import paramiko, time

PI_IP = "192.168.1.21"
PI_USER = "pyroguard"
PI_PASS = "pyroguard041505"

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(PI_IP, username=PI_USER, password=PI_PASS, timeout=10)

# Upload backend/.env to Pi directly
sftp = c.open_sftp()
sftp.put("backend/.env", "/home/pyroguard/pyro-guard/backend/.env")
sftp.close()

stdin, stdout, stderr = c.exec_command("grep FRAME_ /home/pyroguard/pyro-guard/backend/.env")
print("Pi .env updated:\n", stdout.read().decode())

# Stop and restart cleanly
c.exec_command(f"echo {PI_PASS} | sudo -S systemctl stop pyroguard.service")
c.exec_command(f"echo {PI_PASS} | sudo -S pkill -9 -f uvicorn")
time.sleep(2)

print("Starting pyroguard.service...")
stdin, stdout, stderr = c.exec_command(f"echo {PI_PASS} | sudo -S systemctl start pyroguard.service")
stdout.channel.recv_exit_status()
time.sleep(3)

stdin, stdout, stderr = c.exec_command("systemctl is-active pyroguard.service")
print("pyroguard.service:", stdout.read().decode().strip())
c.close()
