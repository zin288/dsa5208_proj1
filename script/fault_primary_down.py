"""S2 scenario: fail the primary, either by hard stop or a graceful rs.stepDown()."""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from docker_utils import docker_stop, docker_exec, container_running, PORTS


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", default="mongo1", help="container currently acting as primary")
    parser.add_argument("--mode", choices=["stop", "stepdown"], default="stop")
    args = parser.parse_args()

    if args.mode == "stop":
        if not container_running(args.target):
            print(f"{args.target} is already stopped")
            return
        docker_stop(args.target)
        print(f"stopped {args.target}")
    else:
        # stepDown keeps the mongod process running; it just forces an election.
        docker_exec(args.target, [
            "mongosh", "--quiet", "--port", str(PORTS[args.target]), "--eval", "rs.stepDown(60)",
        ])
        print(f"{args.target} stepped down")


if __name__ == "__main__":
    main()
