from flask import Flask, request, jsonify
import docker
import requests
import time
import os

app = Flask(__name__)
client = docker.from_env()

EDGE_ID = os.getenv("EDGE_ID", "S-UPF")
FIREWALL_IMAGE = os.getenv("FIREWALL_NSF_IMAGE", "firewall-nsf:latest")
FIREWALL_NAME = os.getenv("FIREWALL_NSF_NAME", "firewall-nsf")
FIREWALL_PORT = int(os.getenv("FIREWALL_NSF_PORT", "18080"))

COLOR = "\033[95m" if EDGE_ID == "S-UPF" else "\033[96m"
RESET = "\033[0m"

def log(msg):
    print(f"{COLOR}[UPF-NSF-MGR][{EDGE_ID}] {msg}{RESET}", flush=True)

def container_running(name):
    try:
        c = client.containers.get(name)
        return c.status == "running"
    except docker.errors.NotFound:
        return False

def ensure_firewall():
    if container_running(FIREWALL_NAME):
        log(f"Firewall NSF already running: {FIREWALL_NAME}")
        return "already_running"

    log(f"Starting Firewall NSF container: {FIREWALL_NAME}")
    client.containers.run(
        FIREWALL_IMAGE,
        name=FIREWALL_NAME,
        detach=True,
        network_mode="host",
        cap_add=["NET_ADMIN"],
        environment={"PYTHONUNBUFFERED": "1"}
    )
    time.sleep(1)
    return "started"

@app.post("/policy/install")
def install_policy():
    policy = request.json
    start = time.time()

    log(f"Received policy {policy['policy_id']} from SCF")
    log(f"Required NSFs: {policy.get('required_nsfs', [])}")

    results = []

    if "firewall" in policy.get("required_nsfs", []):
        ensure_firewall()

        r = requests.post(
            f"http://127.0.0.1:{FIREWALL_PORT}/policy/block-ue",
            json={
                "policy_id": policy["policy_id"],
                "ue_ip": policy["ue_ip"],
                "n6_if": policy.get("n6_if", "ens33")
            },
            timeout=5
        )
        results.append(r.json())

    total_ms = (time.time() - start) * 1000
    log(f"Policy installed policy_id={policy['policy_id']}, total_ms={total_ms:.2f}")

    return jsonify({
        "status": "installed",
        "edge_id": EDGE_ID,
        "policy_id": policy["policy_id"],
        "total_ms": total_ms,
        "results": results
    })

@app.post("/policy/delete")
def delete_policy():
    policy = request.json

    log(f"Deleting policy {policy['policy_id']}")

    r = requests.post(
        f"http://127.0.0.1:{FIREWALL_PORT}/policy/unblock-ue",
        json={
            "policy_id": policy["policy_id"],
            "ue_ip": policy["ue_ip"],
            "n6_if": policy.get("n6_if", "ens33")
        },
        timeout=5
    )

    return jsonify({
        "status": "deleted",
        "edge_id": EDGE_ID,
        "result": r.json()
    })

@app.get("/status")
def status():
    return jsonify({
        "status": "running",
        "edge_id": EDGE_ID,
        "firewall_running": container_running(FIREWALL_NAME)
    })

if __name__ == "__main__":
    log("UPF-side NSF Manager started")
    log("UPF core forwarding is not modified")
    app.run(host="0.0.0.0", port=9095)
