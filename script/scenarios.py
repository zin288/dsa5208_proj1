"""Context manager applying one of the S0-S3 scenarios around a block of trials."""
import sys
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import docker_utils
from fault_partition import partition
from fault_recover import recover

SCENARIOS = ["normal", "secondary_down", "primary_down", "partition"]


@contextmanager
def apply_scenario(name):
    if name not in SCENARIOS:
        raise ValueError(f"unknown scenario: {name}")

    applied = name != "normal"
    try:
        if name == "secondary_down":
            docker_utils.docker_stop("mongo3")
        elif name == "primary_down":
            docker_utils.docker_stop("mongo1")
        elif name == "partition":
            partition("mongo1")
        yield
    finally:
        if applied:
            recover()
