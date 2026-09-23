# DSA5208 Project 1 — MongoDB Consistency Experiments

Distributed MongoDB replica set (`rs0`) used to study client-centric consistency models
(read-your-writes, monotonic-reads, monotonic-writes, writes-follow-reads) under tunable
read/write concern configurations, node failures, and network partitions.

## Environment (recorded on first setup, Windows host)

| Component | Version |
|---|---|
| OS | Windows 11 |
| Docker Desktop | 4.92.0 (engine 29.8.0, API 1.56) |
| Docker Compose | v5.5.1 |
| Python (host venv) | 3.10.9 |
| PyMongo | 4.17.0 |
| MongoDB image | `dsa5208/mongo-lab:8.0.32` (built from `mongo:8.0.32-noble`) |
| Git | 2.36.1 |

## Topology

| Container | Hostname | Port | Role | Priority | Notes |
|---|---|---|---|---|---|
| dsa-mongo1 | mongo1 | 27017 | intended PRIMARY | 2 | |
| dsa-mongo2 | mongo2 | 27018 | SECONDARY | 1 | |
| dsa-mongo3 | mongo3 | 27019 | SECONDARY | 0 | `secondaryDelaySecs=10`, tag `role: delayed` |

## One-time host setup (Windows)

1. Install Docker Desktop, ensure Python 3.10+ and Git are installed.
2. **Add hostname mappings** — required so PyMongo (running on the host) can resolve replica
   set member hostnames configured in [replica-init.js](config/replica-init.js). Edit
   `C:\Windows\System32\drivers\etc\hosts` as Administrator and add:
   ```
   127.0.0.1 mongo1
   127.0.0.1 mongo2
   127.0.0.1 mongo3
   ```
3. Create a virtual environment and install dependencies:
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\pip install -r project1\requirements.txt
   ```

## Bring up the cluster

```powershell
docker compose -f project1\docker-compose.yml up -d --build
docker compose -f project1\docker-compose.yml ps   # wait until all 3 are "healthy"
```

Initialize the replica set (safe to re-run; it's a no-op if already initialized):

```powershell
Get-Content project1\config\replica-init.js | docker exec -i dsa-mongo1 mongosh --port 27017 --quiet
```

Verify topology:

```powershell
docker exec -i dsa-mongo1 mongosh --port 27017 --quiet --eval "rs.status().members.forEach(m => print(m.name + ' | ' + m.stateStr))"
```

Expect `mongo1 | PRIMARY`, `mongo2 | SECONDARY`, `mongo3 | SECONDARY`.

## Running experiments

Shared connection helpers and the C1–C4 read/write concern configurations live in
[script/common.py](../script/common.py). Experiment and fault-injection scripts live in
[script/](../script/) (see in-progress additions there).

## Tear down

```powershell
docker compose -f project1\docker-compose.yml down
```

This removes containers but keeps named volumes (`mongo1-data`, `mongo2-data`, `mongo3-data`)
unless `-v` is also passed.
