import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('192.168.1.21', username='pyroguard', password='pyroguard041505', timeout=5)

def run(cmd):
    stdin, stdout, stderr = ssh.exec_command(cmd)
    out = stdout.read().decode('utf-8', errors='replace').strip()
    err = stderr.read().decode('utf-8', errors='replace').strip()
    return out, err

# 1. Delete existing Kiel profile if present to ensure clean config
run('echo pyroguard041505 | sudo -S nmcli connection delete "Kiel"')

# 2. Add connection profile
out, err = run('echo pyroguard041505 | sudo -S nmcli connection add type wifi con-name "Kiel" ifname wlan0 ssid "Kiel"')
print("ADD RESULT:", out)

# 3. Set password and security
run('echo pyroguard041505 | sudo -S nmcli connection modify "Kiel" wifi-sec.key-mgmt wpa-psk wifi-sec.psk "kiel123456"')

# 4. Set autoconnect and priority
run('echo pyroguard041505 | sudo -S nmcli connection modify "Kiel" connection.autoconnect yes connection.autoconnect-priority 10')

# 5. Verify connections
out, _ = run('echo pyroguard041505 | sudo -S nmcli connection show')
print("=== CONNECTIONS ===")
print(out)

# 6. Verify Kiel details
out, _ = run('echo pyroguard041505 | sudo -S nmcli -f connection.id,connection.autoconnect,connection.autoconnect-priority,802-11-wireless.ssid connection show "Kiel"')
print("=== KIEL PROFILE DETAILS ===")
print(out)

ssh.close()
