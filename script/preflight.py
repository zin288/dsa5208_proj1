"""Pre-run health check: replica set topology + each C1-C4 config is reachable/writable."""
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from common import CONFIGS, get_normal_client, get_collection


def check_topology(client):
    status = client.admin.command("replSetGetStatus")
    states = {m["name"]: m["stateStr"] for m in status["members"]}
    primaries = [n for n, s in states.items() if s == "PRIMARY"]
    secondaries = [n for n, s in states.items() if s == "SECONDARY"]

    ok = len(primaries) == 1 and len(secondaries) == 2
    print(f"[topology] primaries={primaries} secondaries={secondaries} -> {'OK' if ok else 'FAIL'}")
    return ok


def check_config(client, config_name):
    # A read miss right after write is expected for majority-read/w:1 configs (e.g. C2) due to
    # replication lag to the majority commit point, so we only check the driver doesn't raise.
    doc_id = f"preflight-{config_name}-{uuid.uuid4().hex}"
    try:
        col = get_collection(client, config_name)
        col.insert_one({"_id": doc_id, "version": 0})
        found = col.find_one({"_id": doc_id})
    except Exception as exc:
        print(f"[config {config_name}] FAIL: {exc}")
        return False
    finally:
        get_collection(client, "C1").delete_one({"_id": doc_id})

    visibility = "visible immediately" if found is not None else "not yet visible (expected for lagging read concern)"
    print(f"[config {config_name}] OK - {visibility}")
    return True


def main():
    client = get_normal_client()
    results = [check_topology(client)]
    results += [check_config(client, name) for name in CONFIGS]
    client.close()

    if all(results):
        print("PREFLIGHT: PASS")
        sys.exit(0)
    else:
        print("PREFLIGHT: FAIL")
        sys.exit(1)


if __name__ == "__main__":
    main()
