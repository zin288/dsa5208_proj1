"""S3 scenario: real network partition via in-container iptables (process keeps running).

Isolates one side's container(s) from the other side's, while leaving the Windows host's
port-mapped client connections (127.0.0.1:270xx) untouched, since those don't originate
from a peer container's IP.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from docker_utils import docker_exec, container_ip

ALL_NODES = ["mongo1", "mongo2", "mongo3"]


def partition(isolate):
    """Blocks all traffic between `isolate` and every other node, in both directions."""
    others = [n for n in ALL_NODES if n != isolate]
    other_ips = {n: container_ip(n) for n in others}

    for other, ip in other_ips.items():
        docker_exec(isolate, ["iptables", "-A", "INPUT", "-s", ip, "-j", "DROP"])
        docker_exec(isolate, ["iptables", "-A", "OUTPUT", "-d", ip, "-j", "DROP"])

    print(f"partitioned {isolate} from {others}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--isolate", choices=ALL_NODES, default="mongo1",
                         help="node to cut off from the other two (default: old primary)")
    args = parser.parse_args()
    partition(args.isolate)


if __name__ == "__main__":
    main()
