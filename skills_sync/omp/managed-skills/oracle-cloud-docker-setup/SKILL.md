---
name: oracle-cloud-docker-setup
description: "How to securely deploy Docker on Oracle Cloud Free Tier, handle dual firewalls (including programmatic OCI CLI updates), prevent the instance from being deleted by the Idle Reclaim policy, and bypass KasmVNC HTTP secure context blocks."
---

## Origem
Criada a partir do contexto: `/home/lucas/Downloads/codex_luascfl_jarvis`

# Oracle Cloud Free Tier - Docker Setup & Anti-Idle Procedure

When deploying Docker applications on Oracle Cloud's Always Free instances (especially `VM.Standard.E2.1.Micro` or `VM.Standard.A1.Flex`), you must address specific cloud-provider quirks: extremely slow IO/CPU causing package manager timeouts, dual-layer firewalls, and aggressive idle instance reclamation.

## 1. Uninterruptible Setup Script (Bypassing Timeouts)
The E2.1.Micro instances are slow. Running `apt upgrade` or installing Docker interactively via SSH tools often causes a 300s timeout, leaving the `dpkg` frontend locked. To avoid this, wrap the setup in a detached background block `( ... ) > log.txt 2>&1 &` and use the official Docker curl script.

```bash
cat << 'EOF' > finish_setup.sh
#!/bin/bash
(
  export DEBIAN_FRONTEND=noninteractive
  # Wait out any existing locks from interrupted sessions
  while sudo fuser /var/lib/dpkg/lock-frontend >/dev/null 2>&1 || sudo fuser /var/lib/dpkg/lock >/dev/null 2>&1; do
    sleep 5
  done
  
  sudo dpkg --configure -a
  curl -fsSL https://get.docker.com | sudo sh
  sudo apt-get install -y docker-compose || (sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose && sudo chmod +x /usr/local/bin/docker-compose)
  sudo systemctl enable --now docker
  
  # Add your docker-compose up here
) > /home/ubuntu/setup_log.txt 2>&1 &
EOF
ssh -i ~/.ssh/oracle_key ubuntu@IP 'bash ~/finish_setup.sh'
```

## 2. Oracle Idle Reclaim Prevention
Oracle Cloud actively reclaims and deletes "Always Free" instances that it considers idle (CPU < 10% for 7 days, Network < 10%, Memory < 10%). To prevent this, schedule a cronjob that artificially spikes CPU usage for a few seconds.

```bash
# Inside the VM
cat << 'EOF' > ~/anti-idle.sh
#!/bin/bash
timeout 45s dd if=/dev/urandom of=/dev/null
EOF
chmod +x ~/anti-idle.sh
(crontab -l 2>/dev/null | grep -v "anti-idle.sh"; echo "*/30 * * * * /bin/bash /home/ubuntu/anti-idle.sh >/dev/null 2>&1") | crontab -
```

## 3. Dual-Layer Firewall Configuration
Opening a port requires changes in TWO places. Failing to do both means the application will be unreachable.

**Layer 1: OS Firewall (Iptables/UFW)**
Oracle's default Ubuntu images use strict iptables rules. Simply using `ufw allow` is often not enough because `iptables` takes precedence. Run this in the VM:
```bash
sudo ufw allow <PORT>/tcp 2>/dev/null || true
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport <PORT> -j ACCEPT
sudo netfilter-persistent save 2>/dev/null || true
```

**Layer 2: Oracle VCN Ingress Rules (Via OCI CLI)**
If the local machine has the `oci` CLI configured, you can programmatically inject rules into the VCN Security List. Because `oci network security-list update` expects the entire array of rules, you MUST fetch them, append the new rule locally, and push the full list back.

```bash
# 1. Get the IDs
COMPARTMENT_ID=$(cat ~/.oci/config | grep "tenancy=" | cut -d'=' -f2) # or via oci iam compartment list
VCN_ID=$(oci network vcn list --compartment-id $COMPARTMENT_ID --query "data[0].id" --raw-output)
SEC_LIST_ID=$(oci network security-list list --compartment-id $COMPARTMENT_ID --vcn-id $VCN_ID --query "data[0].id" --raw-output)

# 2. Fetch existing rules
oci network security-list get --security-list-id $SEC_LIST_ID > sec_list.json

# 3. Append your new rule in python (or jq)
cat << 'EOF' > update_rules.py
import json
with open("sec_list.json", "r") as f:
    rules = json.load(f)["data"].get("ingress-security-rules", [])

rules.append({
    "source": "0.0.0.0/0", "source-type": "CIDR_BLOCK", "protocol": "6", "is-stateless": False,
    "tcp-options": {"destination-port-range": {"min": 3000, "max": 3000}}, "description": "App Access"
})

with open("new_ingress.json", "w") as f: json.dump(rules, f)
EOF
python3 update_rules.py

# 4. Push all rules back
oci network security-list update --security-list-id $SEC_LIST_ID --ingress-security-rules file://new_ingress.json --force
```

## 4. KasmVNC / Selkies Secure Context Requirement
When deploying `linuxserver` images with web-based desktop GUIs (like `zotero`, `calibre`, `webtop`), the KasmVNC ("Selkies") engine strictly requires a Secure Context to access the clipboard and WebRTC. Accessing it via HTTP on a bare IP will result in a hard blocking error: `Error: This application requires a secure connection (HTTPS)`.

**Solution:** Always map and expose the internal HTTPS port (e.g., `3001` instead of `3000`) in `docker-compose.yml` (`3001:3001`) and in the VCN/Iptables. Access the GUI via `https://<IP>:3001` and bypass the browser's self-signed certificate warning.
