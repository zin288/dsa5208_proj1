# DSA5208 Project 1 工作流程

> 项目：Consistency Models in Distributed Databases  
> 截止时间：2026-09-27 23:59:59（新加坡时间，UTC+8）  
> 分值：30 分  
> 小组人数：不超过 3 人  
> 推荐方案：在一台主电脑上用 Docker 部署三节点 MongoDB replica set，由三名组员共同设计、执行、复核和撰写报告

## 1. 这份工作流程的目标

本项目不是简单安装数据库，也不是只比较延迟。最终需要形成一条可以复核的证据链：

```text
课程定义
  -> 数据库配置及理论预测
  -> 可重复的操作历史
  -> 正常、节点故障、网络分区实验
  -> 自动一致性判定和原始日志
  -> 统计表与图
  -> 有证据边界的报告结论
```

完成标准：另一名组员能在另一台电脑上按照 `README.md` 部署集群，运行至少一组核心实验，并得到结构一致的结果文件。

## 2. Canvas 的强制要求

必须完成：

- 安装一个支持 tunable consistency 的分布式数据库。
- 建立 replicated distributed database。
- 探索数据库提供的一致性配置。
- 在实验前预测不同配置是否满足以下四种客户端一致性：
  - read-your-writes（RYW）；
  - monotonic reads（MR）；
  - monotonic writes（MW）；
  - writes-follow-reads（WFR）。
- 自行设计并运行实验验证预测。
- 覆盖多个场景：
  - 正常运行；
  - 一个或多个数据库节点故障；
  - 网络分区。
- 提交：
  - PDF 报告；
  - 实验脚本和源代码；
  - 复现主要实验的简短说明。
- 报告必须说明数据库、部署架构、版本、安装步骤、配置、实验设计、结果、解释、局限和引用。
- 必须引用数据库文档、其他资料，并声明 AI 使用情况。

Canvas 没有给出独立 rubric、报告页数限制或允许文件扩展名列表。作业正文称其为小组项目，但 Canvas 没有配置原生 group assignment。小组应尽快向教师确认是由一名成员代表提交，还是三名成员分别提交同一份材料。

## 3. 推荐范围与不做事项

### 3.1 推荐范围

- 数据库：MongoDB replica set。
- 节点：三个 data-bearing voting members，不使用 arbiter。
- 部署：一台主电脑上的三个 Docker 容器。
- 客户端：Python + PyMongo。
- 主要变量：read concern、write concern、causal session、目标副本、故障状态。
- 主要结果：一致性违规、操作成功率、错误类型、超时、延迟和恢复时间。

### 3.2 暂不扩展

除非所有核心实验和报告初稿已经完成，否则不要增加 ScyllaDB/Cassandra 对比。一个系统的完整实验比两个系统的浅层截图更符合当前时间约束。

### 3.3 不能写出的结论

- “30 次没有看到旧值，所以该配置保证 RYW。”
- “`majority` 等于 linearizability。”
- “节点停机就是网络分区。”
- “读写成功说明所有副本已经一致。”
- “`w:1` 一定产生错误。”

正确表述应区分：

- 理论文档提供的保证；
- 本实验观察到的行为；
- 在有限运行次数内未观察到的反例；
- 超出实验范围、尚未验证的性质。

## 4. 三人分工与协作规则

| 角色 | 主责任 | 必须交付 | 交叉复核 |
|---|---|---|---|
| 组员 A：基础设施 | Docker、MongoDB replica set、健康检查、节点故障、网络分区 | Compose、初始化脚本、故障脚本、架构图 | 复核 B 的故障条件是否真实生效 |
| 组员 B：实验与判定 | 四类一致性 workload、日志、自动判定、批量运行 | Python 脚本、JSONL、判定结果、实验矩阵 | 复核 C 的结论是否得到数据支持 |
| 组员 C：分析与报告 | 数据清理、统计、作图、报告、引用、AI 声明 | CSV、图表、报告、提交清单 | 在干净环境复现 A/B 的核心实验 |

协作规则：

1. 所有脚本、配置和报告使用共享 Git 仓库；不要只通过聊天软件传压缩包。
2. 原始实验结果只追加，不手工覆盖。
3. 每张图都能追溯到一个处理脚本和一个或多个原始日志。
4. 每次重要配置变更都提交到 Git，并在实验元数据中记录 commit SHA。
5. 密码、token、Canvas token 和本机绝对路径不得提交。

## 5. 建议目录结构

```text
project1/
├─ README.md
├─ docker-compose.yml
├─ .env.example
├─ config/
│  ├─ replica-init.js
│  └─ replica-config.json
├─ scripts/
│  ├─ preflight.py
│  ├─ init_cluster.py
│  ├─ cluster_status.py
│  ├─ fault_secondary_down.ps1
│  ├─ fault_primary_down.ps1
│  ├─ fault_partition.ps1
│  ├─ fault_recover.ps1
│  ├─ test_ryw.py
│  ├─ test_monotonic_reads.py
│  ├─ test_monotonic_writes.py
│  ├─ test_writes_follow_reads.py
│  ├─ run_matrix.py
│  ├─ check_history.py
│  └─ analyze_results.py
├─ results/
│  ├─ raw/
│  ├─ processed/
│  └─ manifests/
├─ figures/
├─ report/
│  ├─ report_source.*
│  └─ DSA5208_Project1_Report.pdf
└─ submission/
   └─ DSA5208_Project1_Code.zip
```

## 6. 阶段 0：开始前锁定事项

### 6.1 小组决定

- [ ] 确认三名成员姓名、学号及在报告中的顺序。
- [ ] 确认提交责任人。
- [ ] 向教师确认 Canvas 是否要求每位成员单独提交。
- [ ] 确认主实验电脑和复现实验电脑。
- [ ] 确认仓库访问权限。

### 6.2 软件与硬件预检

主电脑建议满足：

- Windows 11 + Docker Desktop/WSL2；
- 至少 16 GB 内存；
- 至少 20 GB 可用磁盘；
- Python 3.11 或更高；
- Git；
- 可运行 Linux 容器。

记录以下版本，稍后写入报告：

```powershell
docker version
docker compose version
python --version
git --version
```

MongoDB 镜像必须固定到明确版本或 digest，不能在最终实验里使用浮动的 `latest`。报告应记录：

- MongoDB 完整版本；
- Docker image tag 和 digest；
- PyMongo 版本；
- Python 版本；
- 操作系统与 Docker Desktop/WSL2 版本；
- CPU、内存和磁盘概况。

## 7. 阶段 1：部署三节点 MongoDB

### 7.1 拓扑

```text
                        Python experiment controller
                              /      |      \
                             /       |       \
                       mongo1     mongo2     mongo3
                       primary   secondary  secondary
                                  normal     delayed
```

推荐初始配置：

- `mongo1`、`mongo2`、`mongo3` 都保存数据。
- 三个节点都参与投票。
- `mongo3` 设置 `priority: 0`，避免它成为 primary。
- 需要稳定制造复制延迟时，为 `mongo3` 设置 `secondaryDelaySecs: 10` 或 `15`。
- 给 delayed secondary 设置 tag，例如 `role: delayed`，便于客户端定向读取。
- 每个节点使用独立数据卷。
- 宿主机端口分别映射到不同端口，便于诊断。

### 7.2 部署步骤

1. 创建 Compose、MongoDB 配置和数据卷。
2. 启动三个容器：

   ```powershell
   docker compose up -d
   docker compose ps
   ```

3. 等待三个 `mongod` 进程健康。
4. 初始化 replica set。
5. 等待一个节点成为 primary、另外两个成为 secondary。
6. 应用 delayed secondary 配置。
7. 创建项目数据库和测试集合。
8. 运行 `preflight.py` 与 `cluster_status.py`。

### 7.3 部署验收

- [ ] `rs.status()` 中恰好有一个 primary。
- [ ] 两个 secondary 都进入可用状态。
- [ ] 三个节点的数据目录互相独立。
- [ ] primary 写入的数据最终可在两个 secondary 查询到。
- [ ] delayed secondary 的延迟确实接近配置值。
- [ ] 容器重启后 replica set 可以恢复。
- [ ] 初始化脚本可重复运行，不会因对象已存在而失败。
- [ ] `docker compose down` 不会误删原始实验结果。

## 8. 阶段 2：定义一致性模型和配置预测

### 8.1 四种待测性质

#### Read-your-writes（RYW）

同一客户端写入 `x=v` 后，后续读取 `x` 应至少看到该写入或更新版本。

#### Monotonic reads（MR）

同一客户端一旦读到版本 `v_k`，后续读取不能退回更旧版本。

#### Monotonic writes（MW）

同一客户端的连续写入必须按客户端发出的顺序完成和生效。

#### Writes-follow-reads（WFR）

客户端先读取版本 `v_k`，随后写入时，该写入必须建立在 `v_k` 或更新状态之上。

### 8.2 核心配置矩阵

以下预测只适用于启用 causally consistent session 的操作序列：

| 配置 ID | Read concern | Write concern | RYW | MR | MW | WFR |
|---|---|---|---:|---:|---:|---:|
| C1 | `majority` | `majority` | 保证 | 保证 | 保证 | 保证 |
| C2 | `majority` | `w:1` | 不保证 | 保证 | 不保证 | 保证 |
| C3 | `local` | `w:1` | 不保证 | 不保证 | 不保证 | 不保证 |
| C4 | `local` | `majority` | 不保证 | 不保证 | 保证 | 不保证 |

“不保证”表示存在允许违反的执行历史，不表示每次运行都会出现违规。实验报告必须保留这个区别。

### 8.3 实验前预测表

在运行任何实验之前，由三名组员共同填写：

| Experiment ID | 配置 | 场景 | 待测性质 | 预测 | 理由 | 可观察判据 |
|---|---|---|---|---|---|---|
| 示例 | C3 | delayed secondary | RYW | 可能违反 | local read 可返回未追上最新写入的本地快照 | 写入 `v1` 后返回 `v0` |

预测表提交 Git 后再开始正式运行，避免看到结果后倒推假设。

## 9. 阶段 3：统一日志和版本模型

### 9.1 测试数据

对每个逻辑 key 使用单调版本值，而不是难以排序的普通字符串：

```json
{
  "_id": "trial-0001",
  "version": 3,
  "writer": "client-A",
  "trial_id": "trial-0001",
  "payload": "optional"
}
```

每个 trial 使用新的 `_id`，防止前一次实验污染下一次。

### 9.2 每次操作的必需日志字段

```json
{
  "experiment_id": "C3-PARTITION-RYW",
  "trial": 1,
  "op_id": "uuid",
  "client_id": "client-A",
  "session_id": "session-A",
  "operation": "read_or_write",
  "key": "trial-0001",
  "requested_version": 1,
  "returned_version": 0,
  "target_node": "mongo3",
  "read_concern": "local",
  "write_concern": "w1",
  "read_preference": "secondary",
  "invoke_monotonic_ns": 0,
  "response_monotonic_ns": 0,
  "latency_ms": 0.0,
  "success": true,
  "error_type": null,
  "topology_state": "partition",
  "git_commit": "sha",
  "timestamp_utc": "ISO-8601"
}
```

### 9.3 时间规则

Lecture 1 强调分布式系统没有可靠全局时钟。因此：

- invocation/response 的严格顺序由同一个实验控制进程的 monotonic clock 记录。
- 不使用不同容器的 wall-clock timestamp 直接证明 happens-before。
- UTC 时间只用于日志定位，不用于一致性判定。
- 若使用多客户端进程，应明确哪些顺序来自程序顺序、消息依赖或读到某次写入。

## 10. 阶段 4：实现四类一致性 workload

所有脚本必须支持：

- 命令行选择配置 ID、场景、trial 数量和随机种子；
- 设置 `wtimeout`、`maxTimeMS` 和客户端 server-selection timeout；
- 选择 read preference 和标签；
- 开启或关闭 causal session；
- 开启或关闭 `retryWrites`；
- 写出 JSONL 原始日志和单次运行 manifest；
- 失败时保存错误，不静默重试到成功。

### 10.1 RYW workload

基本序列：

```text
Client A: write x=1 -> receive acknowledgement -> read x
```

重点变体：

- 写 primary，读正常 secondary。
- 写 primary，读 delayed secondary。
- causal session 开启/关闭。
- `majority/majority` 与 `local/w:1` 对照。

判定：后续读返回版本小于该客户端已确认写入版本，即观察到 RYW violation。

### 10.2 Monotonic-reads workload

基本序列：

```text
Client A: read x=v2 from up-to-date node
          -> read x again from delayed or isolated node
```

判定：同一客户端后一次读取版本小于此前读取版本，即观察到 MR violation。

### 10.3 Monotonic-writes workload

基本序列：

```text
Client A: write x=1 -> acknowledgement
          -> write x=2 -> acknowledgement
          -> write x=3 -> acknowledgement
```

在 normal、primary failure 和 partition 场景运行。记录每次写入的调用/响应顺序、确认方式、最终副本状态和可能的 rollback。

判定时不能只看最后值。必须结合操作历史和恢复后的副本状态，判断后续写是否建立在前序已完成写之后。

### 10.4 Writes-follow-reads workload

基本序列：

```text
Client A: read x=v1
          -> compute v2 from v1
          -> write x=v2
```

让读取来自一个指定副本，写入发送到当时的 primary。通过 session metadata 和故障条件测试后续写是否建立在已读版本或更新版本之上。

判定时保存 read value、derived write value、session metadata 和目标节点。不要只凭最终值推断依赖关系。

## 11. 阶段 5：故障与网络分区

### 11.1 场景 S0：正常运行

- 三个节点在线。
- 无人工延迟以外的故障。
- 用于验证脚本和建立延迟基线。

### 11.2 场景 S1：一个 secondary 故障

1. 记录故障前 `rs.status()`。
2. 停止一个 secondary。
3. 等待拓扑稳定。
4. 运行完整配置矩阵或指定子集。
5. 恢复节点并等待追平。
6. 保存故障前、中、后的状态。

### 11.3 场景 S2：primary 故障与重新选举

1. 记录当前 primary。
2. 开始客户端循环工作负载。
3. 停止或 step down 当前 primary。
4. 记录首次失败、选举开始、新 primary 可用及首次恢复成功的时间。
5. 检查故障窗口中的确认写、失败写和重试写。
6. 恢复旧 primary，等待其以 secondary 身份加入。

测原始行为时，应关闭自动重试；如需讨论应用体验，再单独增加 `retryWrites=true` 的对照。不要把驱动自动重试后的成功误记为数据库第一次请求成功。

### 11.4 场景 S3：网络分区

网络分区必须保持相关进程仍在运行，同时阻断节点之间的通信。简单 `docker stop` 只能算节点故障。

推荐结构：

```text
Partition A: old primary
Partition B: two secondaries -> elect a new primary
Client path: experiment controller 能够分别访问两侧
```

实现可使用：

- 容器内 `iptables`/`nftables` 只丢弃节点间的 MongoDB 流量；或
- 受控网络代理，为复制连接提供可开关的双向链路；或
- 多网络/多 VM 的防火墙规则。

故障脚本必须成对存在：

```text
fault_partition.ps1
fault_recover.ps1
```

恢复脚本必须在 `finally`/异常清理路径中执行。每次分区实验后检查三个节点重新加入同一 replica set，并确认没有残留防火墙规则。

### 11.5 故障注入验收

- [ ] 日志显示预期链路被阻断。
- [ ] 目标容器进程仍在运行，证明这不是停机。
- [ ] 客户端仍能访问计划中的分区侧。
- [ ] 分区多数派能够按预期选举。
- [ ] 弱配置的操作与强配置的操作表现不同或给出合理错误。
- [ ] 恢复后所有节点重新同步。
- [ ] 第二次运行不受上一次残留规则影响。

## 12. 阶段 6：正式实验矩阵

### 12.1 最小完整矩阵

```text
4 configurations
x 4 consistency properties
x 3 required scenario classes (normal, node failure, partition)
x 30 trials
= 1,440 property trials
```

可将节点故障细分为 secondary failure 与 primary failure，但必须控制总运行时间。先完成每个单元 3 次 smoke test，再运行 30 次正式试验。

### 12.2 固定控制变量

- 相同 MongoDB、PyMongo 和 Docker 版本；
- 相同节点数和 replica set 配置；
- 相同数据结构与 payload 大小；
- 相同超时；
- 相同运行次数；
- 相同随机种子集合；
- 相同故障触发位置；
- 相同机器和资源限制；
- 正式实验期间不运行高负载无关程序。

### 12.3 每次批量运行前

- [ ] `git status` 已记录，正式代码有 commit SHA。
- [ ] `cluster_status.py` 通过。
- [ ] 测试集合已清理或使用新命名空间。
- [ ] 没有残留网络规则。
- [ ] Docker 容器和卷状态符合 manifest。
- [ ] 输出目录为空或使用新的 run ID。
- [ ] 时钟和磁盘空间正常。

### 12.4 每次批量运行后

- [ ] JSONL 可以逐行解析。
- [ ] trial 数与预期一致。
- [ ] 无静默缺失。
- [ ] 每个错误都有 error type/message。
- [ ] manifest 记录配置、版本、seed、commit 和拓扑。
- [ ] 生成 SHA-256 校验值，避免后续无意修改。

## 13. 阶段 7：数据处理与统计

### 13.1 原始数据不可手改

`results/raw/` 只保存原始 JSONL、拓扑状态和数据库日志。任何清理、聚合和筛选都由脚本生成到 `results/processed/`。

### 13.2 主要指标

正确性指标：

- violation count；
- violation rate；
- successful operation count；
- timeout/error count；
- rollback 或版本倒退事件。

性能和可用性指标：

- success rate；
- p50、p95、p99 latency；
- primary failover duration；
- partition 期间的成功/失败分布；
- 恢复到稳定拓扑和副本收敛的时间。

### 13.3 统计规则

- 报告 trial 总数和有效 trial 数。
- 延迟不只报告平均值。
- 同一指标的小数位保持一致。
- 每张图写明配置、场景、样本数和误差定义。
- 错误和超时不能从延迟统计中悄悄删除；应分别报告。
- 若某配置没有观察到 violation，报告 `0/N observed`，不要写“证明为 0”。

### 13.4 推荐图表

1. 架构图：三个 MongoDB 节点、客户端和分区边界。
2. 配置保证表：C1-C4 与四种性质。
3. 违规率热力图：配置 × 场景 × 一致性性质。
4. 延迟箱线图或 ECDF：弱配置与强配置对照。
5. 故障时间线：primary 故障、选举、恢复。
6. 预测—观察对照表：每个实验是否与预测一致。

图表必须由脚本生成，并在 caption 中说明 setting、metric direction、单位和样本数。

## 14. 阶段 8：报告写作

### 14.1 建议结构

### 1. Introduction

回答：项目研究什么、为什么客户端一致性重要、本文测试哪些配置和场景。

不要在 Introduction 中提前声称某配置“通过全部测试”，除非结果部分已经提供相应证据。

### 2. Background

简要定义：

- replicated distributed database；
- RYW、MR、MW、WFR；
- MongoDB replica set；
- read concern、write concern、read preference；
- causally consistent session；
- 正常运行、节点故障和网络分区的区别。

把 Lecture 1 的 happens-before/逻辑时间与 Lecture 3 的客户端一致性联系起来，但不要声称 MongoDB 的内部实现完全等同于课堂伪代码，除非数据库文档明确支持。

### 3. System and Deployment

必须包括：

- 架构图；
- 三个节点的角色和投票配置；
- delayed secondary 设置；
- 容器网络；
- 软件和硬件版本；
- 安装与初始化步骤；
- 为什么一台电脑上的多容器仍能用于本实验；
- 这种部署相对多机环境的局限。

### 4. Consistency Configurations and Predictions

- 给出 C1-C4 表。
- 对四种性质逐项解释预测。
- 明确区分 guarantee、not guaranteed 和 observed violation。
- 引用 MongoDB 官方文档。

### 5. Experimental Methodology

必须说明：

- workload 的精确操作序列；
- 数据与版本模型；
- trial 数；
- 超时、重试和 read preference；
- 节点故障方法；
- 网络分区方法；
- 自动判定规则；
- 控制变量；
- 日志和复现方式。

### 6. Results

按研究问题组织，而不是按脚本文件顺序罗列：

1. 四种配置在正常状态下是否符合预测？
2. 节点故障时哪些保证或操作受到影响？
3. 网络分区时一致性和可用性如何变化？
4. 强配置带来了什么延迟或可用性代价？

每个小节遵循：

```text
问题 -> 设置 -> 观察 -> 证据 -> 解释 -> 局限
```

### 7. Discussion and Limitations

至少讨论：

- 单机 Docker 不能复现真实跨机房网络、独立硬件故障和时钟漂移；
- 30 次或有限试验不能证明普遍正确性；
- 人工延迟和分区模型与生产网络存在差异；
- 驱动自动重试可能改变客户端观察；
- 实验只覆盖单文档/单 key 时，不可推广到任意多文档事务；
- 没有观察到反例与系统提供理论保证之间的区别。

### 8. Conclusion

只总结得到数据支持的发现。每个主要结论都应能指向一张表、一个图或一组明确日志。

### 9. Reproducibility and AI-use Statement

列出仓库结构、启动命令、运行命令、处理脚本和预计运行时间。

AI 使用说明可按实际情况改写：

> Generative AI tools were used to assist with project planning, code review, debugging, and language editing. All database configurations, experiment scripts, outputs, figures, and technical claims were reviewed and verified by the group members. The authors remain responsible for the submitted work.

不要声明没有发生过的人工验证。

### 10. References

优先引用：

- 课程 Lecture 1–3；
- MongoDB 官方文档；
- PyMongo 官方文档；
- 任何实际使用的故障注入工具文档。

至少保存以下官方页面的访问日期：

- <https://www.mongodb.com/docs/manual/core/causal-consistency-read-write-concerns/>
- <https://www.mongodb.com/docs/manual/reference/read-concern/>
- <https://www.mongodb.com/docs/manual/reference/write-concern/>
- <https://www.mongodb.com/docs/manual/core/replica-set-elections/>

### 14.2 Claim-evidence map

在报告定稿前建立：

| Claim | Evidence | Status |
|---|---|---|
| C1 在测试场景中未观察到 RYW violation | 表 X，C1/S0-S3，共 N 次 trial | supported within tested scope |
| C3 不保证 RYW | MongoDB 官方 guarantee table；实验 Y 观察到反例 | supported |
| stronger concern increases latency | 图 Z 的 p50/p95/p99 | supported / needs evidence |

如果 claim 没有对应 evidence，就增加实验或减弱/删除 claim。

## 15. 阶段 9：独立复现

由非主部署成员在另一台电脑执行：

1. 从干净 checkout 开始。
2. 按 README 安装依赖。
3. 运行 `docker compose up -d`。
4. 初始化集群。
5. 运行 preflight。
6. 运行至少：
   - C1 + normal + RYW；
   - C3 + delayed secondary + MR；
   - 一个 node-failure workload；
   - 一个真实 network-partition workload。
7. 运行分析脚本。
8. 检查输出路径和报告命令是否正确。

复现者记录：

- 成功步骤；
- 与 README 不一致的地方；
- 手工补充步骤；
- 实际运行时间；
- 失败信息及修复。

修正 README 后，从新环境再次执行失败步骤。

## 16. 阶段 10：打包与提交

### 16.1 PDF 报告检查

- [ ] PDF 可以打开，字体和图表清楚。
- [ ] 姓名、学号和组员信息正确。
- [ ] 截止时间和课程代码正确。
- [ ] 每张图、表在正文被引用。
- [ ] 表格标题、单位、样本数完整。
- [ ] 引用和链接可读。
- [ ] AI 使用已声明。
- [ ] 没有 token、密码、本机用户名或无关绝对路径。

### 16.2 代码 ZIP 检查

建议文件名：

```text
DSA5208_Project1_Code.zip
```

ZIP 应包含：

- `README.md`；
- Compose 和配置文件；
- 所有实验与分析脚本；
- `.env.example`；
- 少量代表性或处理后的结果；
- 依赖文件；
- 许可证/引用说明（如需要）。

ZIP 不应包含：

- Canvas token；
- 数据库密码；
- `.env`；
- Git 目录；
- Docker volumes；
- 大量无关日志；
- Python/IDE cache；
- 个人凭证。

### 16.3 最终提交文件

```text
DSA5208_Project1_Report.pdf
DSA5208_Project1_Code.zip
```

### 16.4 提交后验证

- [ ] Canvas 显示 submitted，而不是仅上传到浏览器。
- [ ] 下载 Canvas 中的已提交文件并重新打开。
- [ ] PDF 与本地最终版本哈希一致。
- [ ] ZIP 能解压，README 和脚本存在。
- [ ] 所有应提交的组员均显示正确状态。
- [ ] 保存提交确认页面或回执。

## 17. 截止日前进度表

| 日期 | 目标 | 负责人 | 当日验收 |
|---|---|---|---|
| 9 月 21 日 | 建仓库、冻结方案、完成 Compose 骨架 | A 主导，B/C 复核 | 三节点可启动 |
| 9 月 22 日 | replica set、delayed secondary、preflight | A | 正常复制及延迟验证通过 |
| 9 月 23 日 | 四个 workload 和统一 JSONL | B | smoke tests 全通过 |
| 9 月 24 日 | secondary/primary failure 和网络分区 | A+B | 分区与停机证据明确分开 |
| 9 月 25 日 | 正式矩阵、数据处理、图表 | B+C | 原始数据、汇总和图可追溯 |
| 9 月 26 日 | 报告完整初稿、引用、AI 声明 | C，A/B 补技术细节 | claim-evidence map 完成 |
| 9 月 27 日 | 独立复现、PDF/ZIP 验收、提交 | 全组 | Canvas 提交状态确认 |

如果进度落后，优先级为：

1. 完整满足四种一致性、三类场景和可复现提交；
2. 确保网络分区是真实链路隔离；
3. 保留原始证据并写清局限；
4. 再优化图表和增加运行次数；
5. 最后才考虑第二种数据库或额外实验。

## 18. 最终反例审查

提交前由三个人分别回答：

### 正确性

- 我们真的测试了四种不同性质，还是四个脚本其实都只是“写后读”？
- 网络分区时进程是否仍运行？
- 定向读取是否真的命中了 delayed/isolated secondary？
- 驱动是否自动重试并隐藏了首次失败？
- 自动判定是否可能把 timeout 当成 consistency violation？
- 最终值是否被错误当成完整操作历史？

### 证据

- 每个主要结论能否指向表、图或原始日志？
- 0 次 violation 是否写成了“未观察到”，而不是“证明保证”？
- 异常 trial 是否被透明报告？
- 样本数、配置和版本是否完整？

### 可复现性

- 干净电脑能否运行？
- README 是否包含从零开始的命令？
- 故障恢复脚本是否可靠？
- ZIP 是否缺文件或包含凭证？

### 写作

- 每个段落是否只有一个主要信息？
- 术语是否始终一致？
- prediction、observation 和 guarantee 是否混用？
- 局限是否具体，而不是泛泛地说“时间有限”？

只有当所有高风险问题都有明确答案，项目才进入提交状态。
