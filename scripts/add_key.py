import paramiko
import os

host = "192.168.1.2"
usernames = ["pyroguard", "PyroGuard"]
passwords = ["PYROGUARD041505", "pyroguard041505"]
key_path = os.path.expanduser("~/.ssh/id_ed25519.pub")

with open(key_path, "r") as f:
    pub_key = f.read().strip()

print(f"Connecting to {host}...")
client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

success = False
for u in usernames:
    for p in passwords:
        try:
            print(f"Trying username={u}, password={p}...")
            client.connect(host, username=u, password=p, timeout=5)
            print(f"Success with username={u}, password={p}!")
            success = True
            
            print("Adding SSH key...")
            command = f"mkdir -p ~/.ssh && echo '{pub_key}' >> ~/.ssh/authorized_keys && chmod 700 ~/.ssh && chmod 600 ~/.ssh/authorized_keys"
            stdin, stdout, stderr = client.exec_command(command)
            stdout.channel.recv_exit_status()
            print("Key added.")
            break
        except paramiko.AuthenticationException:
            pass
        except Exception as e:
            print(f"Error: {e}")
            
    if success:
        break

if not success:
    print("All combinations failed.")
client.close()
