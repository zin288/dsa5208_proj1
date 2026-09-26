"""Repeat selected fault workloads as independent inject/recover episodes."""
import argparse
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from common import get_normal_client
from fault_recover import recover
from matrix_lock import acquire as acquire_matrix_lock

SCRIPT_DIR = Path(__file__).parent
WORKLOADS = {
    "RYW": "test_ryw.py",
    "MR": "test_monotonic_reads.py",
    "MW": "test_monotonic_writes.py",
    "WFR": "test_writes_follow_reads.py",
}
FAULT_SCENARIOS = ["secondary_down", "primary_down", "partition"]


def wait_for_healthy_cluster(timeout_seconds):
    deadline = time.monotonic() + timeout_seconds
    last_status = "not checked"
    consecutive_ready_checks = 0
    while time.monotonic() < deadline:
        client = get_normal_client()
        try:
            status = client.admin.command("replSetGetStatus")
            members = status.get("members", [])
            states = [member.get("stateStr") for member in members]
            healthy = all(member.get("health") == 1 for member in members)
            ready = (
                len(members) == 3
                and healthy
                and states.count("PRIMARY") == 1
                and states.count("SECONDARY") == 2
            )
            if ready:
                primary_optime = next(
                    member["optimeDate"] for member in members
                    if member["stateStr"] == "PRIMARY"
                )
                lag_seconds = {
                    member["name"]: (primary_optime - member["optimeDate"]).total_seconds()
                    for member in members
                    if member["stateStr"] == "SECONDARY"
                }
                ready = all(
                    lag <= (30 if name.endswith(":27019") else 5)
                    for name, lag in lag_seconds.items()
                )
                last_status = f"states={states}, secondary_lag_seconds={lag_seconds}"
            else:
                last_status = f"states={states}, health={[m.get('health') for m in members]}"

            if ready:
                consecutive_ready_checks += 1
                if consecutive_ready_checks >= 2:
                    client.close()
                    return next(
                        member["name"].split(":", 1)[0]
                        for member in members
                        if member["stateStr"] == "PRIMARY"
                    )
            else:
                consecutive_ready_checks = 0
        except Exception as exc:
            last_status = f"{type(exc).__name__}: {exc}"
            consecutive_ready_checks = 0
        finally:
            client.close()
        time.sleep(2)
    raise TimeoutError(f"Replica set did not return to 1 PRIMARY + 2 SECONDARY: {last_status}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--configs", nargs="+", choices=["C1", "C2", "C3", "C4"],
                        default=["C1", "C3"], help="default compares strong C1 with weak C3")
    parser.add_argument("--properties", nargs="+", choices=list(WORKLOADS), default=list(WORKLOADS))
    parser.add_argument("--scenarios", nargs="+", choices=FAULT_SCENARIOS, default=FAULT_SCENARIOS)
    parser.add_argument("--episodes", type=int, default=3)
    parser.add_argument("--trials-per-episode", type=int, default=10)
    parser.add_argument("--seed", type=int, default=1000)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--episode-timeout-seconds", type=int, default=3600)
    parser.add_argument("--recovery-timeout-seconds", type=int, default=180)
    parser.add_argument("--plan", action="store_true", help="show planned episodes without running")
    args = parser.parse_args()

    if args.episodes < 1 or args.trials_per_episode < 1:
        parser.error("--episodes and --trials-per-episode must be positive")
    if args.episode_timeout_seconds < 1 or args.recovery_timeout_seconds < 1:
        parser.error("timeouts must be positive")

    if args.run_id is None:
        args.run_id = datetime.now(timezone.utc).strftime("fault-episodes-%Y%m%dT%H%M%SZ")

    cell_count = len(args.configs) * len(args.properties) * len(args.scenarios)
    episode_count = cell_count * args.episodes
    trial_count = episode_count * args.trials_per_episode
    print(
        f"run_id={args.run_id}; cells={cell_count}; episodes={episode_count}; "
        f"trials_per_episode={args.trials_per_episode}; planned_trials={trial_count}",
        flush=True,
    )
    if args.plan:
        return

    acquire_matrix_lock()
    completed_episodes = 0
    for config in args.configs:
        for property_name in args.properties:
            workload = SCRIPT_DIR / WORKLOADS[property_name]
            for scenario in args.scenarios:
                for episode in range(1, args.episodes + 1):
                    episode_id = f"{args.run_id}-{config}-{property_name}-{scenario}-ep{episode:02d}"
                    wait_for_healthy_cluster(args.recovery_timeout_seconds)
                    command = [
                        sys.executable, str(workload),
                        "--config", config,
                        "--scenario", scenario,
                        "--trials", str(args.trials_per_episode),
                        "--seed", str(args.seed + episode - 1),
                        "--run-id", episode_id,
                    ]
                    print(
                        f"episode {completed_episodes + 1}/{episode_count}: "
                        f"{config} {property_name} {scenario} #{episode}",
                        flush=True,
                    )
                    try:
                        result = subprocess.run(command, timeout=args.episode_timeout_seconds)
                    except subprocess.TimeoutExpired:
                        recover()
                        wait_for_healthy_cluster(args.recovery_timeout_seconds)
                        raise SystemExit(f"episode timed out: {episode_id}")

                    recover()
                    wait_for_healthy_cluster(args.recovery_timeout_seconds)
                    if result.returncode != 0:
                        raise SystemExit(f"episode failed with exit code {result.returncode}: {episode_id}")
                    completed_episodes += 1

    print(f"all {completed_episodes} independent fault episodes completed")


if __name__ == "__main__":
    main()
