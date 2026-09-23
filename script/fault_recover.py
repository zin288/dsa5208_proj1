"""Recovery: flush iptables rules on all nodes and restart any stopped containers.

Always call this in a try/finally after fault_partition.py / fault_secondary_down.py /
fault_primary_down.py, so no rule or stopped container leaks into the next run.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from docker_utils import docker_exec, docker_start, container_running

ALL_NODES = ["mongo1", "mongo2", "mongo3"]


def main():
    for node in ALL_NODES:
        if not container_running(node):
            docker_start(node)
            print(f"restarted {node}")

    for node in ALL_NODES:
        docker_exec(node, ["iptables", "-F"], check=False)
        docker_exec(node, ["iptables", "-X"], check=False)

    print("recovery complete: all nodes running, iptables rules flushed")


if __name__ == "__main__":
    main()
