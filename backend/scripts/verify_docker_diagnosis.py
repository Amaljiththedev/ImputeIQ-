"""Quick one-shot verification: uploads the MNAR file and checks the diagnosis label."""
import requests
import time

BASE = "http://127.0.0.1:8000"
MNAR_FILE = "app/data/synthetic/patient_records_mnar_30.csv"

# Upload
from pathlib import Path
with open(MNAR_FILE, "rb") as f:
    resp = requests.post(f"{BASE}/api/upload/", files={"file": (Path(MNAR_FILE).name, f, "text/csv")})
resp.raise_for_status()
dataset_id = resp.json()["id"]
print(f"Uploaded MNAR file -> dataset_id={dataset_id}")

# Diagnose
job_id = requests.post(f"{BASE}/api/diagnosis/{dataset_id}").json()["id"]
print(f"Diagnosis job: {job_id}")

# Poll
for _ in range(60):
    s = requests.get(f"{BASE}/api/jobs/{job_id}").json()["status"]
    if s in ("complete", "failed"):
        break
    time.sleep(0.5)
print(f"Job status: {s}")

# Results
results = requests.get(f"{BASE}/api/diagnosis/{dataset_id}/results").json()
print()
print("=== Diagnosis Results ===")
for r in results:
    col       = r["target_column"]
    mechanism = r["diagnosed_mechanism"]
    p_val     = r["littles_p_value"]
    drivers   = r["significant_drivers"]
    detail    = r["diagnosis_detail"]
    print(f"  column   : {col}")
    print(f"  diagnosed: {mechanism}")
    print(f"  littles_p: {p_val:.4f}")
    print(f"  drivers  : {drivers}")
    print(f"  detail   : {detail}")
    print()

# Verdict
mech = results[0]["diagnosed_mechanism"] if results else "N/A"
if mech == "Ambiguous (MCAR/MNAR)":
    print("[PASS] Updated diagnosis_mechanism.py IS running in Docker.")
    print("       MNAR data correctly diagnosed as 'Ambiguous (MCAR/MNAR)' - not MCAR.")
elif mech == "MCAR":
    print("[FAIL] Old diagnosis_mechanism.py is running in Docker.")
    print("       MNAR data was diagnosed as 'MCAR' - the Ambiguous fix is NOT active.")
else:
    print(f"[INFO] Diagnosed as: {mech}")
