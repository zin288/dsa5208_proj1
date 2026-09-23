"""S1 scenario: stop a secondary node (real process stop, not a partition)."""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from docker_utils import docker_stop, container_running


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=["mongo2", "mongo3"], default="mongo3")
    args = parser.parse_args()

    if not container_running(args.target):
        print(f"{args.target} is already stopped")
        return

    docker_stop(args.target)
    print(f"stopped {args.target}")


if __name__ == "__main__":
    main()
