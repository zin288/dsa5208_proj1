"""Thin subprocess wrappers around `docker` CLI, shared by fault-injection scripts."""
import json
import subprocess

CONTAINERS = {"mongo1": "dsa-mongo1", "mongo2": "dsa-mongo2", "mongo3": "dsa-mongo3"}
PORTS = {"mongo1": 27017, "mongo2": 27018, "mongo3": 27019}


def run(args, check=True):
    return subprocess.run(args, check=check, capture_output=True, text=True)


def container_ip(name):
    container = CONTAINERS.get(name, name)
    out = run(["docker", "inspect", "-f", "{{json .NetworkSettings.Networks}}", container]).stdout
    networks = json.loads(out)
    # single bridge network per compose file, so just take the first entry's IP
    return next(iter(networks.values()))["IPAddress"]


def docker_exec(name, cmd_args, check=True):
    container = CONTAINERS.get(name, name)
    return run(["docker", "exec", container] + cmd_args, check=check)


def docker_stop(name):
    container = CONTAINERS.get(name, name)
    return run(["docker", "stop", container])


def docker_start(name):
    container = CONTAINERS.get(name, name)
    return run(["docker", "start", container])


def container_running(name):
    container = CONTAINERS.get(name, name)
    out = run(["docker", "inspect", "-f", "{{.State.Running}}", container], check=False).stdout.strip()
    return out == "true"
