from flask import Flask, request, jsonify
import subprocess
import time
import os

app = Flask(__name__)

CHAIN = os.getenv("I2NSF_CHAIN", "I2NSF-N6")
YELLOW = "\033[93m"
RESET = "\033[0m"

def log(msg):
    print(f"{YELLOW}[FW-NSF] {msg}{RESET}", flush=True)

def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)

def ensure_chain():
    run(["iptables", "-N", CHAIN])
    check = run(["iptables", "-C", "FORWARD", "-j", CHAIN])
    if check.returncode != 0:
        run(["iptables", "-I", "FORWARD", "1", "-j", CHAIN])

def build_rule(policy):
    policy_id = policy["policy_id"]
    ue_ip = policy["ue_ip"]
    n6_if = policy.get("n6_if", "ens33")

    return [
        "-s", ue_ip,
        "-o", n6_if,
        "-m", "comment",
        "--comment", f"I2NSF:{policy_id}",
        "-j", "DROP"
    ]

@app.post("/policy/block-ue")
def block_ue():
    ensure_chain()
    policy = request.json
    policy_id = policy["policy_id"]
    rule = build_rule(policy)

    check = run(["iptables", "-C", CHAIN] + rule)
    if check.returncode == 0:
        log(f"Rule already exists policy_id={policy_id}")
        return jsonify({"status": "already_installed", "policy_id": policy_id})

    cmd = ["iptables", "-I", CHAIN, "1"] + rule
    result = run(cmd)

    log(f"Installed N6 block rule policy_id={policy_id}, ue_ip={policy['ue_ip']}, n6_if={policy.get('n6_if', 'ens33')}")

    return jsonify({
        "status": "installed" if result.returncode == 0 else "failed",
        "policy_id": policy_id,
        "cmd": " ".join(cmd),
        "stderr": result.stderr,
        "timestamp": time.time()
    })

@app.post("/policy/unblock-ue")
def unblock_ue():
    policy = request.json
    policy_id = policy["policy_id"]
    rule = build_rule(policy)

    removed = 0
    while run(["iptables", "-C", CHAIN] + rule).returncode == 0:
        run(["iptables", "-D", CHAIN] + rule)
        removed += 1

    log(f"Removed N6 block rule policy_id={policy_id}, removed={removed}")

    return jsonify({
        "status": "removed",
        "policy_id": policy_id,
        "removed": removed
    })

@app.get("/status")
def status():
    result = run(["iptables", "-L", CHAIN, "-v", "-n"])
    return jsonify({
        "status": "running",
        "chain": CHAIN,
        "iptables": result.stdout
    })

if __name__ == "__main__":
    log("Firewall NSF started on port 18080")
    app.run(host="0.0.0.0", port=18080)
