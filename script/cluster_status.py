"""Print replica set member states, optimes and replication lag for quick manual checks."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from common import get_normal_client


def main():
    client = get_normal_client()
    status = client.admin.command("replSetGetStatus")
    primary_optime = None
    for m in status["members"]:
        if m["stateStr"] == "PRIMARY":
            primary_optime = m["optimeDate"]

    print(f"set: {status['set']}")
    for m in status["members"]:
        lag = ""
        if primary_optime is not None and m["stateStr"] != "PRIMARY" and m["health"] == 1:
            lag_seconds = (primary_optime - m["optimeDate"]).total_seconds()
            lag = f" | lag_behind_primary_s={lag_seconds:.1f}"
        print(f"  {m['name']:<15} {m['stateStr']:<10} health={m['health']}{lag}")

    client.close()


if __name__ == "__main__":
    main()
