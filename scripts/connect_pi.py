import socket
import subprocess
import re
import os
import time
import paramiko
from concurrent.futures import ThreadPoolExecutor

USERNAMES = ["pyroguard", "pi"]
PASSWORDS = ["pyroguard041505", "raspberry"]

KNOWN_IPS = ["192.168.1.19", "192.168.1.2", "192.168.137.100", "192.168.1.17"]

def test_port(ip, port=22, timeout=0.6):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        return s.connect_ex((ip, port)) == 0
    except:
        return False
    finally:
        s.close()

def get_arp_ips():
    found = []
    try:
        out = subprocess.check_output(["arp", "-a"], text=True)
        for line in out.splitlines():
            line = line.strip()
            match = re.search(r"(\d+\.\d+\.\d+\.\d+)\s+([0-9a-fA-F-]+)", line)
            if match:
                ip, mac = match.groups()
                mac = mac.lower()
                if "192.168.137." in ip or any(mac.startswith(p) for p in ["dc-a6-32", "b8-27-eb", "e4-5f-01", "28-cd-c1"]):
                    if ip not in found and not ip.endswith(".255") and not ip.endswith(".1"):
                        found.append(ip)
    except Exception as e:
        print(f"[-] Error reading ARP: {e}")
    return found

def get_local_subnets():
    subnets = set()
    try:
        out = subprocess.check_output(["ipconfig"], text=True)
        for line in out.splitlines():
            m = re.search(r"IPv4 Address[.\s]+:\s+(\d+\.\d+\.\d+)\.\d+", line)
            if m:
                subnets.add(m.group(1))
    except:
        subnets.add("192.168.1")
        subnets.add("192.168.137")
    return list(subnets)

def find_pi():
    candidates = []

    # 1. Check mDNS first (fastest)
    for name in ["pyroguard.local", "raspberrypi.local"]:
        try:
            ip = socket.gethostbyname(name)
            if ip and ip not in candidates:
                print(f"[+] Resolved {name} -> {ip}")
                candidates.append(ip)
        except:
            pass

    # 2. Check ARP IPs
    for ip in get_arp_ips():
        if ip not in candidates:
            candidates.append(ip)

    # 3. Check Known IPs
    for ip in KNOWN_IPS:
        if ip not in candidates:
            candidates.append(ip)

    print(f"[*] Quick-checking known & ARP candidate IPs: {candidates}")
    for ip in candidates:
        if test_port(ip, 22, timeout=0.8):
            print(f"[+] Found active SSH on candidate IP: {ip}")
            return ip

    # 4. Fast parallel scan across all local subnets
    subnets = get_local_subnets()
    print(f"[*] Scanning active subnets {subnets} for Raspberry Pi...")
    all_ips = []
    for sub in subnets:
        for i in range(2, 255):
            all_ips.append(f"{sub}.{i}")

    with ThreadPoolExecutor(max_workers=80) as ex:
        results = [ip for ip in ex.map(lambda ip: ip if test_port(ip, 22, timeout=0.4) else None, all_ips) if ip]

    if results:
        print(f"[+] Found SSH server(s) online: {results}")
        return results[0]

    return None

def update_frontend_env(pi_ip):
    env_path = os.path.join(os.path.dirname(__file__), "frontend", ".env.local")
    if os.path.exists(env_path):
        with open(env_path, "r") as f:
            lines = f.readlines()
        new_lines = []
        updated = False
        for line in lines:
            if line.startswith("NEXT_PUBLIC_API_URL="):
                new_lines.append(f"NEXT_PUBLIC_API_URL=http://{pi_ip}:8000\n")
                updated = True
            else:
                new_lines.append(line)
        if not updated:
            new_lines.append(f"NEXT_PUBLIC_API_URL=http://{pi_ip}:8000\n")
        with open(env_path, "w") as f:
            f.writelines(new_lines)
        print(f"[+] Updated frontend/.env.local with NEXT_PUBLIC_API_URL=http://{pi_ip}:8000")

def update_ssh_config(pi_ip):
    ssh_config_path = os.path.expanduser("~/.ssh/config")
    try:
        lines = []
        if os.path.exists(ssh_config_path):
            with open(ssh_config_path, "r") as f:
                lines = f.readlines()
        
        new_lines = []
        in_pi = False
        updated = False
        for line in lines:
            if line.strip().lower() == "host pi":
                in_pi = True
                new_lines.append(line)
            elif in_pi and line.strip().lower().startswith("hostname"):
                new_lines.append(f"    HostName {pi_ip}\n")
                updated = True
                in_pi = False
            elif in_pi and line.strip().lower().startswith("host "):
                in_pi = False
                new_lines.append(line)
            else:
                new_lines.append(line)
        
        if not updated:
            new_lines.append(f"\nHost Pi\n    HostName {pi_ip}\n    User pyroguard\n")
            
        with open(ssh_config_path, "w") as f:
            f.writelines(new_lines)
        print(f"[+] Updated ~/.ssh/config Host Pi to {pi_ip}")
    except Exception as e:
        print(f"[-] Could not update ~/.ssh/config: {e}")

def start_backend(pi_ip):
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    
    connected = False
    for u in USERNAMES:
        for p in PASSWORDS:
            try:
                print(f"[*] Trying SSH login: {u}@{pi_ip}...")
                client.connect(pi_ip, username=u, password=p, timeout=6)
                connected = True
                print(f"[+] Connected to Raspberry Pi as {u}!")
                break
            except Exception as e:
                continue
        if connected:
            break

    if not connected:
        print("[-] SSH login failed with standard credentials.")
        return False

    script_content = """#!/bin/bash
while fuser -s /home/pyroguard/pyro-guard/backend/venv/bin/pip 2>/dev/null; do
    sleep 3
done
cd /home/pyroguard/pyro-guard/backend
pkill -f uvicorn
nohup venv/bin/python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 > backend.log 2>&1 &
"""
    print("[*] Deploying and starting PYRO-GUARD backend on Raspberry Pi...")
    stdin, stdout, stderr = client.exec_command("cat > /home/pyroguard/pyro-guard/backend/start_wait.sh")
    stdin.write(script_content)
    stdin.channel.shutdown_write()
    stdout.channel.recv_exit_status()

    client.exec_command("chmod +x /home/pyroguard/pyro-guard/backend/start_wait.sh")
    client.exec_command("nohup /home/pyroguard/pyro-guard/backend/start_wait.sh > /dev/null 2>&1 &")

    print("[+] Backend started successfully on the Raspberry Pi!")
    print(f"[+] API URL: http://{pi_ip}:8000")
    print(f"[+] Docs URL: http://{pi_ip}:8000/docs")
    client.close()
    return True

if __name__ == "__main__":
    print("=" * 60)
    print(" PYRO-GUARD Raspberry Pi Smart Connect & Start ")
    print("=" * 60)
    pi_ip = find_pi()
    if not pi_ip:
        print("\n[-] Raspberry Pi could not be found yet.")
        print("[!] Next Steps:")
        print("    1. Put SD card into Raspberry Pi and turn it ON with wall charger.")
        print("    2. Wait 30-45 seconds for it to boot and join Wi-Fi.")
        print("    3. Run this script again: python connect_pi.py")
    else:
        update_frontend_env(pi_ip)
        update_ssh_config(pi_ip)
        start_backend(pi_ip)
