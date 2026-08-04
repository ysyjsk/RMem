# Plan-Robust Agent Memory：第一阶段严格工作计划 eval-protocol-v1.0-rc3

## 版本信息

- **依据文档**：`Plan_Robust_Agent_Memory_Proposal_v0.2`
- **文档状态**：冻结候选最终版；完成功效可行性、统计层级和执行环境 Gate 后方可冻结为 `eval-protocol-v1.0`
- **阶段名称**：Phase 1 — Evaluation Protocol and Test-Set Construction
- **唯一目标**：构造并冻结可复现、可审计、可证伪的测试集、测试指标、统计协议与测试原则
- **开发范式**：Test-Driven Development（TDD）
- **执行真相边界**：Proposal 负责科学 framing；本 Workplan、现有 schemas、`protocol/metric_spec_v1.md` 与 tests 共同构成唯一 execution source of truth。`修改建议-8.3.md` 合并后仅保留为决策记录，不得作为第二套执行文档
- **本阶段禁止事项**：不设计最终方法；不优化研究方法；不运行正式 acceptance 实验；不根据 acceptance 结果选择数据、预算、阈值、prompt 或 baseline
- **阶段完成标志**：全部 Gate 通过并发布不可变的 `eval-protocol-v1.0`，之后才能进入 feasibility pilot
- **预计关键路径**：协议、数据/模型/检索结构审计与 harness 约 14–16 个工作日；随后完成独立的 `D_leaf` qualification micro-run，方可进入 feasibility pilot。第二模型与第二数据集的完整 replication 不计入第一阶段关键路径，但其选择、结构资格和预算必须在本阶段冻结。Gate 未通过时顺延，不以日期覆盖验收条件

---

# 0. 最终核验结论与 Proposal 实施勘误

## 0.1 保持不变的核心部分

以下内容已经成立，原样保留：

1. consolidated memory 是 immutable evidence 上的有损物化视图；
2. primary experiment 固定 evidence 顺序、固定 leaf bytes，只改变 reduction topology；
3. 评价行为等价而非文本等价；
4. `Q_dev / Q_cal / Q_accept` 严格隔离；
5. Task Quality、Plan Robustness、Lifecycle Cost 三维分开报告；
6. acceptance sealing、manifest、checksum、provenance 和 access log；
7. P10：测试必须允许证伪研究；
8. 禁止在评测协议冻结前实现最终方法；
9. token-balanced 连续分区及其 deterministic tie-break；
10. online canonical balanced 必须作为强简单 baseline，并可直接关闭方法空间。

## 0.2 Proposal v0.2 的实施级勘误

Proposal 的科学命题不修改，但执行时必须采用以下勘误：

### E1. Fixed leaf 跨 budget 复用

Proposal 中“同一个 episode、budget 和 leaf seed 下复用 leaf”改为：

> 同一个 episode、leaf partition、`C_leaf`、leaf constructor、leaf prompt、leaf model 和 `s_leaf` 下，只生成一次 leaf；所有 budget 和 topology 均复用相同 leaf bytes。

budget 只作用于 internal/final merge，不作用于 leaf construction。

### E2. 数据集角色调整

- **LongMemEval-S knowledge-update / temporal**：主推断数据集；
- **MemoryAgentBench FactConsolidation-SH**：shared-context stress track；
- **MemoryAgentBench 其余 Conflict Resolution rows**：结构审计后决定 stress 子轨；
- FC-SH 不承担 cluster-level 主统计，不承担 development/calibration/acceptance 三分。

该调整只修复数据结构与统计单元冲突，不改变研究问题。

### E3. “合理成本”操作化

判断 online canonical balanced 是否关闭方法空间时，必须联合考虑：

- task quality；
- plan robustness；
- construction cost；
- deployment state amplification；
- prefix render/query cost；
- latency。

质量更好但依赖明显更大的 `O(B log n)` deployment state，不自动视为“简单方案已完全解决”。

### E4. NO-GO 是顺序 Gate，不是一次 null 即终止

如果 primary merge prompt 未发现 effect，必须先执行预注册的合理 stress prompt 分支，并检查统计功效、budget saturation 与 judge noise；只有全部条件满足时才能触发停止条件。

### E5. 科学效应阈值与可决策阈值分离

冻结：

```text
delta_SESOI = 0.05
```

它表示科学上关心的最小实际效应，不因样本量不足而改变。

另由冻结前的 `G-POWER-FEASIBILITY` 确定：

```text
delta_decision
```

它表示当前 acceptance 设计能够以至少 80% power 支持 GO/NO-GO 决策的最小效应。不得把“当前只能检测较大效应”解释为“小效应没有科学意义”。

### E6. Same-plan seed null 降为诊断量

`D_seed^95` 和 `Delta_Q_plan_cal` 保留，用于描述 stochastic variation，但不再作为 confirmatory GO 的硬 AND 条件。正式主检验是 episode × replicate block 内的 paired permutation；不可逆 NO-GO 依赖充分功效与区间/等价性结论，而不是单纯“不显著”。

### E7. Primary budget 使用统一轴

Primary budget sweep 明确规定：

```text
B_merge = B_final = B_query = B
```

“跨 topology 固定”只指同一个 budget 点内固定，不代表跨 budget 固定。`B_query` 指 answer model 接收的 memory payload 上限，不包含同一个唯一 `user.content` 中的 question、固定 instruction 和固定序列化开销；请求不存在 `system` 或 `developer` role。


### E8. `k` 参数化，但 primary 仍固定为 `k=8`

冻结：

```text
K_planned = {4, 8, 16}
k_primary = 8
k_max_planned = 16
```

Master split 与 leakage graph 不依赖某个单一 `k`。每个 episode 预先生成：

```text
eligible_for_k(e, k) = [atomic_evidence_count(e) >= k]
```

Primary `k=8` 使用 `E_8`；planned secondary k-sweep 必须在共同子集：

```text
E_16 = {e | atomic_evidence_count(e) >= 16}
```

上比较 `k ∈ {4,8,16}`，保证同一组 episode、同一 split 和同一 acceptance sealing。不得为了 k-sweep 重新划分数据。

### E9. k-sweep 是结构缩放检验，不自动等于纯 depth 因果检验

改变 `k` 会同时改变：

- leaf 输入跨度；
- leaf 数量；
- 总 leaf state；
- rewrite depth；
- merge 次数。

因此，固定 `C_leaf` 的 k-sweep 检验的是系统级结构缩放。若结果随 k 增长，只能说“与 rewrite-depth 机制一致”。

若要进一步声称 depth 因果机制，必须增加 matched-total-leaf-capacity sensitivity：

```text
k × C_leaf(k) = constant
```

或其他能够控制 leaf-state amplification 的预注册设计。该 sensitivity 只在 k-sweep 出现信号后于 calibration 上执行，不进入最小 pilot。

### E10. Confirmatory plan 集与 diagnostic plan 集分离

冻结：

```text
Pi_primary = {left_deep, canonical_balanced}
Pi_diag    = {left_deep, canonical_balanced, right_deep}
Pi_online  = {eager_left_deep, online_canonical_balanced}
```

`right_deep` 仅用于代数非结合性和 depth-identifiability 诊断，不进入部署相关的 confirmatory headline。

### E11. Backbone replication 是预注册轨道，不混入 primary 单变量实验

Primary backbone 仍按模型调用框架固定。另在 Day 1 选择并冻结一个不同模型家族的 replication backbone。每个 backbone 独立生成 leaves，不得跨模型复用 leaf bytes。

Primary GO/NO-GO 只基于 primary backbone。若要提出“跨模型家族成立”的论文结论，必须完成 replication backbone；否则结论明确限定于 primary operator configuration。

### E12. 第二数据源是 generality Gate，不伪造独立 cluster

Phase 1 必须完成至少一个独立来源候选数据集的结构审计，但不强制在本阶段完成第二 adapter。

LoCoMo 官方只有 10 个独立对话，因此不能被写成 50 个独立主推断 episode。它可以作为跨构造流程的 replication/stress 候选，但不能单独提供有力的 cluster-level confirmatory inference。

若在论文主实验前没有第二个具备足够独立 construction units 的数据源，则必须限制 claim 为 LongMemEval-specific，不得宣称普适 benchmark 结论。

### E13. Budget-Matched Retain 必须是强、查询条件化基线

Retain 不是顺序截断。它必须使用冻结的 query-conditioned retriever，在 `B_query=B` 内按相关性选择 raw evidence，并在最终 prompt 中按原始时间顺序渲染。Embedding、chunking、ranking、packing、tie-break 和 index revision 均属于评测合同。

# 1. 当前阶段的精确定义

本阶段不是“开始跑论文实验”，而是建立实验成立所需的全部前置合同。

最终必须交付：

1. 测试对象 schema；
2. 统一数据适配器和数据 manifest；
3. development / calibration / acceptance 划分；
4. fixed-leaf 与统一 budget-axis capacity 合同；
5. offline/online plan descriptor；
6. prompt、model、seed、repeat count 与 cache 合同；
7. budget 校准与 saturation 协议；
8. task-quality、plan-robustness 与 cost 指标；
9. paired permutation、same-plan diagnostic null 与功效仿真；
10. rewrite-depth、k-eligibility 与 cross-leaf evidence descriptors；
11. strong Budget-Matched Retain retriever contract；
12. primary/replication backbone manifest 与成本预算；
13. 第二数据源结构资格报告；
14. evaluator parity、snapshot 探活、repeatability 与缓存；
15. leakage、reproducibility、网络环境与 access audit；
16. protocol qualification report。

本阶段不回答：

- topology effect 是否存在；
- balanced 是否解决问题；
- 最终方法是什么；
- 哪个 memory system 最好；
- 论文是否可投稿。

本阶段可以在 development/calibration 上执行必要的 qualification micro-runs，但其唯一目的必须是冻结 evaluator、budget、功效和随机性合同，不能提前形成论文结论。

# 2. 不可违反的测试原则

## P1. 原始任务行为优先

评价对象是 query/task behavior，而不是 memory 文本相似度。

主评价优先使用原 benchmark 的 exact match、accuracy、F1、task success 或原始 judge score。BLEU、ROUGE、embedding similarity 仅作诊断。

## P2. Fixed-leaf 单变量原则

Primary topology comparison 中，下列条件全部固定：

- episode；
- ordered evidence；
- leaf boundaries；
- `C_leaf`；
- leaf prompt/model/config；
- `s_leaf = 0`；
- leaf bytes 和 SHA-256；
- merge prompt/model；
- `B_merge` 与 `B_final`；
- answer prompt/model；
- `B_query`；
- evaluator config。

不同 topology 之间只允许改变：

- reduction tree 的括号结构；
- 由该结构必然产生的 merge 输入、中间节点和最终 view。

Primary leaves 跨所有 budget 复用。不同 merge prompt 属于不同 operator configuration，不得混在同一 topology effect 中。

## P3. 原始顺序不可破坏

所有合法 topology 必须保持原始语义时间顺序。第一版禁止 random shuffle、非连续区间合并和未标注重排。

## P4. 行为等价而非文本等价

文本不同不构成错误；held-out query/task 行为不同才构成非等价。stale、omission、corruption、hallucination 等 operation-level 类别在 `eval-protocol-v1.0` 中保留定义，但其自动 judge 和大规模人工资格验证移到 `eval-protocol-v1.1`。

## P5. 统计单元不得伪造

必须区分：

1. memory-construction unit；
2. episode；
3. query；
4. operation-level item。

同一次 memory construction 下的多个 query 不是多个独立 construction replicate。

- LongMemEval-S：一个 evaluation instance 为一个 episode 和一个 construction unit；
- FactConsolidation：一个 dataset row/context 为一个 construction unit，内部问题只用于 context-conditioned query aggregation。

## P6. Query 与开发信息隔离

- `Q_dev`：prompt 编写、adapter 调试、规则开发；
- `Q_cal`：budget performance check、judge repeatability、seed/power estimation；
- `Q_accept`：正式 baseline 和后续方法确认。

Acceptance 在 protocol 冻结前不可读取。不得将同一 construction unit 的 query 跨 split。

## P7. Immutable source of truth

所有 evidence、leaf、merged node、answer 和 score 均必须可追溯到：

- dataset commit / file SHA-256；
- episode 和 evidence IDs；
- prompt hashes；
- model snapshot；
- seed axes；
- parent node IDs；
- evaluator cache key。

禁止覆盖 raw data 或只保存最终 memory。

## P8. Budget-conditioned 结论

所有结论按 budget 单独报告，同时报告绝对 token 数、raw-fit fraction 和 leaf-load ratio。

Primary sweep 中：

```text
B_merge = B_final = B_query = B
```

不得把 tight-budget 结果外推到 loose-budget，也不得把只改变 construction budget、却固定 query budget 的实验混入 primary sweep。

## P9. Evaluator 必须可审计

- 确定性 evaluator：保持原逻辑并通过 parity；
- 项目内 primary judge 按模型调用框架固定为 provider 上的 `gpt-5.5`，记录 requested/returned model、provider、base URL、prompt、参数和 cache；
- 若 provider 暴露 explicit version/snapshot，必须使用；若只暴露稳定 model ID，则冻结返回字段和全部 judge cache，并明确时间重放限制；
- 官方 LongMemEval GPT-4o 只作为 compatibility audit；可访问时使用带日期 snapshot，不改变项目内 primary judge 结果；
- 禁止 silent fallback；
- 新增 operation-level judge 不属于 `eval-protocol-v1.0`；
- primary judge endpoint 和 official compatibility snapshot（若计划使用）均在 Day 1 探活。

## P10. 不合并为单一总分

Task Quality、Plan Robustness、Lifecycle Cost 分开报告，不设计任意加权总分。

## P11. 测试集必须能够证伪研究

协议必须允许：

- effect 不存在；
- effect 未超过可决策阈值；
- pilot 或 acceptance 功效不足；
- budget 只有 saturation control；
- judge 不可靠；
- online balanced 已经解决；
- retention 占优；
- 数据不支持 claim。

不得通过删题、改预算、改 prompt、事后改变阈值或把相关重复观测伪装成独立样本来保留故事。

## P12. NO-GO 保护原则

不可逆停止条件不能由以下任一情形单独触发：

- 仅一个 merge prompt 为 null；
- 仅 ceiling/full-context-parity budget 为 null；
- formal test 功效不足；
- judge repeatability 未通过；
- `abs(Delta_primary) <= D_seed_pair^95` 或 `D_diag <= D_seed_range^95`；
- paired permutation 不显著但 CI 仍无法排除 `delta_decision`；
- rewrite-depth 模型不可识别；
- same-plan null 的统计量尺度与真实统计量不一致。

## P13. 科学阈值与设计能力分离

固定：

```text
delta_SESOI = 0.05
```

冻结前根据实际 eligible count、grouped split、`R_formal`、judge flip rate 和 estimator-matched simulation 冻结：

```text
delta_decision
```

Null 结果只能排除当前设计有能力排除的效应。若 `delta_decision > delta_SESOI`，报告必须明确说明对 `[delta_SESOI, delta_decision)` 区间的效应仍然不可判定。

## P14. 进展停滞必须立即升级

执行中若出现以下任一情形，视为“在同一阶段原地踏步”：

- 同一失败 Gate 在两次实质不同的修复尝试后仍无进展；
- 连续一个工作会话没有新增通过测试、可审计产物或排除性证据；
- 反复修改同一配置、prompt 或脚本，但没有新的可检验假设；
- 当前阶段的前置条件实际未满足，却继续堆叠后续代码；
- 执行计划开始循环回到已经否决的方案。

一旦触发：

1. 立即停止盲目重试；
2. 生成 `stall_report_<date>.md`；
3. 明确当前阶段、已尝试方案、失败证据、最可能根因、可选路径和推荐决策；
4. **立即告诉用户**，不得静默绕过、拖延到阶段结束或用“继续优化”掩盖停滞；
5. 未完成反思和决策前，不进入下一里程碑。


## P15. `k` 不得改变 split

`k` 是 plan/leaf-construction 参数，不是数据划分变量。Master split 先冻结，再为每个 `k` 生成 deterministic eligibility mask。任何 k-sweep 必须使用相同 episode 交集，不得重做 leakage graph 或 acceptance split。

## P16. 计划集合必须按 claim 分层

- `Pi_primary` 支持部署相关 confirmatory claim；
- `Pi_diag` 支持代数非结合性、位置和深度机制分析；
- `Pi_online` 支持实际在线部署 Gate。

不得用 diagnostic-only plan 撑大 headline effect。

## P17. Backbone 与 Retriever 都是显式实验维度

Primary topology comparison 内固定 backbone 和 retriever。模型家族变化、embedding 变化或 retrieval policy 变化必须进入独立 replication/sensitivity track，不得与 topology 变化混在同一对比中。

## P18. 数据集 generality 不得由共享来源替代

同一 benchmark 的长度变体、同源生成版本或共享 construction units 不构成独立数据源复制。跨数据集 claim 必须来自独立构造流程，并按真实 construction-unit 数量报告。

# 3. TDD 总执行规则

```text
写合同
→ 写失败测试（Red）
→ 实现最小功能（Green）
→ 重构但不改变合同（Refactor）
→ 生成审计产物
→ 冻结版本
```

任何功能没有测试，不视为实现；任何数据转换没有 provenance/checksum，不视为可用；任何 evaluator 没有资格验证，不视为有效；任何 split 没有 leakage test，不视为冻结。

## 3.1 外网访问与代理

执行环境访问 Hugging Face、GitHub、模型 API 或其他外网资源时，可以使用端口：

```text
17897
```

连接顺序固定为 direct → `http://127.0.0.1:17897`：先直连，直连失败后才设置回环代理进行第二次实质不同的尝试。

代理回退配置：

```bash
export http_proxy=http://127.0.0.1:17897
export https_proxy=http://127.0.0.1:17897
export HTTP_PROXY=http://127.0.0.1:17897
export HTTPS_PROXY=http://127.0.0.1:17897
```

要求：

1. Day 1 分别执行直连与必要的代理回退探活并记录结果，禁止默认先走代理；
2. 不假设代理永久可用，每次关键下载前执行轻量连通性测试；
3. 下载数据后仍以 file checksum/commit 为真值，不能把“请求成功”当作数据正确；
4. API judge 或模型请求必须记录是否经过代理、目标 endpoint 和失败原因；
5. 若 `127.0.0.1:17897` 在当前机器不可达，应检查 SSH reverse tunnel/代理进程，而不是直接修改研究协议。
6. 直连和代理两次实质不同的尝试仍无进展时，立即生成 stall report 并报告用户，不得无限重试。

### 3.1.1 Day 1 API 与纯净消息合同

Day 1 与后续正式生成调用冻结为：

```text
base_url: https://api.labforge.cc/v1
model_inventory_endpoint: /models
generation_endpoint: /chat/completions
generation_url: https://api.labforge.cc/v1/chat/completions
request_protocol: OpenAI-compatible Chat Completions
request_output_limit_field: max_tokens
max_route_attempts: 2
response_field: choices[0].message.content
usage_fields: prompt_tokens, completion_tokens
fallback_order: direct, http://127.0.0.1:17897
```

每个生成请求必须包含 exactly one `user` message；客户端不得注入 `system` 或 `developer` message，不得添加隐藏 prompt，也不得改用 `/responses`。这里的“纯净”仅证明客户端 payload 符合合同；对 provider 侧不可见策略不作无法验证的声明。

每个 probe artifact 必须记录最终 URL/endpoint、实际 route、requested/returned model、usage、request ID、response hash 和失败尝试。API key 只能从环境变量读取，禁止写入 artifact、日志、cache 或版本库。

### 3.1.2 Day 1 artifact 新鲜度与 run identity 合同

反思记录：此前曾在 `python -m plan_robust_memory.probe_day1` 仍运行时读取 `artifacts/day1/model_inventory.json`，看到旧 run 的 HTTP 400 后提前判定本次 inventory 失败并中止进程。该结论无效。原因是旧实现先在内存中完成 inventory、115K、judge、embedding 与 cost 等步骤，最后才统一覆盖八个 artifact；运行中读取同名文件无法证明它属于当前进程。本次最终落盘证据反而显示 `model_inventory.json` 已通过 direct HTTP 200。

为防止再次误判，Day 1 artifact 必须满足以下新鲜度合同：

1. 运行开始时立即写入 `day1_run_state.json`，包含 `run_id`、`state=running`、`started_at`、`pid` 和八个 artifact 文件名；
2. 运行开始时立即用同一 `run_id` 的 `pending` artifact 原子替换八个旧 JSON，禁止裸露上一轮 artifact；
3. 每个 sub-gate 完成后立即原子发布对应 artifact，不得等整轮 run 结束才批量写入；
4. 任何 agent、脚本或人工诊断在 `day1_run_state.json` 不存在、`state != completed`、artifact `run_id` 不一致或 `artifact_state != completed` 时，只能把该目录判为 `unknown / running`，不得据此报告 passed 或 blocked；
5. 停止或中止运行前，必须先记录当前 `run_id`、进程状态、artifact mtime/ctime 与 `day1_run_state.json`，并在进程结束后重新核对同一 `run_id` 的最终 artifact set；
6. 任何 Day 1 结论必须引用同一 `run_id` 下完整八文件和 completed run state，mtime 只能作为辅助证据，不能替代 run identity。

## 3.2 防止原地踏步的执行循环

每个 milestone 每个工作会话结束时必须记录：

```text
当前 Gate
本次新增测试
新增通过项
新增失败证据
下一次唯一最高优先级动作
```

若触发 P14，必须立即向用户报告，不得继续重复执行。该规则属于项目执行合同，不是可选的沟通习惯。

# 4. 建议仓库结构

```text
project/
├── proposal/
│   └── Plan_Robust_Agent_Memory_Proposal_v0.2.md
├── protocol/
│   ├── implementation_errata_v1.md
│   ├── terminology_v1.md
│   ├── evaluation_contract_v1.md
│   ├── capacity_contract_v1.md
│   ├── k_axis_contract_v1.md
│   ├── retriever_contract_v1.md
│   ├── backbone_replication_contract_v1.md
│   ├── replication_dataset_contract_v1.md
│   ├── seed_contract_v1.md
│   ├── metric_spec_v1.md
│   ├── statistical_protocol_v1.md
│   ├── power_feasibility_v1.md
│   ├── depth_analysis_v1.md
│   ├── no_go_protocol_v1.md
│   ├── network_environment_v1.md
│   ├── stall_escalation_v1.md
│   └── decision_log.md
├── schemas/
│   ├── episode.schema.json
│   ├── evidence.schema.json
│   ├── query.schema.json
│   ├── leaf.schema.json
│   ├── plan.schema.json
│   ├── run.schema.json
│   ├── score.schema.json
│   └── cost.schema.json
├── data/
│   ├── raw/
│   ├── normalized/
│   ├── splits/
│   ├── manifests/
│   ├── fixtures/
│   └── protected_acceptance/
├── src/
│   ├── adapters/
│   ├── validation/
│   ├── splitting/
│   ├── leaf_partition/
│   ├── plan_generation/
│   ├── evaluators/
│   ├── metrics/
│   ├── statistics/
│   └── logging/
├── tests/
│   ├── unit/
│   ├── property/
│   ├── integration/
│   ├── qualification/
│   ├── leakage/
│   ├── reproducibility/
│   └── regression/
├── configs/
│   ├── datasets/
│   ├── budgets/
│   ├── prompts/
│   ├── models/
│   ├── retrieval/
│   └── plans/
├── cache/
│   ├── leaves/
│   ├── embeddings/
│   ├── retrieval/
│   └── judge/
├── logs/
│   ├── access/
│   ├── progress/
│   └── stalls/
└── artifacts/
    ├── qualification/
    ├── reports/
    └── checksums/
```

---

# 5. 工作包 T0：术语、Schema 与随机因子合同

## 5.1 必须冻结的对象

### Episode

```text
Episode
├── dataset_id
├── dataset_version_or_commit
├── episode_id
├── construction_unit_id
├── ordered_evidence_ids
├── query_ids
├── family_id
├── split
└── provenance
```

### Evidence

```text
Evidence
├── evidence_id
├── episode_id
├── sequence_index
├── raw_content
├── token_count
├── event_time
├── valid_time
├── source_metadata
└── sha256
```

### Query

```text
Query
├── query_id
├── episode_id
├── question_type
├── is_abstention
├── query_text
├── gold_answer
├── evaluator_id
├── supporting_evidence_ids
└── split
```

### PlanNodeRaw

`PlanNodeRaw` 只保存不可推导的逻辑树事实：

```text
PlanNodeRaw
├── logical_node_id
├── plan_id
├── node_type                 # leaf / internal
├── leaf_id                   # leaf only
├── left_logical_child_id     # internal only
├── right_logical_child_id    # internal only
└── covered_span
```

`descendant_leaf_ids`、`tree_level`、`depth_to_root`、role path 和
`critical_path` 不得进入 raw schema；如为性能保留缓存，必须显式标记为
derived cache，并用递归 child-edge rebuild 测试证明一致。

### NodeArtifact

`NodeArtifact` 是原 `ViewNode` 的唯一物化形式。它只引用稳定的
`content_artifact_id`，不把本机绝对路径作为科学身份：

```text
NodeArtifact
├── materialized_node_id / logical_node_id / run_id
├── content_artifact_id / content_hash / artifact_kind
├── local_surrogate_content_tokens / capacity_tokens
├── tokenizer_snapshot / serialization_version / operator_config_id
├── deterministic_operator_hash
├── model_snapshot / prompt_hash / response_hash
├── creation_event_type / creation_event_id
├── schema_version / validation_status
├── materialization_source    # generated / cache / deterministic
└── artifact_status
```

`NodeArtifact` 不新增 `cache_source_artifact_id`。Generated API output 的
lineage 由 accepted binding 验证；cache 和 deterministic materialization 通过
creation/materialization event 与 source artifact 建立接受关系，其中
deterministic 还必须验证 `deterministic_operator_hash`。

### ModelCallAttemptRaw

所有 leaf、merge、answer、judge API 调用共用一套 raw attempt 记录。
`requested_model`、`provider` 和 `provider_route` 在每个 attempt 中均必须是
非空字符串。`returned_model` 和 `request_id` 的 key 也必须存在，但
值只在 provider 实际返回对应 identity 时记录：

- `accepted_materialized`、`successful_nonmaterialized` 和 `failed_parse`
  必须为非空字符串；
- `failed_validation`、`failed_provider`、`cancelled_before_start` 和
  `cancelled_after_start` 允许为 null，非 null 时仍必须是非空字符串；
- 不得使用 `"unknown"`、`"None"` 或其他伪造占位字符串代替
  provider 未提供的 identity。

每个 attempt 同时保存
`local_surrogate_serialized_input_tokens`、
`local_surrogate_output_content_tokens` 与 provider usage；
`provider_usage_source` 只能是 `provider_exact`、`provider_estimated` 或
`missing`。Missing 时 provider token 字段全部为 null，不得用
local surrogate count 冒充 provider usage。

`local_surrogate_content_tokens`、
`local_surrogate_serialized_input_tokens` 和
`local_surrogate_output_content_tokens` 当前均由
`surrogate_regex_bytes_v1` 产生，只能用于 deterministic partition、相对
长度比较和可复现的 pressure proxy，不得称为 exact model tokens。
所有以这些字段为输入的 pressure、compression、utilization 和
balance 指标都必须标记为 local-surrogate proxy。在 Q0 前，必须在
既有 G-COST 内部资格条件中二选一：冻结真实模型 tokenizer 及 immutable
revision；或提供 provider/tokenizer 误差界、有依据的 safety margin 与不
超过真实模型预算的测试证据。当前不得声称该资格已通过，也不
因此新增顶层 Gate。

### AcceptedOutputBindingRaw

`AcceptedOutputBindingRaw` 是 leaf、merge、answer、judge 阶段
accepted generated API output 的唯一事实源。成功 binding 与
accepted attempt 是一对一关系；`accepted_attempt` 若保留只能是该
引用关系的派生缓存，不能成为第二个真相源。Cache 和
deterministic materialization 不是 generated API output，通过
creation/materialization event 与 source artifact 建立接受关系，不得伪造
accepted API binding。

### MergeEventRaw

Merge event 保存逻辑 merge、左右 materialized node、输出 node、预算和
materialization source。Generated 必须引用 merge binding；cache 必须有
`cache_source_artifact_id` 且不得伪造 API attempt；deterministic 不进入
generative rewrite lineage。Merge event 不重复保存 NodeArtifact token 字段。

### Run

```text
Run
├── run_id
├── run_phase
├── replicate_id
├── episode_id
├── k
├── budget_id
├── plan_id
├── plan_set_id
├── operator_config_id
├── backbone_id
├── constructor_model_snapshot
├── merge_model_snapshot
├── answer_model_snapshot
├── embedding_model_snapshot
├── s_leaf
├── s_merge
├── s_answer
├── judge_config_hash
├── retrieval_config_hash
├── artifact_hashes / cost_artifact_id
├── accepted_output_bindings / merge_events
├── executor_config_hash / executor_mode / concurrency_limit
├── cache_mode / rate_limit_policy_hash / retry_policy_hash / provider_route
├── run_started_at / run_finished_at / replication_index
├── execution_order_index / run_batch_id / provider_observation_window
├── stage_timing_boundaries
└── status
```

### BackboneBundle

```text
BackboneBundle
├── backbone_id
├── role                  # primary / replication
├── model_family
├── constructor_model_snapshot
├── merge_model_snapshot
├── answer_model_snapshot
├── provider
├── endpoint
├── decoding_config_hash
├── day1_probe_artifact
└── cost_budget_artifact
```

### Plan

```text
Plan
├── plan_id
├── plan_family
├── plan_set_id           # primary / diagnostic / online
├── k
├── leaf_ids
├── plan_nodes             # PlanNodeRaw child graph; scientific topology truth
├── online_or_offline
├── prefix_queryable
├── rebuild_interval
├── budget_id
└── generator_version
```

### RetrievalConfig

```text
RetrievalConfig
├── retrieval_config_id
├── embedding_model_snapshot
├── tokenizer_snapshot
├── retrieval_unit_version
├── similarity_metric
├── candidate_top_k
├── packing_policy
├── render_order
├── tie_break
├── index_version
└── sha256
```

### Protected label access boundary

`ConstructionInputView` may read raw evidence, leaf configuration and plan
edges, but not query, gold answer, or supporting labels. `AnswerInputView` may
read final memory, query and answer configuration, but not gold/support labels.
Only `ScoringInputView` may load the protected label store, and only after run
artifacts and answers are frozen with an access log. The frozen mapping is
`supporting session -> atomic evidence -> chunk -> leaf`; every annotation
records `support_mapping_status` (`exact`, `expanded_to_chunks`, or
`unresolved`) and mapped IDs. Summary aggregation uses unique supporting leaves.

## 5.2 随机因子与重复次数合同

严格区分：

```text
s_leaf
s_merge
s_answer
s_judge
```

Primary topology protocol：

```text
s_leaf = 0
R_pilot = 3
R_formal = 5
```

第 `r` 个 repeated run：

```text
s_merge  = r
s_answer = r
```

同一个 `r` 必须在所有 topology 间配对，即 common random numbers。Judge 结果由固定 snapshot、配置和缓存确定，不把 judge 随机性混入 plan seed。

约束：

- Pilot 不得以 `R=3` 的精度支持 formal NO-GO；
- Formal 阶段必须使用 `R_formal=5`，除非在读取 acceptance 前升级 protocol version；
- 任何 pseudo-plan null 必须复现当前阶段对应的 R-run averaging structure；
- 重复运行增加的是 stochastic precision，不增加独立 episode 数量。

## 5.3 首批失败测试

- schema 缺失 construction unit 必须失败；
- evidence index 重复或断裂必须失败；
- plan 漏叶、重叶、乱序必须失败；
- node span 与 child span 不一致必须失败；
- topology 间 leaf SHA-256 不一致必须失败；
- budget 变化导致 leaf cache miss 必须失败；
- `s_leaf != 0` 进入 primary run 必须失败；
- topology 间同 replicate 的 merge/answer seed 不一致必须失败；
- rolling judge alias 进入 frozen config 必须失败；
- score 缺少 judge cache key 必须失败；
- primary budget 下 `B_merge != B_final` 或 `B_final != B_query` 必须失败；
- pilot/formal 使用错误的 R 必须失败；
- 把 repeated observations 计作独立 episode 的 power 输入必须失败；
- 未配置 periodic reconstruction interval 却启用该 plan 必须失败；
- plan 未声明 `plan_set_id` 必须失败；
- primary statistic 包含 `right_deep` 必须失败；
- k 不在预注册集合或 partition 公式硬编码为 8 必须失败；
- k-sweep 不使用 `E_16` 共同子集必须失败；
- 跨 backbone 复用 leaf cache 必须失败；
- formal Retain 缺少 retrieval config hash 必须失败；
- embedding 或 replication model 使用 rolling alias 必须失败。
- `PlanNodeRaw` 出现 depth、descendant leaves 或 role path 等派生字段必须失败；
- `NodeArtifact` content reference 不可解析或写入本机绝对路径必须失败；
- `NodeArtifact` 出现 `cache_source_artifact_id` 必须失败；
- generated materialization 没有且仅有一个 accepted binding 必须失败；
- cache/deterministic materialization 伪造 accepted API attempt 必须失败；
- 一个 logical call 出现两个成功 bindings 必须失败；
- construction/answer serializer 接触 gold/support labels 必须失败。

## 5.4 完成条件

所有非法 fixture 被拒绝；合法 fixture 通过；ID、hash、seed、binding、creation
event、protected-label access 和 cache key 规则冻结。Raw artifacts 删除所有
derived tables 后仍能重建 PlanMetrics、resource work 和 support exposure。

---

# 6. 工作包 T1：数据现实审计与数据源资格

## 6.1 Primary：LongMemEval-S knowledge-update / temporal

采用官方 cleaned 文件。必须由 adapter 实际读取并记录：

- 总 instance 数；
- 各 `question_type` 数；
- `_abs` 数及其类型分布；
- eligible KU/TR 非 abstention 数；
- session 数、token 数分布；
- `answer_session_ids` 重叠；
- base-question/family 关系；
- raw file SHA-256；
- provisional 20/30/50 grouped split 下的 development/calibration/acceptance 数量；
- 扩展到全部非 abstention question types 时的可用数量上限。

禁止将 issue 帖或论文中的 78、133、211 直接写成数据合同；实际文件 manifest 才是唯一计数依据。数据计数完成后必须立即触发 `G-POWER-FEASIBILITY`，不能等到统计代码全部完成后再判断设计是否可决策。

Primary `eval-protocol-v1.0` 默认：

```text
question_type ∈ {knowledge-update, temporal-reasoning}
and question_id does not end with "_abs"
```

`_abs` 进入 secondary abstention diagnostic，不进入 primary topology inference。

LongMemEval 一个 evaluation instance 定义为：

```text
1 episode = 1 construction unit = 1 primary cluster
```

## 6.2 Stress：MemoryAgentBench FactConsolidation / Conflict Resolution

已知官方数据是“一个 context 对多个 questions”，因此：

```text
1 row/context = 1 construction unit
```

不论最终审计出 1、4 或其他数量的 FC-SH context，均不承担主 cluster inference。

必须并行完成：

- 8 rows 的 `metadata.source`；
- question 数；
- context/token 长度；
- SH/MH 类型；
- 不同 rows 的 evidence/entity/question overlap；
- 是否 nested/prefix；
- dataset commit 和 parquet SHA-256。

报告方式：

- 每个 context 单独报告；
- query 先在 context 内聚合；
- 不把同一 context 的多个 query 当作独立 construction samples；
- 不把不同长度的 nested context 当作独立 cluster；
- 不做 dev/cal/accept 三分。

## 6.3 第二数据源与 Replication 结构审计

Phase 1 必须完成第二数据源候选的结构资格审计，但不要求在 `eval-protocol-v1.0` 前完成完整 adapter 和正式模型运行。

### LoCoMo

LoCoMo 可作为独立构造流程候选，但必须按真实结构处理：

- 独立 construction unit 是 conversation，不是 query；
- 官方数据只有 10 个 conversations；
- 内部多 query 先在 conversation 内聚合；
- 不得写成 50 个独立 episode；
- 审计 session 数、atomic evidence 数、`k ∈ {4,8,16}` 可行性、query evaluator、上下文长度和 supporting-evidence 可定位性。

因此 LoCoMo 的默认定位是：

```text
cross-source replication / stress track
```

而不是单独承担高功效 confirmatory inference。

### 第二主推断数据集 Gate

在论文级 cross-dataset claim 前，必须再识别至少一个满足以下条件的独立来源：

1. 足够多的独立 construction units；
2. 可定义有序 atomic evidence；
3. 支持 fixed-leaf/order-preserving topology；
4. query-level evaluator 可执行；
5. 不与 LongMemEval 共享 haystack 生成流程；
6. 可形成 acceptance sealing。

若未找到，允许继续 LongMemEval-specific feasibility，但必须限制结论范围，并在 stop/generalization decision 中明确说明。

### Phase 1 产物

```text
replication_dataset_audit_v1.md
locomo_structure_audit.json
replication_candidate_decision_log.md
```

## 6.4 Backbone Replication 资格

Primary backbone 由模型调用框架固定。Day 1 还必须选择一个不同模型家族的 explicit snapshot 作为 replication backbone。

选择条件：

- 与 primary 不属于同一基础模型家族；
- 支持所需输入窗口和输出容量；
- 允许固定 model ID 或 provider version；
- 通过最小 constructor/merge/answer probe；
- 禁止自动 fallback；
- 生成独立 leaf cache。

Replication 不进入 primary GO/NO-GO。它是 paper-level conclusion stability requirement。若无法获得合格的不同家族模型，必须把结论限定为 single-backbone。

## 6.5 数据资格测试

每个 adapter 必须通过：

1. count preservation；
2. order preservation；
3. content/gold hash preservation；
4. evaluator parity；
5. round-trip provenance；
6. no silent drop；
7. deterministic rebuild；
8. source commit/file checksum 固定；
9. construction unit 不被错误拆分；
10. `_abs` 分类与排除规则可复现。

## 6.6 完成产物

```text
longmemeval_data_audit.json
memoryagentbench_cr_audit.json
locomo_structure_audit.json
replication_candidate_decision_log.md
backbone_replication_probe.json
dataset_manifest.json
conversion_log.jsonl
excluded_items.jsonl
checksums.sha256
```

---

# 7. 工作包 T2：统一测试集构造

## 7.1 三层测试单元

1. Episode/construction unit：split、leaf、plan、cluster；
2. Query：task score；
3. Operation item：`eval-protocol-v1.1` 错误审计。

Primary score 先在 episode 内聚合 query，再在 episode 间 macro-average。

## 7.2 LongMemEval Atomic Evidence

默认 atomic evidence 为一个 timestamped session。Session 内 turn 不因 topology 需要而拆分。

若单 session 超过硬输入限制：

1. 标记 `oversized_atomic_item`；
2. 使用预注册 deterministic turn-boundary chunking；
3. 所有 budget/topology 共用相同结果；
4. 不根据 query、gold 或 answer session 调整边界。

## 7.3 Master Episode 纳入条件与 k Masks

Master episode pool 的纳入不硬编码 `k=8` 或 `k=16`。基础条件：

- 至少 4 个非空 atomic evidence；
- query/gold/evaluator 可执行；
- evidence 顺序明确；
- 无不可恢复字段；
- leaf construction 不读取 query/gold。

对每个 episode 冻结：

```text
atomic_evidence_count
eligible_for_k4
eligible_for_k8
eligible_for_k16
```

定义：

```text
E_k = {e | atomic_evidence_count(e) >= k}
```

使用规则：

- primary `k=8` 使用 `E_8`；
- planned k-sweep 在 `E_16` 上同时运行 `k=4,8,16`；
- split、leakage group 和 acceptance sealing 基于 master pool，只生成一次；
- 不允许为某个 k 重新划分；
- 每个 split 分别报告 `N_master / N_4 / N_8 / N_16`。

Full Context 是否答对不作为删除条件，只用于 diagnostic。


# 8. 工作包 T3：划分、泄漏与 Acceptance Sealing

## 8.1 Split 用途

### Development

adapter、prompt、规则、fixture、代码开发。可以反复查看。

### Calibration

budget performance classification、judge repeatability、seed variance、power estimation和 feasibility pilot。不得训练或事后重写 primary prompt。

### Acceptance

正式 baseline 和后续方法确认。Protocol 冻结前不可读取。

## 8.2 Provisional Split 与功效约束

LongMemEval 初始候选比例为：

```text
development = 20%
calibration = 30%
acceptance  = 50%
```

该比例是 **provisional design**，不是在功效检查前不可修改的常量。比例应用于 group，而非单个 query。

冻结规则：

1. 先使用实际数据 manifest 和 leakage groups 计算各 split 的 master construction units，以及 `N_4/N_8/N_16`；
2. 执行 `G-POWER-FEASIBILITY`；
3. 只有 acceptance 的 primary `E_8` 对冻结的 `delta_decision` 达到至少 80% power，比例才可冻结；k-sweep 的 `E_16` 功效单独报告，不阻塞 primary freeze；
4. 若不可达，必须在任何 topology 结果产生前选择并记录：
   - 扩展 eligible question types；
   - 调整 dev/cal/accept 比例；
   - 增加第二个主推断数据集；
   - 或将 `delta_decision` 提高到预注册、可达且仍具有系统意义的值；
5. `delta_SESOI=0.05` 不因 split 调整而改变；
6. 不得通过读取 acceptance 结果选择 split。

如果 group assignment 导致任一主要 `question_type` 在 calibration 或 acceptance 中低于 20 个 instance：

1. 使用确定性分层 group assignment；
2. 保持 group 不跨 split；
3. 记录偏离 hash-only 的原因和算法；
4. 不得根据模型表现重新划分。

## 8.3 Group 构造

先建立 leakage graph，节点为 LongMemEval instances；以下任一关系产生边：

- 去掉 `_abs` 后 base question ID 相同；
- `answer_session_ids` 有交集；
- supporting evidence exact hash 重叠；
- normalized question exact duplicate；
- 已知 template/source family 相同。

每个 connected component 为不可拆分 group。

Haystack 中通用 filler session 的重叠只触发警报，不自动连边；否则可能把大量无关实例错误合成一个 giant component。

## 8.4 Label-free Design Pool

`development + calibration` 可以联合用于以下不读取 gold/score 的统计：

- raw token length；
- session count；
- fixed leaf token length；
- raw-fit fraction；
- leaf-load ratio。

涉及质量的 budget saturation check 只能使用 calibration。

## 8.5 Leakage tests

自动检查：

- construction unit overlap；
- episode/query exact overlap；
- base question overlap；
- answer/supporting session overlap；
- evidence exact overlap；
- normalized query overlap；
- template/source family overlap；
- prompt examples 与 acceptance overlap；
- near duplicate 警报。

所有豁免必须进入 `leakage_decisions.jsonl`。

## 8.6 Acceptance 保护

- manifest 可见，query/gold 内容受保护；
- `make test`、`make dev`、`make pilot` 不读取 acceptance；
- 仅 `RUN_MODE=acceptance` 且已有 frozen tag 时加载；
- 每次加载写 append-only log；
- accidental access 触发 protocol major version 变更或重新划分。

---

# 9. 工作包 T4：Parameterized Fixed Leaf、Capacity 与 Mechanism Descriptors

## 9.1 k Axis

冻结：

```text
K_planned = {4, 8, 16}
k_primary = 8
k_max_planned = 16
s_leaf = 0
```

第一阶段 primary pilot 只运行 `k=8`。`k∈{4,8,16}` 是 planned secondary axis，不得因 primary 结果临时增加其他 k。

## 9.2 Token-balanced 连续分区

对任意合法 `k`，第 `j` 个边界选择累计 token 最接近：

```text
j × total_tokens / k
```

的合法 evidence 边界，其中 `j=1...k-1`。

Tie-break：

1. 选更小 evidence index；
2. 保证剩余 evidence 足以形成剩余非空 leaf；
3. 不切 atomic evidence；
4. 算法版本、k 和 boundary hash 写入 manifest。

不得根据 query、gold、answer session 或 supporting evidence 调整。

## 9.3 k-sweep 可解释性

Primary `k=8` 固定 `C_leaf`。

planned k-sweep 默认同样固定 `C_leaf` 和 B，用于测试系统级结构缩放：

```text
leaf granularity + leaf-state amplification + merge count + rewrite depth
```

因此，`D` 随 k 增长不能被单独称为 depth 因果证明。

若 k-sweep 出现信号，才允许在 calibration 上执行 matched-total-leaf-capacity sensitivity：

```text
k × C_leaf(k) = constant
```

该 sensitivity 必须使用预注册容量取整规则和同一 `E_16` episode 集。

## 9.4 容量层级与统一 Primary Budget Axis

严格定义：

```text
C_leaf   = 每个 leaf constructor 的最大输出 tokens
B_merge  = 每个 internal merge node 的最大输出 tokens
B_final  = root/final memory 最大 tokens
B_query  = answer model 接收的 memory payload 最大 tokens
```

在固定 `(backbone, k)` 内，`C_leaf` 跨 budget 和 topology 固定。

Primary sweep 强制：

```text
B_merge = B_final = B_query = B
```

解释：

- 同一 budget 点内，B 在所有 topology 间相同；
- 不同 budget 点之间同步变化；
- `B_query` 不包含同一个唯一 `user.content` 中的 question、固定 instruction 和固定序列化开销；请求不存在 `system` 或 `developer` role；
- 固定开销单独记账；
- `f_raw(B)` 与 `rho_leaf(B,k)` 使用同一个 B。

## 9.5 Leaf Constructor

必须 query-independent、gold-blind，并固定：

- backbone；
- model snapshot；
- prompt；
- decoding；
- k；
- partition hash；
- `C_leaf`；
- `s_leaf`。

Cache key：

```text
sha256(
  dataset_version_or_commit
  + episode_id
  + k
  + partition_hash
  + evidence_span
  + C_leaf
  + leaf_prompt_hash
  + constructor_model_snapshot
  + decoding_config
  + s_leaf
)
```

不得包含：

```text
budget_id
topology_id
query_id
```

不同 backbone 或不同 k 的 leaf 不可复用。

## 9.6 Fixed-leaf Hard Tests

- 同一 `(episode, backbone, k, partition, seed)` 得到同一冻结 bytes；
- 同一 `(episode, backbone, k)` 的所有 budget/topology 引用相同 leaf SHA-256；
- 不同 k/backbone 使用不同 cache namespace；
- spans 连续、互斥、全覆盖；
- leaf provenance 合法；
- 不含 query/gold；
- 不超过 `C_leaf`；
- budget 变化不触发 leaf regeneration；
- primary sweep 中 `B_merge=B_final=B_query`；
- k-sweep 使用相同 `E_16`。

## 9.7 Rewrite-depth 与 Evidence-layout Descriptors

对每个 `(episode, k, plan)` 预计算：

```text
d_mean(e,k,T)
d_max(e,k,T)
d_joint(e,k,T)
n_supporting_leaves(e,k)
evidence_spans_multiple_leaves(e,k)
support_leaf_positions(e,k)
```

其中：

```text
evidence_spans_multiple_leaves(e,k)
= [n_supporting_leaves(e,k) > 1]
```

解释限制：

- `false` 不表示 topology effect 结构上必为零；
- 单 leaf evidence 仍会因 leaf-to-root rewrite depth 和 merge partner 不同而受 topology 影响；
- 该布尔量只表示是否需要跨 leaf 联合 evidence；
- 不允许直接用 `fraction × n` 代替有效样本数。

Descriptors 在任何 topology answer 输出前冻结。无可靠 `answer_session_ids` 时标记 `not_applicable`。


# 10. 工作包 T5：Budget 校准与 Saturation 分类

## 10.1 候选 Grid

成本上界使用的候选 budget envelope 现在冻结为以下完整集合；它是成本
合同，不等同于 M8 在读取 topology 结果前选择的最终 budget 子集：

```text
B_cost_envelope = {128,192,256,384,512,768,1024,1536,2048,3072,4096}
```

最终 `B_grid` 只能是该集合的子集。任何新增点、超出 `C_leaf` 或模型
输出上限的点，都必须重新生成完整 workload、pricing 和 cost artifact，
并重新通过 Day 1 cost Gate；不得在读取 topology 结果后增加有利点。

## 10.2 两个结构指标

### Raw-fit fraction

```text
f_raw(B)
= Budget-Matched Retain 在 B 内可原样容纳的候选 evidence tokens
  / 全部候选 evidence tokens
```

### Leaf-load ratio

```text
rho_leaf(B)
= sum_i token_count(l_i) / B
```

二者均在 label-free design pool 上计算分布，不只报告中位数，还报告 P25/P50/P75。

## 10.3 Budget-Matched Retain Retriever Contract

Budget-Matched Retain 必须是 query-conditioned strong baseline。

### Retrieval Unit

默认 retrieval unit 为原始 timestamped session。若 session 超过 embedding/model 输入限制，使用与 T2 一致的 deterministic turn-boundary chunks。

### Embedding

必须冻结：

```text
model = BAAI/bge-m3
revision = explicit commit/tag
tokenizer_revision = explicit commit/tag
precision = fp16
similarity = cosine over normalized vectors
```

禁止仅写模型别名而不记录 revision。

### Ranking 与 Candidate Set

- query embedding 只使用当前 question；
- 禁止使用 gold、`answer_session_ids` 或 supporting labels；
- 默认对全部 retrieval units 排序：

```text
candidate_top_k = all
```

不设置会削弱基线的任意小 top-k。若因工程限制设置 cap，必须在 design pool 上证明 cap 不绑定，且在 acceptance 前冻结。

Tie-break：

```text
score descending
→ sequence_index ascending
→ evidence_id lexicographic
```

### Budget Packing

按 relevance ranking 执行 deterministic greedy packing：

1. 尝试加入当前 unit；
2. 计入 timestamp、speaker、separator 和序列化 token；
3. 若加入后超过 `B_query`，跳过该 unit并继续；
4. 不截断 unit；
5. 直到候选耗尽。

选择完成后，最终 prompt 按原始时间顺序渲染被选 units，避免 relevance-order 破坏 temporal reasoning。

### Cache 与公平性

Retrieval cache key 包含：

```text
question_id
raw_evidence_manifest_hash
embedding_snapshot
retrieval_unit_version
ranking_config
packing_config
B_query
```

Full Context、Retain 和 topology answer 使用相同 answer model、answer prompt 和输出参数。

必须生成：

```text
retriever_contract_v1.md
retrieval_config_v1.yaml
retrieval_index_manifest.json
retain_packing_audit.json
```

## 10.4 Budget 选择算法

1. 先按 `f_raw` 目标 `{0.25, 0.50, 0.75, 0.95}` 选择最近的未重复候选；
2. 记录对应 `rho_leaf`，不强制全部落入某个区间；
3. 检查是否至少覆盖：
   - 一个 `rho_leaf > 2` 的有损归约点；
   - 一个 `rho_leaf <= 2` 的 transition/near-fit 候选；
4. 若无法覆盖，允许在 **未查看 topology 结果前** 调整 `C_leaf` 或候选 grid，并重新生成整个 design manifest；
5. 一旦 primary leaves 生成并冻结，`C_leaf` 不再调整；
6. acceptance 不参与任何选择。

禁止使用 `k·C_leaf/B ∈ [4,16]` 作为全局硬约束。

## 10.5 SATURATION-01 / CEILING-01

在 calibration 上真实运行 Full Context 与 Budget-Matched Retain，并通过冻结的 evaluator 判分。该步骤不是纯 token 统计，必须单独预算模型调用、长上下文吞吐和 judge 成本。

定义：

```text
gap_full(B) = Q_full_context - Q_retain(B)
```

分类：

- `gap_full(B) > 0.02`：signal-bearing budget candidate；
- `gap_full(B) <= 0.02`：full-context-parity control；
- 若同时 `Q_full_context >= 0.95`：可进一步称为 ceiling control。

处理规则：

1. parity/ceiling 点保留并报告，不删除；
2. parity/ceiling 点不能单独支持“topology effect 不存在”的 NO-GO；
3. hard NO-GO 至少需要一个 `gap_full(B) >= delta_decision` 的 signal-bearing budget；
4. 如果所有可行 B 都为 parity control，则结论是“budget-conditioned feasibility 不可判定或仅测 rewrite-only effect”，不是项目 NO-GO；
5. 不将 full-context parity 错写成任务绝对天花板，除非 `Q_full_context >= 0.95`。

## 10.6 预算公平性

Primary comparison 固定：

- `C_leaf`；
- `B_merge`；
- `B_final`；
- `B_query`；
- answer model/prompt；
- retriever/render policy。

方法专有 metadata：

- 按冻结 capability profile 计入 deployment state；共享 index/source state
  另列，不得混入 plan-specific deployment state；
- 进入 prompt 的部分计入 `B_query`；
- 不得在成本表中隐去。

## 10.7 产物

```text
capacity_contract_v1.md
budget_grid_v1.json
raw_fit_curves.csv
leaf_load_curves.csv
retriever_contract_v1.md
retrieval_config_v1.yaml
retain_packing_audit.json
budget_saturation_report.json
budget_selection_decisions.md
```

---

# 11. 工作包 T6：Plan Set、Prompt 与 Backbone Operator 合同

## 11.1 三个 Plan Sets

### Confirmatory Primary

```text
Pi_primary = {left_deep, canonical_balanced}
```

- `left_deep` 是自然 eager online 行为的离线等价探针；
- `canonical_balanced` 对应可在线实现的 balanced compaction 目标；
- primary headline 使用二者的配对差异，不由 right-deep 撑大。

### Diagnostic

```text
Pi_diag = {left_deep, canonical_balanced, right_deep}
```

`right_deep` 只用于：

- 非结合性范围；
- 时间位置镜像；
- depth identifiability；
- algebraic diagnostic。

### Online Deployment

```text
Pi_online = {eager_left_deep, online_canonical_balanced}
```

用于 G3 / Pareto Gate，不与 offline primary statistic 混报。

所有 plan 使用全部且仅使用一次 leaf，保持 inorder 和连续 span。

## 11.2 Online Plans

保留 eager left-deep、online canonical balanced binary-counter compaction 和 periodic reconstruction descriptor。

任意 prefix 必须 queryable，不得引用未来 leaf。

Periodic reconstruction 必须显式配置：

```text
rebuild_interval = null | positive_integer
```

规则：

- `null` 表示 disabled；
- 启用时 interval 在运行前由 plan config 给出；
- 不得由当前 run 的质量或成本结果动态选择；
- 多 interval 候选必须预注册并只在 calibration 选择；
- interval、触发次数和成本进入 manifest。

## 11.3 Backbone Operator Config

Primary backbone 与 replication backbone 分开定义：

```text
OperatorConfig
= (constructor_model, merge_model, answer_model,
   leaf_prompt, merge_prompt, answer_prompt,
   C_leaf, B, k)
```

规则：

- primary topology comparison 内只改变 plan；
- replication backbone 使用独立 leaves、merge 和 answers；
- judge 可以保持统一以便比较；
- 不允许 primary 与 replication 的 artifacts 混入同一 `Q_T`；
- 跨模型只比较 effect direction、rank stability 和 effect-size consistency。

Day 1 生成：

```text
backbone_manifest_v1.json
primary_backbone_probe.json
replication_backbone_probe.json
backbone_cost_budget_v1.json
```


## 11.4 Prompt Artifacts

M6 必须产生并冻结：

```text
leaf_prompt_v1.txt
merge_prompt_v1_primary.txt
merge_prompt_v2_stress.txt
answer_prompt_v1.txt
render_prompt_v1.txt
prompt_manifest.json
```

### Primary merge prompt

目标是保守、事实保持、时间方向明确、输出预算明确。

### Stress merge prompt

必须在查看 primary pilot 结果前冻结，满足：

- 仍是合理可部署的 consolidation prompt；
- 更强调抽象、去重和跨 evidence 综合；
- 仍要求 provenance、时序和事实保持；
- 不是 deliberately broken prompt；
- 使用相同 model、capacity 和输出 schema。

两个 prompt 定义两个不同 operator：

```text
mu_(M, P1, B)
mu_(M, P2, B)
```

不得把二者结果混成同一个 primary effect。

## 11.5 Prompt NO-GO 分支

- GO 分支：primary prompt 满足 confirmatory GO 条件，则 stress prompt 后置为 sensitivity；
- Null 分支：primary prompt 在所有 signal-bearing budgets 上均未满足 confirmatory GO 时，必须先检查 power、judge repeatability 和区间结论；
- 若仍具备 NO-GO 判定资格，使用预注册 stress prompt 在 tight signal-bearing budget 重跑；
- 只有两个 prompt 均未达到 `delta_decision`，且 formal power 充分、CI 可排除 `delta_decision`，才允许继续判断停止条件；
- `abs(Delta_primary) <= D_seed_pair^95` 只能作为 seed diagnostic，不能单独阻断 GO 或触发 NO-GO；
- 如果只有 stress prompt 有 effect，结论为 **operator-contingent feasibility**，不是完整 GO；后续必须判断该 operator 是否具有合理质量和部署价值。

## 11.6 Property Tests

- inorder preservation；
- span coverage；
- merge count `k-1`；
- deterministic plan JSON；
- online no future read；
- prefix queryability；
- balanced depth bound；
- prompt hash 固定；
- operator config 不被 topology 运行修改；
- `Pi_primary` 不含 right-deep；
- `Pi_diag` 保留 right-deep；
- primary/replication backbone cache 隔离；
- plan descriptor 显式记录 k 与 plan_set_id。

## 11.7 T6 PlanMetrics 与 lineage 派生合同

T6 的 `PlanMetrics` 必须由 `PlanNodeRaw` child edges 递归重建，不调用模型，
也不读取 timestamps 重新排序。冻结字段为：

```text
descendant_leaf_ids
leaf_depth_vector
order_role_path_vector_root_to_leaf
tree_height
critical_path_merge_count
merge_count
deterministic_plan_hash
```

`order_role_path_vector_root_to_leaf` 中每条 role path 从 root 走向 leaf。
EvidenceExposure 的 `order_role_sequence_root_to_leaf` 使用相同方向；
`generative_merge_path_leaf_to_root` 则显式按 evidence leaf 到 root 的语义
merge 顺序保存 logical merge node IDs，不得使用无方向后缀的旧
path/sequence 字段建立并行真值。`earlier_span_fraction`、
`later_span_fraction` 和 order-role sequence 只由 frozen evidence order 与
covered spans 决定；`time_span_imbalance` 与
`boundary_real_time_gap` 只有 event/valid time 质量足够时才报告，否则为
`unavailable`。MergeEventMetrics 的 per-event 字段仅为布尔值
`is_generative_merge`；`generative_rewrite_depth` 只保留在
EvidenceExposure，且等于
`len(generative_merge_path_leaf_to_root)`，不受 cache hit、retry 或
failed attempt 影响。

T6 必须同时能从 creation event、accepted binding 和 merge event 重建
materialized lineage；任何失败 attempt 都不能进入 lineage。

---

# 12. 工作包 T7：评价指标、功效与统计协议

## 12.1 基础记号与 Plan Sets

- episode：`e`；
- budget：`B`；
- leaf count：`k`；
- plan：`T`；
- repeated run：`r=1...R`；
- query score：`s(e,k,B,T,r,q)∈[0,1]`。

冻结：

```text
Pi_primary = {L, Bal}
Pi_diag    = {L, Bal, R}
Pi_online  = {OL, OB}
```

先在 episode 内对 query macro-average，再在 episode 间 macro-average：

```text
S(e,k,B,T,r) = mean_q s(e,k,B,T,r,q)
Q(k,B,T,r)   = mean_e S(e,k,B,T,r)
Q_T(k,B)     = mean_r Q(k,B,T,r)
```

独立推断单元始终是 episode/construction unit。重复 plan/run 行不是独立样本。


## 12.2 Task Quality

对任意指定 plan set `P`：

```text
Q_mean(P,k,B)  = mean_{T in P} Q_T(k,B)
Q_worst(P,k,B) = min_{T in P} Q_T(k,B)
Q_best(P,k,B)  = max_{T in P} Q_T(k,B)
```

Headline 必须明确 plan set，不再使用无下标的模糊 `Q_worst`。


## 12.3 Primary Contrast 与 Diagnostic Range

### Confirmatory deployment-relevant contrast

```text
Delta_primary(k,B)
= Q_Bal(k,B) - Q_L(k,B)
```

正式检验采用双侧 paired test；同时报告符号。效应量为：

```text
abs(Delta_primary)
```

### Diagnostic three-plan range

```text
D_diag(k,B)
= max_{T in Pi_diag} Q_T(k,B)
- min_{T in Pi_diag} Q_T(k,B)
```

`D_diag` 只能称为 diagnostic tested-plan range，不作为 headline confirmatory effect。


## 12.4 Same-plan Seed Null：仅作诊断

Diagnostic null 必须与对应真实统计量使用相同 R-run averaging structure。

分别构造：

```text
D_seed_pair^95(k,B)   # 对应 abs(Delta_primary)
D_seed_range^95(k,B)  # 对应 D_diag
```

每次 bootstrap 必须以完整跨 episode 的 run vector 为单位，为每个 pseudo-plan 抽取 R 个 run vectors 后求均值，再计算 paired difference 或 range。

报告：

```text
abs(Delta_primary)
D_diag
D_seed_pair^95
D_seed_range^95
各自 uncertainty interval
```

它们只描述 stochastic variation，不作为 confirmatory AND gate，不单独触发 NO-GO。


## 12.5 正式主检验：Primary Paired Permutation

Confirmatory statistic 是 `Delta_primary(k_primary,B)`，只比较 `Pi_primary`。

在每个 `episode × replicate` block 内交换 `left_deep` 与 `canonical_balanced` 标签，保持 episode、replicate、query aggregation 和 common random numbers 不变。执行至少 10,000 次 permutation。

报告：

- signed paired difference；
- two-sided p-value；
- episode-clustered paired bootstrap 95% CI；
- win/tie/loss episode counts；
- question-type stratification。

`Pi_diag` 的三计划 omnibus/range permutation 作为 secondary diagnostic，并与 primary p-value 分开。

Mixed-effects/GEE 不替代 primary paired permutation。


## 12.6 两类效应阈值

### 科学最小效应

冻结：

```text
delta_SESOI = 0.05
```

表示科学上值得关注的 5 个绝对百分点，不因当前数据量改变。

### 当前可决策效应

冻结前由 `G-POWER-FEASIBILITY` 确定：

```text
delta_decision
```

它是当前 acceptance 设计能以至少 80% power 支持 GO/NO-GO 的最小效应。

约束：

- `delta_decision >= delta_SESOI`；
- 候选值必须来自预注册网格，例如 `{0.05, 0.075, 0.10, 0.125, 0.15}`；
- 选择规则、实际样本数、仿真代码和随机种子写入 `power_feasibility_v1.md`；
- 不得根据 topology 结果修改；
- 若 `delta_decision > 0.05`，报告必须明确：当前设计无法排除 `[0.05, delta_decision)` 的效应。

## 12.7 G-POWER-FEASIBILITY

该 Gate 必须在 split、`delta_decision` 和 protocol tag 冻结前通过。

### 阶段 A：解析筛查

使用实际 eligible/group 数量，对：

```text
discordance psi ∈ {0.10, 0.15, 0.25, 0.40}
```

计算：

- acceptance 对 5pp effect 的近似 power；
- 当前 acceptance 的近似 minimum detectable effect；
- 全部 KU/TR eligible 的上限；
- 扩展到全部非 abstention 类型时的上限。

解析计算只作数量级检查，不替代正式仿真。

### 阶段 B：Estimator-matched Simulation

必须模拟真实 primary 设计：

```text
Pi_primary = {left_deep, canonical_balanced}
R_pilot = 3
R_formal = 5
episode-level correlated binary outcomes
common random numbers
judge flip rate
paired permutation of Delta_primary
actual E_8 grouped split size
```

Primary effect grid 至少覆盖：

```text
Delta_primary ∈ {0, ±0.025, ±0.05, ±0.075, ±0.10, ±0.15}
多个 discordance 场景
```

同时使用实际数据中下列经验分层比例：

```text
question_type
single_support_leaf / multiple_support_leaves
evidence_position bins
```

允许不同 strata 具有不同 effect probability 和 discordance。

禁止使用：

```text
effective_n = fraction_multiple_leaves × n
```

单 supporting leaf 仍可能因 rewrite depth 和 merge partner 不同而受 topology 影响。正确做法是模拟异质效应，并报告总体与分层 power。

`Pi_diag` 的三计划 range 和 k-sweep `E_16` power 另作 secondary，不决定 primary `delta_decision`。

### 决策

若 acceptance 对任何仍有系统意义的候选 `delta_decision` 都无法达到 80% power，`eval-protocol-v1.0` 不得冻结。必须在任何 topology 结果产生前选择并记录：

1. 扩大 eligible question types，并分层报告 category × topology；
2. 调整 split 比例；
3. 增加第二个独立主推断数据集；
4. 将 `delta_decision` 提高到可达、预注册且仍有系统意义的值；
5. 或将本阶段明确降为 exploratory，取消 hard NO-GO 权限。

不得用重复运行数替代独立 episode 数。

## 12.8 Confirmatory GO 与 NO-GO

### Confirmatory GO

在至少一个 signal-bearing budget 上同时满足：

1. `Pi_primary` left-deep vs canonical-balanced paired permutation 通过预注册显著性阈值；
2. `abs(Delta_primary) >= delta_decision`；
3. clustered CI 已报告；
4. judge qualification 通过；
5. protocol 无违规。

`D_seed_pair^95` 不是必要条件。

### Formal NO-GO

不能由“不显著”直接推出。必须满足：

1. 至少一个 signal-bearing budget；
2. formal design power `>= 0.80`；
3. primary 与预注册 stress operator 均未达到 `delta_decision`；
4. CI 或预注册 equivalence procedure 能排除 `delta_decision`；
5. judge repeatability 合格；
6. 非 ceiling-only；
7. depth/机制分析没有被错误当成替代主效应；
8. online balanced Gate 已单独处理。

## 12.9 G-DEPTH-IDENTIFIABILITY

在不运行 topology answer generation 的情况下，按每个 `k` 使用 plan descriptors、leaf mapping 和 `answer_session_ids`：

1. 计算 `d_mean/d_max/d_joint`；
2. 计算 `n_supporting_leaves` 与 `evidence_spans_multiple_leaves`；
3. 报告 single-leaf/multi-leaf strata 的实际比例；
4. 检查 depth 与 plan、evidence position、question type、k 的共线性；
5. 检查 episode 内是否存在足够 depth variation；
6. 使用 `Pi_diag` 保留 right-deep 的镜像识别信息；
7. 用实际设计矩阵执行 episode-clustered binary-outcome power simulation；
8. 检查 k-sweep 中 total leaf state 与 depth 的共变。

限制：

- `evidence_spans_multiple_leaves=false` 不等于 topology-insensitive；
- 不得将其比例直接乘 n；
- 若 depth 与 plan/k 无法分离，机制分析降为 descriptive；
- k-sweep 单调性最多提供机制一致性，未经容量匹配不能称为纯因果验证。


## 12.10 Rewrite-depth 与 k-scaling 机制分析

H1 是 `Pi_primary` 的部署相关 paired contrast。

在 `eval-protocol-v1.0` 中不存在 confirmatory H2。若
`G-DEPTH-IDENTIFIABILITY` 通过，使用 `Pi_diag` 的 PlanMetrics、
EvidenceExposure 和 AnnotatedSupportExposure 做 episode-plan-run 内聚合，
报告 episode-clustered uncertainty interval；若未通过，仍可展示 raw
descriptors，但必须标为不可识别。

规则：

- `d_mean`、`d_max`、`d_joint` 与 `generative_rewrite_depth` 均为 secondary；
- `evidence_spans_multiple_leaves` 用于预注册分层，不是样本权重；
- source features 与 materialized mediators 分开；
- right-deep 仅进入 mechanism diagnostic 和 diagnostic range；
- 不把不同 topology 的第 n 个 merge 直接配对；
- 不用 post-treatment mediator 回归声称因果；
- 不产生 confirmatory mechanism p-value，也不替代 H1 或进入 GO/NO-GO。

若未来需要 logistic mixed model、episode-clustered GEE 或确认性机制 claim，
必须在读取相应结果前作为 `eval-protocol-v1.1` 的独立分析计划预注册。

Planned secondary k-sweep：

```text
k ∈ {4,8,16}
episodes = E_16
plans = Pi_primary + Pi_diag
```

主要观察 `Delta_primary(k,B)`、`D_diag(k,B)` 与 depth descriptors 是否随 k 系统变化。固定 `C_leaf` 的结果是结构缩放证据；若要做 depth 因果表述，必须增加 matched-total-leaf-capacity sensitivity。


## 12.11 Leaf-level Variance Qualification

Primary null 不包含 leaf variance，因为 `s_leaf=0`。

在 protocol tag 后、feasibility pilot 前执行独立 qualification micro-run：

- fixed balanced topology；
- fixed merge seed；
- fixed answer seed；
- `s_leaf ∈ {0,1,2,3,4}`；
- 至少 20 个预注册分层 calibration episodes。

报告：

```text
D_leaf = max_s Q_leaf(s) - min_s Q_leaf(s)
```

`D_leaf` 仅说明被 primary protocol 隔离的 leaf-generation variance，不从 `Delta_primary` 或 `D_diag` 中相减，也不混入 same-plan null。

该 micro-run 的 token、调用、费用和失败重试必须独立预算。未完成 qualification artifact 前不得开始 feasibility pilot。

## 12.12 Context Saturation Gap

```text
CSG(B,T) = Q_full_context - Q_T(B)
```

仅作 diagnostic，不删除样本，不证明 topology effect。

## 12.13 Lifecycle Cost

```text
C_life = C_construct + C_query
```

所有成本必须按 `backbone × k × budget × plan` 分层。

Construction 与 query 的 token usage 必须按 accepted-path 和 observed
operational 两套字段保存。每套字段至少保留 total input、cached input
subset、uncached input 和 output；

```text
uncached_input = input_total - cached_input_subset
```

Observed work 还包括 API attempt count、failed attempt count、successful
nonmaterialized count、accepted materialized generation count、cache hit、retry
token/latency overhead、sum attempt latency、critical-path elapsed latency 和
parallelism factor。`successful_nonmaterialized` 与 provider-executed failed
attempt 可能有真实 token/latency，但不进入 materialized lineage。

Construction 分为 shared leaf construction、plan-specific merge construction
和 answer/query；judge usage 与 latency 单独归档，不并入 memory lifecycle
cost。Missing provider usage 或 missing cost 必须是 `unknown`，不能默认为 0。

状态成本不再使用模糊的 `durable_state_tokens`，而拆为：

1. deployment state：`deployment_memory_tokens`、metadata bytes、冻结的
   capability profile 与 measurement point；
2. shared source state：`shared_leaf_tokens`、`shared_raw_evidence_bytes`；
3. experiment artifact footprint：`artifact_cache_bytes`。

Artifact footprint 只用于审计/复现，不进入 deployment lifecycle cost。Primary
offline 默认 capability profile 为 `FINAL_QUERY_ONLY`；online track 的所有
topology 必须使用相同 profile。

美元费用是可选的 run-level `PricingManifest` 派生视图，费率统一为 USD per
1M tokens，并保存 source access time、snapshot hash、provider/model/route 和
usage schema。没有 PricingManifest 时 estimated USD 为 `unavailable`，但
科学 resource metrics 仍可计算。

## 12.14 Online Balanced Pareto Gate

判断 online balanced 是否关闭方法空间时，至少比较：

```text
(Delta_primary, D_diag, Q_mean, Q_worst, C_construct,
 deployment_memory_tokens, render_cost, query_latency)
```

只有其关闭主要质量/方差差距且处于合理 Pareto 前沿，才算简单方法关闭空间。

## 12.15 Operation-level Audit

`eval-protocol-v1.0` 仅保留 omission、stale、corruption、hallucination、preservation、faithfulness 的 schema 和分母定义。

自动 judge、双人工标注和 adjudication 整体移到 `eval-protocol-v1.1`，不作为 `eval-protocol-v1.0` Gate。

## 12.16 T7 Observability secondary diagnostics

Phase 1 必选机制指标仅保留四类：

1. structural exposure：leaf depth、EvidenceExposure 层的
   `generative_rewrite_depth`、`order_role_sequence_root_to_leaf`、
   `generative_merge_path_leaf_to_root`、earlier/later span fraction 和
   relative position；
2. compression exposure：`content_to_budget_pressure`、`pressure_sum`、
   `pressure_max`、`actual_compression_ratio`、`output_budget_utilization` 和
   `payload_to_budget_ratio`；
3. merge balance：`token_imbalance_abs`、`token_imbalance_signed`，以及在
   时间字段可用时的 optional `time_span_imbalance`；
4. resource/execution：上述 accepted-path/observed operational 字段和阶段
   wall-clock。

这些变量只作为 descriptive secondary diagnostics。每个
episode-plan-run 先聚合，再报告 episode-clustered bootstrap interval；证据
行不能膨胀样本量，不同 topology 的第 n 个 merge 不直接配对，不产生
confirmatory p-value，也不进入任何 primary GO/NO-GO。

机制字段的 canonical names 为
`order_role_path_vector_root_to_leaf`、`order_role_sequence_root_to_leaf`、
`generative_merge_path_leaf_to_root`、`is_generative_merge`、
`earlier_span_fraction`、`later_span_fraction` 和
`critical_path_merge_count`。旧的无方向 path/sequence 名称与 per-event
`generative_rewrite_depth` 不得保留为并行字段。
`content_to_budget_pressure` 是结构代理，不证明 semantic retention。

## 12.17 T7 support exposure 与访问边界

Protected label store 的 gold answer/supporting evidence 只能在 scoring 阶段
加载；construction 和 answer input view 必须拒绝这些字段。映射链固定为
`supporting session -> atomic evidence -> chunk -> leaf`，每条 annotation
保留 exact/expanded/unresolved 状态和映射 ID。正式 summary 按 unique
supporting leaves 聚合，统一字段名：

```text
annotated_support_rewrite_mean
annotated_support_rewrite_max
annotated_support_pressure_mean
annotated_support_pressure_max
annotated_support_order_role_summary
```

# 13. 工作包 T8：Evaluator 资格验证与 Judge Cache

## 13.1 Deterministic Evaluator

MemoryAgentBench `fact_sh/fact_mh` 保持官方 `substring_exact_match` 语义，并测试：

- 正确；
- 错误；
- 多答案；
- 格式异常；
- 空输出；
- case/substring 边界。

## 13.2 Project Judge 与 Official Compatibility

Primary task judge 以同目录模型调用框架为准：

```text
model = gpt-5.5
role  = project_longmemeval_compatible_judge
```

Day 1 必须记录：

- requested model；
- returned model；
- provider/base URL；
- endpoint；
-访问日期；
-实际接受的 decoding 参数；
-代理 route；
-最小 parser probe。

规则：

1. primary judge 不得自动切换；
2. 所有正式分数只读冻结 cache；
3. provider 若无法保证权重永久不变，必须明确记录 time-replay limitation；
4. cache 保证当前实验 artifact 可重放，但不能伪称未来可重新生成相同 judge 输出；
5. 50×3 repeatability 是 primary confirmatory 资格 Gate。

官方 LongMemEval GPT-4o judge 作为 compatibility audit：

- 若官方 dated snapshot 可访问，在固定子集上做 agreement audit；
- 若不可访问，记录为外部兼容性限制；
- official audit 不替换或改写项目内 `gpt-5.5` 冻结结果；
- 不得自动回退到裸 `gpt-4o`。

Evaluator Parity 的官方代码来源冻结为：

```text
LongMemEval
repository = https://github.com/xiaowu0162/LongMemEval
commit     = 9e0b455f4ef0e2ab8f2e582289761153549043fc
path       = src/evaluation/evaluate_qa.py
sha256     = ecce9c4c79dc89d99534ac17b383a5cbb5b9f0c69ee98adaf0684742e3d95251

MemoryAgentBench
repository = https://github.com/HUST-AI-HYZ/MemoryAgentBench
commit     = 455306dcabc3842526eb83cd4e225e5d486c5c5d
path       = utils/eval_other_utils.py
sha256     = d77976be409298970614d477a9d8003850caddb0510e56a7e821a037d98493a2
```

真实 qualification 命令：

```bash
python -m plan_robust_memory.qualify_evaluator_parity
```

该命令按 direct -> `127.0.0.1:17897` 下载并核对官方源码，验证
MemoryAgentBench normalization/substring semantics 与 LongMemEval 五类 prompt
hash，同时复用已通过的 Day 1 inventory 和 judge probe，不重复外部 Gate。
`gpt-4o-2024-08-06` 若不在已通过 inventory 中，必须记录
`unavailable_external_limitation`，compatibility call count 为 0，且不得回退
到 rolling `gpt-4o`。运行中或失败时只能依据
`evaluator_parity_run_state.json` 的本次 `run_id` 判断状态，不得读取旧同名
artifact 宣称本次通过或失败。


## 13.3 Judge Cache

Cache key：

```text
sha256(
  question_id
  + reference_answer_hash
  + hypothesis_hash
  + judge_prompt_hash
  + judge_model_snapshot
  + decoding_config
  + output_schema_version
)
```

正式统计只能读取冻结 cache。相同 hypothesis 不得因 topology 或脚本路径不同被重复 judge。

## 13.4 50 × 3 Repeatability

为消除 P6/T3 与旧“development/calibration”措辞之间的自由裁量，Judge Repeatability 的唯一来源为冻结 20/30/50 划分中的 `Q_cal`；development 不进入该 50-case manifest，acceptance 不得读取。manifest 使用 selection
seed `judge-repeatability-calibration-v1`，按 episode ID 的稳定 hash 排序，50
个 case 必须来自 50 个不同 episode。类别互斥且配额冻结为：

Judge qualification 前必须先由 data-steward 执行一次 calibration-only 投影：

```bash
make materialize-longmemeval-calibration
```

该命令可以读取并扫描 combined `normalized_episodes.json`，但只能写出
`normalized_calibration_20_30_50.json` 与
`calibration_split_materialization_log.json`；投影必须绑定 dataset audit
hash、power artifact hash、20/30/50 assignment hash、source SHA-256 和完整
`Q_cal` episode ID 集合，并记录 `acceptance_payload_exported=false`。随后
`python -m plan_robust_memory.qualify_judge_repeatability` 只允许读取这个
calibration projection，禁止 `--normalized-episodes` 输入或任何 combined-store
路径。projection 校验失败时不得发出请求。

```text
gold_equivalent = 8
clearly_wrong = 8
partial = 8
temporal_reasoning = 7
knowledge_update = 7
formatting_variation = 6
abstention_like = 6
```

`temporal_reasoning` 与 `knowledge_update` 必须分别来自对应 LongMemEval task
type。gold-equivalent 使用 gold 等价答案；clearly-wrong 使用不包含 gold 的
固定无关答案；partial 使用 gold 的确定性严格子片段；formatting variation
只增加 answer framing；abstention-like 是对可回答 calibration question 的
拒答式 candidate，不读取已排除的 `_abs` item。`expected_semantic_label` 只
审计 case 构造，不进入 repeatability Gate，也不得被解释为人工一致性验证。

每个 case 按 manifest 顺序独立调用 judge 3 次，replicate ID 严格为
`0/1/2`，共 150 个唯一 `(case_id, replicate_id)` observation。调用固定为：

```text
endpoint = https://api.labforge.cc/v1/chat/completions
model = gpt-5.5
temperature = 0
max_tokens = 128
stream = false
messages = exactly one user message
response_format = not sent
```

项目 prompt wrapper 保留对应 LongMemEval official task semantics，只把官方
yes/no 输出要求替换为严格 JSON `{"label":0|1}`；official yes/no parser 与
项目 JSON parser 继续分离。每次先 direct；只有访问失败才使用
`127.0.0.1:17897`，两次均失败立即停止本 Gate。

真实命令为：

```bash
python -m plan_robust_memory.qualify_judge_repeatability
```

artifact contract 冻结为：

```text
judge_repeatability_case_manifest.json          immutable case source
judge_repeatability_transport_attempts.jsonl    raw direct/proxy attempts
judge_repeatability_attempts.jsonl              raw ModelCallAttemptRaw
judge_repeatability_output_bindings.jsonl       raw AcceptedOutputBindingRaw
judge_repeatability_outputs.jsonl               raw provider outputs
judge_repeatability.json                        derived observations/metrics/decision
judge_repeatability_run_state.json              current run identity/state/checksums
judge_repeatability_stall.json                  current blocked-run evidence
```

`AcceptedOutputBindingRaw` 是 accepted generated judge API output 的唯一
真值。Provider usage 与
`local_surrogate_serialized_input_tokens`/
`local_surrogate_output_content_tokens` 分离；缺少 provider cache subset 时保持
provider usage unknown，不以零或本地 surrogate 计数代替。Judge work 仍是 evaluation
overhead，不进入 memory lifecycle cost。运行中和运行结束后只能依据 `judge_repeatability_run_state.json` 中本次 `run_id` 及其 artifact checksum
判断状态；不得读取旧同名 aggregate 宣称本次通过或失败。run-scoped raw
文件在完成后才原子发布为 canonical artifacts。

qualification CLI 的 preparation lifecycle 在首次读取 manifest、JSON 或
upstream artifact 之前生成新的 `run_id`，并先写入
`judge_repeatability_run_state.json`（`state=preparing`）。任何缺文件、坏 JSON、
provenance/checksum 漂移或配额不足都必须写入同一 `run_id` 的
`judge_repeatability_stall.json`，将 run-state 终结为 `blocked`，并把旧
canonical 文件标为 `not_published_for_this_run`；这种失败不得留下
`running` 状态，也不得推进 `cache_qualification`。

三项指标分母固定为：

```text
unanimity_rate       = 三个 label 全相同的 case 数 / 50
pairwise_flip_rate   = 不同 label 的无序 replicate pair 数 / (50 * C(3,2))
parse_success_rate   = strict JSON parse 成功 observation 数 / 150
```

最低条件：

```text
unanimity_rate       >= 0.95
pairwise_flip_rate   <= 0.05
parse_success_rate   == 1.00
```

失败处理：

1. 单次 judge policy 不得冻结；
2. 改为预注册 3-vote majority 或其他显式 policy；
3. 使用同一 50-case set 之外的新 qualification subset 复验；
4. 仍失败则 LongMemEval task score 不能用于 confirmatory result。

Repeatability 只验证稳定性，不宣称 judge 对真实正确性的人工一致性；后者属于 `eval-protocol-v1.1`。

任何少于或多于 50×3、重复 case/replicate、类别缺失、非二元 label、模型
漂移、非 strict JSON 或跨 Day 1/evaluator-parity run evidence 都必须 fail
closed 并写入本次 stall/run-state。只有三项阈值全部通过，qualification
state 才从前两项的 ordered prefix 推进到 `cache_qualification`；无论通过
与否，full-leaf generation 仍为 false。

## 13.5 Judge Blindness

Judge 不得看到 plan 名称、方法名称、预期优劣、非必要成本或其他 items 的输出。

---

# 14. 工作包 T9：测试层级

## L0 Schema Tests

字段、ID、span、capacity、seed、replicate count、model snapshot、cache key、periodic interval。

## L1 Pure-function Tests

token accounting、hash、split、partition、plan serialization、metric aggregation、cost summation、power approximation、depth descriptor。

## L2 Property Tests

顺序、覆盖、plan 完整、online no-future-read、determinism、budget 不重建 leaf、primary budget-axis equality。

## L3 Golden Fixtures

保留原有 fixture，并新增：

1. budget 变化但 leaf hash 不变；
2. topology 间 replicate seed 不配对；
3. pseudo-plan 只抽单次 run 的错误 null；
4. judge silent fallback 或未记录 returned model；
5. judge cache key 冲突；
6. full-context-parity control；
7. nested FC context 不可当独立 cluster；
8. `B_query` 未随 primary budget sweep 变化；
9. `delta_SESOI` 与 `delta_decision` 被错误合并；
10. 低功效 null 被错误触发 NO-GO；
11. repeated observations 被错误当作独立 episodes；
12. depth 与 plan 完全共线却仍被声明可识别；
13. periodic reconstruction 启用但 interval 缺失；
14. 外网代理不可达但下载脚本无限重试；
15. 同一 Gate 重复失败却未生成 stall report；
16. PlanNodeRaw 含派生字段或 child span 无法重建；
17. NodeArtifact 使用绝对路径或新增 cache source 字段；
18. generated/cache/deterministic lineage 与 accepted binding 不一致；
19. provider/local-surrogate token、cached subset 或 reasoning subset 被混淆；
20. accepted-path/observed work、judge overhead 和 shared leaf work 对账失败；
21. support labels 泄漏到 construction/answer 或重复加权 supporting leaf；
22. formal executor/cache/retry/rate-limit/route 不一致或 stage wall-clock 边界
    不可重建；
23. full-leaf guard 在 Observability Freeze、SATURATION-01、protocol tag 或
    Q0/D_leaf 之前错误放行。
24. failed/cancelled attempt 使用伪造 `returned_model`/`request_id`
    占位符，或 accepted/successful/parse-failed attempt 的该字段为 null；
25. path/sequence 没有方向后缀、走向与后缀不一致，或 merge-event
    错把 `is_generative_merge` 记为 depth；
26. local surrogate token 被报告为 exact model tokens，或在无 tokenizer/
    provider 误差和 safety-margin 证据时放行 Q0。

## L4 Dataset Qualification

LongMemEval count/type/abs/session manifest；MemoryAgentBench 8-row audit；provisional/final split count。

## L5 Leakage

construction unit、base question、answer-session、template、evidence overlap。

## L6 Evaluator Qualification

official parity、Day 1 snapshot probe、50×3 repeatability、cache determinism、禁止 rolling fallback。

## L7 Statistical Regression

- corrected null 与真实 statistic 使用相同 R；
- `R_pilot=3`、`R_formal=5`；
- permutation 保持 block；
- common random numbers；
- `D_seed^95` 不参与 confirmatory AND gate；
- `delta_SESOI=0.05` 不可覆盖；
- `delta_decision` 必须来自冻结的 power artifact；
- underpowered null 只能 inconclusive；
- power simulation 使用独立 episode 数；
- depth 模型必须先通过 identifiability Gate。

## L8 Capacity/Budget Regression

- `B_merge = B_final = B_query = B`；
- budget sweep 实际改变 query budget；
- 同一 budget 跨 topology 相等；
- fixed overhead 不计入 memory payload B；
- secondary decoupled sweep 不得混入 primary。

## L9 Execution Discipline

- 代理配置端口为 17897；
- 代理失败有有限重试和明确错误；
- progress log 每工作会话生成；
- P14 触发时生成 stall report 并阻止进入下一 milestone。

## L10 Reproducibility

从空目录两次运行：

```text
normalize
audit-data
power-screen
split
build-manifest
partition-leaves
build-depth-descriptors
generate-plan-descriptors
compute-fixture-metrics
probe-project-judge
build-judge-qualification-cache
```

所有确定性 artifact checksum 相同。

## 14.1 Observability raw-to-derived tests

在第一次高成本 full-leaf 构建前，以下测试属于现有 T9/G-REPRO 的阻塞项：

- 删除 derived tables 后可从 raw artifacts 重建 PlanMetrics、merge metrics、
  accepted/observed work 和 support exposure；
- PlanNodeRaw child graph 合法，order role 与 critical path 可重建；
- generated materialization 恰好一个 accepted binding；cache 不伪造 API
  attempt；deterministic 不进入 generative rewrite lineage；
- `AcceptedOutputBindingRaw` 只绑定 accepted generated API output；cache 与
  deterministic 只通过 creation/materialization event 与 source artifact
  建立接受关系；
- failed 与 successful-nonmaterialized attempt 不进入 materialized lineage；
- 所有 attempt 都有 requested identity/route 和 nullable returned identity keys，
  outcome 条件、非空字符串与禁止伪造占位符的规则与 schema 一致；
- canonical path 可按后缀方向重建，MergeEventMetrics 仅有
  `is_generative_merge`，EvidenceExposure 的 `generative_rewrite_depth`
  等于 leaf-to-root generative path 长度；
- cached input 是 total input 的子集且不会重复计数；reasoning token 不被
  作为额外 output 计数；
- provider usage missing 保留为 unknown，不能被 local surrogate token 或零替代；
- local surrogate 字段与 provider/model token 字段分离，所有相关
  pressure/compression/utilization/balance 报告均明示其 proxy 口径；
- accepted-path 与 observed operational work 可对账，shared leaf 不跨 plan
  重复；judge overhead 不进入 lifecycle cost；
- support labels 无法进入 construction/answer view，support mapping 状态显式
  且 unique-leaf aggregation 可重建；
- formal topology runs 使用相同 executor/cache/retry/rate-limit/route，阶段
  wall-clock 边界一致。

## 14.2 Observability Freeze 与 full-leaf 入口顺序

Observability Freeze 不是 full experiment ready，也不是新增顶层 Gate。唯一
进入顺序冻结为：

```text
Observability Freeze
-> Evaluator Parity
-> Judge Repeatability
-> Cache Qualification
-> SATURATION-01
-> Final Judge/Budget Freeze
-> eval-protocol-v1.0
-> Q0/D_leaf micro-run
-> Full Leaves
```

现有 full-leaf guard 必须拒绝缺少上述任一前置状态、顺序错乱或 Q0/D_leaf
未通过的调用。`修改建议-8.3.md` 在合并后只作为 freeze decision record，
不具有执行权威。

# 15. 严格执行顺序

本节的唯一高成本进入顺序如下，milestone 编号和并行的只读数据审计不得
被解释为允许跳步：

```text
Observability Freeze
-> Evaluator Parity
-> Judge Repeatability
-> Cache Qualification
-> SATURATION-01
-> Final Judge/Budget Freeze
-> eval-protocol-v1.0
-> Q0/D_leaf micro-run
-> Full Leaves
```

Observability Freeze 只表示 raw/derived/schema/metric/tests 合同已经冻结，不
表示实验 ready。以上步骤继续由既有 G-PLAN、G-COST、G-EVAL、G-BUDGET 和
G-REPRO 验收，不新增顶层 Gate。

## M-1：Phase 0 最终修订与可行性 Gate

在 M0 前提交：

- implementation errata；
- data-role 与 replication-data 决策；
- k-axis contract；
- unified capacity contract；
- retriever contract；
- seed/repeat contract；
- primary/diagnostic/online plan-set contract；
- primary/replication backbone contract；
- corrected null spec；
- evaluator snapshot/cache spec；
- NO-GO sequential protocol；
- power-feasibility protocol；
- depth-identifiability protocol；
- network/stall execution protocol。

Day 1 必须完成：

1. LongMemEval 文件定位、SHA-256、question-type 与 atomic-evidence counts；
2. `N_master/N_4/N_8/N_16` 和 provisional grouped counts；
3. G-POWER-FEASIBILITY 解析筛查；
4. primary generation backbone 115K/4096-output probe；
5. judge endpoint probe；
6. 选择并 probe 一个不同家族 replication backbone；
7. 冻结 `BAAI/bge-m3` explicit revision；
8. 17897 代理探活；
9. 写死 `B_merge=B_final=B_query=B`；
10. 冻结 `K_planned={4,8,16}`、`k_primary=8`；
11. 冻结 `R_pilot=3`、`R_formal=5`；
12. 生成 primary、replication、SATURATION、D_leaf 和 future k-sweep 成本上界。

Day 1 cost 上界必须由 `src/plan_robust_memory/day1_cost.py` 从真实
LongMemEval manifest、power artifact、同一 run 的 model inventory/replication
probe 和 LabForge 公开 pricing/status 快照重算。调用方不得直接提供聚合
金额。成本合同冻结：

- `B_cost_envelope={128,192,256,384,512,768,1024,1536,2048,3072,4096}`；
  后续最终 budget 只能是该集合的子集；
- 每个逻辑调用最多计两个不同 route 尝试，logical calls 与 billable
  attempts 分开记录；
- workload rows 按 component、role/model、split、`k`、budget envelope、plan
  set 和 repeat 记录，并由代码聚合五个 component；
- 输入使用冻结的客户端停止上限与 provider exact usage guard，输出上限按
  role 协议记录；缺少 exact usage 或超出上限即重新打开 cost Gate；
- 上界包括 primary stress/online、SATURATION、Q0 `D_leaf`、future k-sweep
  及 matched-capacity 条件分支；未知费用不得记为零；
- LabForge 费率从 `https://labforge.cc/api/pricing` 与
  `https://labforge.cc/api/status` 推导，推理 base URL 仍固定为
  `https://api.labforge.cc/v1`，并记录响应 hash、pricing version、公式
  bundle hash 和模型比率。

唯一执行入口为：

```bash
python -m plan_robust_memory.probe_day1
```

必须完整产出八个文件：

```text
proxy_probe.json
model_inventory.json
primary_115k_probe.json
primary_output_probe.json
judge_probe.json
replication_model_probe.json
embedding_probe.json
cost_upper_bound.json
```

其中 `/models` 只用于 inventory；primary 115K、primary 4096-output、judge 与 replication 的生成探针必须使用 `https://api.labforge.cc/v1/chat/completions`、单一 `user` message 和 wire 字段 `max_tokens`。route 只允许两次：`direct`，失败后 `proxy_17897`；禁止同一路径无证据重试。任何旧的模型框架 v1.0/v1.1 别名、`/responses` 请求或客户端角色注入均不构成合格的 Day 1 证据。

Day 1 artifact 证据必须通过 `day1_run_state.json` 校验：`state=completed`、八个 artifact 均为同一 `run_id`、每个 artifact 的 `artifact_state=completed`。如果 probe 仍在运行，或同名 JSON 缺少本次 `run_id`，该目录只能判为 `unknown`，不得读取旧 artifact 后宣称本次 run 已 blocked 或 passed。运行中若需要诊断，只能报告当前阶段、进程状态和 pending/completed artifact，不得据旧文件停止进程。

具体模型调用方式、API/本地分工、代理、probe 和 fallback 规则以同目录的唯一 canonical 文件为准：

```text
Plan_Robust_Agent_Memory_Model_Framework_Usage.md
```

历史提法中的模型框架 `v1.0` 与 `v1.1` 是同一文件的废弃别名，不表示不同合同；当前及后续工作只允许使用上述无版本 canonical 文件名。`eval-protocol-v1.0/v1.1` 仍表示不同评估阶段，不得与模型框架名称混用。

Day 1 若样本量、模型窗口、不同家族 replication model、embedding revision 或网络条件不可行，立即报告用户，不继续堆代码。


## M0：测试骨架

创建 repo、CI、pytest、fixtures、progress/stall logs 和 make targets。先出现预期失败测试。

## M1：Schema 与术语

实现 T0，冻结 ID/hash/seed/repeat/cache/capacity/k/plan-set/backbone/retrieval
合同，以及 PlanNodeRaw、NodeArtifact、ModelCallAttemptRaw、
AcceptedOutputBindingRaw、MergeEventRaw 和 protected-label boundary。

## M2：LongMemEval 只读审计与 Adapter

这是第一个正式数据集。

完成：

- 实数文件各类型与 `_abs`；
- eligible KU/TR manifest；
- expanded non-abstention count；
- `N_master/N_4/N_8/N_16`；
- session/evidence schema；
- adapter qualification；
- raw SHA-256；
- 不生成大规模 LLM leaves。

## M3：Power Feasibility、Split 与 Leakage

完成：

- 解析功效表；
- estimator-matched simulation；
- 冻结 `delta_decision` 或选择数据扩展路径；
- family graph；
- final split；
- acceptance guard；
- evidence-layout strata 与 depth design-matrix 预审计；
- final split 不依赖 k，k masks 写入 manifest。

若 G-POWER-FEASIBILITY 不通过，不进入 M4。

## M3.5：Observability Freeze

在任何 evaluator qualification、SATURATION 或 leaf generation 前，以 TDD
完成 T0/T6/T7/T9 的 raw/derived contract、现有 schema 就地升级、metric
specification 与 full-leaf blocking tests。该 milestone 不读取 acceptance，
不产生模型调用，不新增 workload/method/primary metric/top-level Gate。

## M4：Evaluator Wrapper 与 Repeatability

严格按以下内部顺序完成：

1. Evaluator Parity：official compatibility 与 deterministic wrapper parity；
2. Judge Repeatability：snapshot pin 与 50×3 test；
3. Cache Qualification：judge cache key、blindness 和 deterministic replay。

Project judge 已在 Day 1 探活，本阶段不得临时换模型；official compatibility
audit 单独记录。前一项未通过不得进入后一项。

当前状态（2026-08-04）：Evaluator Parity 已由 run
`evaluator-parity-cdc9dc290e214da2bab361283dd163bd` 通过。两份官方源码
checksum、6 个 deterministic cases 与 5 个 LongMemEval prompt hashes 全部
一致；official dated GPT-4o snapshot 不在已通过的 Day 1 inventory 中，已按
规则记录外部限制且没有 fallback。Judge Repeatability 已由 run
`judge-repeatability-4c37b7794c664566a4d9dbfba4ef27f9` 尝试：首个 logical
call 的 direct 与 `proxy_17897` 均返回 HTTP 403，得到零个 accepted
observations。该结果只证明外部访问停滞，不构成 repeatability 通过或失败
估计；`next_stage=judge_repeatability`，Cache Qualification 未开始，
`full_leaf_generation_allowed=false`。

## M5：Secondary Data Structural Audits

并行完成：

- MemoryAgentBench 8-row source/context/nesting；
- LoCoMo 10-conversation structure、session、k-eligibility 和 evaluator audit；
- 至少一个额外独立来源候选的 desk audit；
- replication dataset decision log。

这些审计不阻塞 LongMemEval harness，但必须在 `eval-protocol-v1.0` report 中完成。

## M6：Parameterized Leaf、Capacity、Retriever、Depth 与 Prompts

完成：

- generic k partition；
- `K_planned={4,8,16}` masks；
- primary `k=8` partition；
- `C_leaf`；
- unified primary B contract；
- strong Retain retriever contract/index；
- leaf cache key with k/backbone；
- `d_mean/d_max/d_joint/n_supporting_leaves/evidence_spans_multiple_leaves`；
- primary/stress merge prompts；
- answer/render prompts；
- hard tests。

## M7：Plan Sets 与 Generators

完成 `Pi_primary/Pi_diag/Pi_online`、offline/online descriptors、depth/state descriptors、periodic interval schema 和 property tests。

## M8：Budget Structural Calibration 与 Cost

完成：

- candidate grid；
- raw-fit；
- rho-leaf；
- Retain retrieval/packing audit；
- lifecycle cost schema；
- online-balanced state accounting；
- Full Context/SATURATION 运行前的模型与吞吐 dry-run。

## M9：Calibration Saturation Qualification

真实运行：

- Full Context；
- Budget-Matched Retain；
- frozen judge/cache；
- saturation/parity classification。

该阶段必须独立预算，不能与纯代码开发合并计算工期。

## M10：Metrics、Formal Tests 与 Depth Identifiability

完成：

- episode-macro；
- Delta_primary 与 D_diag；
- diagnostic same-plan null；
- paired permutation；
- power estimator；
- GO/NO-GO/equivalence logic；
- G-DEPTH-IDENTIFIABILITY；
- descriptive depth/rewrite/pressure/order-role exposure aggregation；
- D_leaf protocol。

## M11：Protocol Qualification 与 Freeze

SATURATION-01 通过后先完成 Final Judge/Budget Freeze，再执行空目录复现、
全量 CI、qualification reports 和 checksums，最后发布：

```text
eval-protocol-v1.0
```

## Q0：Post-freeze Leaf Variance Qualification

在 protocol tag 后、pilot 前执行 `D_leaf` micro-run，生成：

```text
leaf_variance_qualification_v1.json
leaf_variance_cost_report_v1.json
```

Q0 未完成不得进入 feasibility pilot。

# 16. 现实工作日安排

该排期是资源规划，不覆盖 Gate。若出现 P14 停滞条件，立即暂停并报告用户。

## 第 1 日：Phase 0 生死检查与推理基座冻结

- LongMemEval 类型、`_abs`、atomic-evidence counts 和 `N_4/N_8/N_16`；
- provisional grouped count 与解析功效筛查；
- primary 115K/4096-output probe；
- judge probe；
- 不同家族 replication backbone 选择与 probe；
- BAAI/bge-m3 revision 冻结；
- 17897 代理探活；
- unified B、k-axis、plan-set、R 和阈值分离红测试；
- 全量 primary/replication/qualification 成本上界；
- implementation errata 与 canonical 模型框架文件。

## 第 2 日：测试骨架与 Schema

- repo、CI、progress/stall logs；
- schema 最小实现；
- stable ID/hash；
- 合法/非法 fixtures；
- T0 全绿。

## 第 3–4 日：LongMemEval Adapter

- session/evidence normalization；
- count/order/gold/provenance qualification；
- eligible/expanded manifests；
- raw checksums；
- no silent drop。

## 第 5–6 日：Power、Split 与 Leakage

- estimator-matched power simulation；
- 冻结 `delta_decision` 或数据扩展方案；
- grouped split；
- leakage graph；
- acceptance guard；
- evidence-layout strata 与 depth design-matrix 预审计；
- final split 不依赖 k，k masks 写入 manifest。

## 第 7 日：Evaluator

- official wrapper；
- dated snapshot config；
- 50×3 repeatability；
- judge cache。

## 第 8 日：Secondary Data 并行审计

- MemoryAgentBench 8-row；
- LoCoMo 10-conversation structure；
- 额外独立来源候选 desk audit；
- replication dataset decision。

该项可与第 5–7 日部分并行。

## 第 9 日：Parameterized Leaf、Retriever、Capacity 与 Prompt

- generic `j×tokens/k` partition；
- k masks 与 E16 common cohort；
- `C_leaf` 与 k/backbone-aware leaf cache；
- BGE-M3 index 与 strong Retain packing；
- unified B contract；
- primary/stress prompts；
- fixed-leaf tests；
- depth descriptors。

## 第 10 日：Plan Sets

- `Pi_primary/Pi_diag/Pi_online`；
- offline/online generators；
- periodic interval schema；
- property tests；
- depth/state profiles。

## 第 11 日：Budget Structural Calibration

- candidate grid；
- raw-fit/rho-leaf；
- cost schema；
- Full Context 运行 dry-run；
- 目标模型/3090 Ti 或 API 吞吐可行性检查。

## 第 12–13 日：SATURATION-01 真实运行

- calibration Full Context；
- Budget-Matched Retain；
- frozen judge/cache；
- parity/ceiling/signal-bearing classification；
- 成本报告。

## 第 14 日：统计与冻结

- metrics；
- diagnostic null；
- paired permutation；
- power/equivalence logic；
- depth identifiability；
- clean rebuild；
- qualification reports；
- CI/checksum；
- protocol tag。

若第 12–13 日长上下文吞吐或 judge 运行超出预期，第 14 日顺延，不压缩资格检查。

## Protocol Tag 后：Q0

- 20 个分层 calibration episodes；
- 5 个 leaf seeds；
- fixed balanced/merge/answer；
- D_leaf 与成本归档。

Q0 的实际时间由模型吞吐决定，不承诺包含在 14 个工作日内。

# 17. 阶段 Gates

## G-NETWORK

- 17897 代理已探活或明确记录不可用；
- 外网脚本有限重试，不无限循环；
- 数据/API 请求失败能区分代理、DNS、TLS、权限和资源不存在；
- project judge endpoint、requested/returned model 在 Day 1 真实探活；
- official dated snapshot 若计划使用，单独探活或记录不可用；
- 禁止无声回退到 rolling alias。

## G-DATA

- LongMemEval eligible count 与 `N_4/N_8/N_16` 来自实际文件；
- expanded non-abstention count 已归档；
- adapter qualification 通过；
- FC-SH 明确为 stress track；
- LoCoMo 被按 10 个 conversations 而非 query 数审计；
- 第二独立数据源候选和 claim-scope decision 已归档；
- raw file commit/checksum 固定。

## G-POWER-FEASIBILITY

- 解析筛查使用实际 grouped counts；
- estimator-matched simulation 可复现；
- `R_pilot=3`、`R_formal=5`；
- `delta_SESOI=0.05`；
- `delta_decision` 已在 topology 结果前冻结；
- acceptance `E_8` 对 `delta_decision` power `>=0.80`；
- power simulation 使用 evidence-layout strata，而不是 `fraction × n`；
- 若不满足，已扩展数据/调整 split/增加数据集或取消 hard NO-GO 权限。

## G-SPLIT

- construction unit/family 不跨 split；
- final split 与 power artifact 一致；
- acceptance 未被开发访问；
- leakage 无未处理高风险项。

## G-K-AXIS

- `K_planned={4,8,16}`、`k_primary=8`；
- split 不依赖 k；
- primary 使用 E8；k-sweep 使用共同 E16；
- partition 公式参数化；
- k-sweep claim 不越过容量混淆边界。

## G-LEAF

- `C_leaf` 在固定 backbone/k 内跨 budget 固定；
- leaf cache key 无 `budget_id`；
- 同一 backbone/k 下所有 topology/budget leaf SHA-256 一致；
- 不同 backbone/k cache 隔离；
- query/gold 不进入 constructor。

## G-CAPACITY

- primary 中 `B_merge = B_final = B_query = B`；
- budget sweep 实际改变 B_query；
- 同一 budget 跨 topology 固定；
- secondary decoupled sweep 与 primary 隔离；
- fixed overhead 单独记账。

## G-RANDOM

- `s_leaf=0`；
- merge/answer seeds 在 topology 间按 replicate 配对；
- judge noise 不混入 run seed；
- repeated runs 不计作独立 episodes；
- D_leaf protocol 已冻结。

## G-BUDGET

- raw-fit 与 rho-leaf 都已报告；
- SATURATION-01 已真实运行；
- 至少一个 signal-bearing budget，或明确标记 budget axis inconclusive；
- parity/ceiling 点未被误用于 NO-GO。

## G-STAT

- primary statistic 只使用 `Pi_primary`；
- right-deep 只进入 `Pi_diag`；
- real/null statistic averaging structure 一致；
- `D_seed^95` 仅为 diagnostic；
- paired permutation 可运行；
- `delta_SESOI` 与 `delta_decision` 分离；
- formal NO-GO 使用 power + CI/equivalence，而非“不显著”；
- power gate 可运行。

## G-DEPTH-IDENTIFIABILITY

- `d_mean/d_max/d_joint/n_supporting_leaves/cross-leaf flag` 可计算；
- 共线性和支持范围已审计；
- single/multiple-support-leaf strata 已报告；
- 未把 single-leaf 视为结构零效应；
- episode-clustered power simulation 已完成；
- 不可识别时自动降为 descriptive；
- 不把 54×3×3 写成 486 个独立样本。


## G-RETRIEVER

- BAAI/bge-m3 explicit revision 已冻结；
- retrieval units、ranking、all-candidate policy、packing 和 chronological render 已冻结；
- Retain 不使用 gold/answer-session labels；
- retrieval config/cache 可复现；
- embedding swap 不混入 primary topology contrast。

## G-BACKBONE-REPLICATION

- primary backbone 已按模型框架冻结；
- 不同家族 replication backbone 已选择、探活并预算；
- Run schema 记录 constructor/merge/answer snapshots；
- 不同 backbone 不复用 leaves；
- 未完成 replication 时，cross-family claim 被禁止。

## G-EVAL

- deterministic parity；
- project judge requested/returned model 与 provider route 已冻结；
- official compatibility audit 状态已记录；
- cache；
- 50×3 repeatability 通过；
- operation audit 不伪装为已完成。

## G-PLAN

- offline/online plan 合法；
- no future read；
- prefix queryable；
- periodic reconstruction interval 合同明确；
- prompt/operator config 冻结；
- logical child graph 合法，`PlanMetrics` 可完全从 `PlanNodeRaw` 重建；
- `order_role_path_vector_root_to_leaf` 与
  `order_role_sequence_root_to_leaf` 由 frozen evidence order 得到且走向与
  后缀一致；
- `generative_merge_path_leaf_to_root` 按 evidence leaf 到 root 重建；
- `critical_path_merge_count` 与递归 tree height 一致；
- MergeEventMetrics 只使用 `is_generative_merge`，EvidenceExposure 的
  `generative_rewrite_depth` 只由 leaf-to-root generative path 长度得到，
  cache hit 不改变该长度。

## G-COST

- construction/query 分开；
- provider/local-surrogate token 字段分离，`provider_usage_source` 与
  `usage_schema_version` 存在；
- local 字段只使用 `local_surrogate_content_tokens`、
  `local_surrogate_serialized_input_tokens` 和
  `local_surrogate_output_content_tokens`，相关 pressure、compression、
  utilization 与 balance 只作 local-surrogate proxy；
- Q0 前已冻结真实模型 tokenizer revision，或已有 provider/tokenizer
  误差界、充足 safety margin 和不超真实模型预算的测试证据；当前
  不预设该内部资格条件已通过；
- cached input 是 total input 的子集，reasoning 是 output 的子集，二者均不
  重复计数；
- accepted-path 与 observed operational work 可分离、可对账；
- shared leaf、plan-specific merge、answer 和 judge overhead 可分离；
- deployment state、shared source state 与 artifact footprint 不混淆，Primary
  Pareto 使用 `deployment_memory_tokens`；
- render cost、query latency 与四阶段 wall-clock 可记录；
- SATURATION 和 D_leaf 有独立预算；
- missing usage/cost 是 unknown，不记零；
- PricingManifest 缺失时 estimated USD 为 unavailable，不记零。

## G-PROGRESS

- 每工作会话有 progress log；
- P14 触发时有 stall report；
- 同一 Gate 两次实质修复失败后已通知用户；
- 未以重复调参代替根因分析。

## G-REPRO

- clean rebuild checksum 一致；
- prompts/models/seeds/cache/power artifact 可恢复；
- derived metrics 可从 raw artifacts 重建；
- `AcceptedOutputBindingRaw` 是 accepted generated API output 唯一真值；
  cache/deterministic 的接受关系仅由 creation/materialization event 与
  source artifact 重建，不伪造 binding；
- failed/nonmaterialized attempts 不进入 lineage，cache 不伪造 attempt；
- failed/cancelled attempt 的 nullable returned identity 与 successful attempt 的
  mandatory returned identity 可从 raw artifacts 按 outcome 重新验证，且无占位符；
- 路径方向、per-event `is_generative_merge` 与 EvidenceExposure depth
  可由 raw child/merge edges 重建，不保留无方向旧字段；
- support labels 未进入 construction/answer artifacts，support mapping 与
  unique-leaf aggregation 可重建；
- tokenizer、serialization、executor/cache/retry/rate-limit/route config 在
  formal topology comparison 中一致；
- stage wall-clock boundaries、cumulative attempt work、critical path 与
  parallelism factor 可重建；
- CI 与目标机器通过。

所有 Gate 通过才能冻结 protocol；Q0 通过后才能进入 pilot。

# 18. 本阶段禁止提交的代码

保留原禁止项：

- 最终方法；
- learned scheduler；
- verifier-guided merge policy；
- utility predictor；
- topology search；
- query-aware leaf/evidence selection；
- acceptance prompt tuning；
- 事后 budget 修改；
- 大规模主结果绘图。

允许的仅是 harness fixture、identity/deterministic/broken test doubles 和 qualification micro-runs。

---

# 19. 第一批必须编写的测试文件

```text
tests/unit/test_episode_schema.py
tests/unit/test_seed_contract.py
tests/unit/test_replicate_count_contract.py
tests/unit/test_capacity_contract.py
tests/unit/test_primary_budget_axis.py
tests/unit/test_stable_hash.py
tests/unit/test_token_accounting.py
tests/unit/test_periodic_rebuild_interval.py
tests/unit/test_k_axis_contract.py
tests/unit/test_plan_set_contract.py
tests/unit/test_backbone_bundle_schema.py
tests/unit/test_retrieval_config_schema.py
tests/unit/test_observability_contract.py
tests/unit/test_observability_schemas.py
tests/observability/test_contracts.py

tests/property/test_contiguous_partition.py
tests/property/test_partition_formula_uses_k.py
tests/property/test_k_sweep_uses_common_e16.py
tests/property/test_plan_inorder_preservation.py
tests/property/test_plan_span_coverage.py
tests/property/test_online_no_future_read.py
tests/property/test_budget_does_not_rebuild_leaf.py
tests/property/test_budget_sweep_changes_query_budget.py
tests/property/test_same_budget_matches_all_topologies.py

tests/integration/test_longmemeval_adapter.py
tests/integration/test_longmemeval_type_counts.py
tests/integration/test_memoryagentbench_cr_audit.py
tests/integration/test_locomo_construction_unit_count.py
tests/integration/test_replication_dataset_audit.py
tests/integration/test_replication_backbone_probe.py
tests/integration/test_retain_retrieval_pipeline.py
tests/integration/test_proxy_17897_probe.py

tests/day1/test_probe_day1_cli.py
tests/regression/test_model_framework_single_source.py
tests/regression/test_day1_report_consistency.py

tests/leakage/test_construction_unit_overlap.py
tests/leakage/test_base_question_overlap.py
tests/leakage/test_answer_session_overlap.py

tests/qualification/test_original_evaluator_parity.py
tests/qualification/test_project_judge_model_is_frozen.py
tests/qualification/test_project_judge_endpoint_probe.py
tests/qualification/test_judge_repeatability.py
tests/qualification/test_judge_cache_determinism.py

tests/statistics/test_null_matches_r_run_mean.py
tests/statistics/test_seed_null_is_diagnostic_only.py
tests/statistics/test_primary_pair_excludes_right_deep.py
tests/statistics/test_diag_range_includes_right_deep.py
tests/statistics/test_paired_permutation_blocks.py
tests/statistics/test_common_random_numbers.py
tests/statistics/test_delta_sesoi_is_frozen.py
tests/statistics/test_delta_decision_comes_from_power_artifact.py
tests/statistics/test_power_uses_independent_episode_count.py
tests/statistics/test_power_uses_empirical_evidence_layout_strata.py
tests/statistics/test_power_does_not_multiply_n_by_cross_leaf_fraction.py
tests/statistics/test_underpowered_null_is_inconclusive.py
tests/statistics/test_no_go_requires_equivalence_or_ci.py
tests/statistics/test_r_pilot_and_r_formal.py

tests/depth/test_answer_sessions_map_to_leaves.py
tests/depth/test_depth_descriptors.py
tests/depth/test_cross_leaf_evidence_descriptor.py
tests/depth/test_single_leaf_not_assumed_zero_effect.py
tests/depth/test_depth_identifiability_gate.py
tests/depth/test_repeated_rows_not_independent_episodes.py

tests/regression/test_leaf_bytes_shared_across_plans_and_budgets.py
tests/regression/test_ceiling_control_cannot_trigger_no_go.py
tests/regression/test_primary_null_requires_stress_prompt.py
tests/regression/test_cost_missing_not_zero.py
tests/regression/test_backbone_leaf_caches_are_isolated.py
tests/regression/test_retain_is_query_conditioned.py
tests/regression/test_retain_renders_chronologically.py
tests/regression/test_stall_report_blocks_next_milestone.py

tests/reproducibility/test_manifest_rebuild.py
tests/reproducibility/test_power_artifact_rebuild.py
```

最先运行：

```bash
pytest \
  tests/unit/test_episode_schema.py \
  tests/unit/test_seed_contract.py \
  tests/unit/test_primary_budget_axis.py \
  tests/unit/test_k_axis_contract.py \
  tests/unit/test_plan_set_contract.py \
  tests/unit/test_observability_contract.py \
  tests/unit/test_observability_schemas.py \
  tests/observability/test_contracts.py \
  tests/integration/test_no_leaves_before_gates.py \
  tests/statistics/test_power_uses_independent_episode_count.py \
  tests/statistics/test_null_matches_r_run_mean.py \
  -q
```

这些通过前，不进行真实 LLM construction。

# 20. Definition of Done

## 20.1 `eval-protocol-v1.0` Freeze DoD

- [ ] implementation errata 已冻结；
- [ ] 17897 代理探活结果已记录；
- [ ] project judge endpoint 与 requested/returned model 已在 Day 1 真实探活；
- [ ] schema/seed/repeat/capacity 合同通过；
- [ ] `B_merge = B_final = B_query = B` 已写入 primary contract；
- [ ] LongMemEval 实际类型、`_abs`、eligible 和 expanded counts 已归档；
- [ ] `N_master/N_4/N_8/N_16` 与 k masks 已归档；
- [ ] split 不依赖 k，E16 common k-sweep cohort 已冻结；
- [ ] LongMemEval adapter 通过 qualification；
- [ ] G-POWER-FEASIBILITY 解析与仿真通过；
- [ ] `delta_SESOI=0.05` 已冻结；
- [ ] `delta_decision` 已在 topology 结果前冻结；
- [ ] `R_pilot=3`、`R_formal=5` 已冻结；
- [ ] final grouped split 已与 power artifact 一致；
- [ ] acceptance guard 与 access log 生效；
- [ ] FC 8-row audit 完成，FC-SH 定位为 stress track；
- [ ] LoCoMo 以 10 个 conversation construction units 完成结构审计；
- [ ] 第二独立数据源候选和 claim-scope decision 已归档；
- [ ] `K_planned={4,8,16}`、`k_primary=8`；
- [ ] generic k partition 与 k-aware cache key 已实现；
- [ ] `C_leaf` 在固定 backbone/k 内固定且 cache key 无 `budget_id`；
- [ ] 所有 budget/topology 复用相同 leaf hashes；
- [ ] primary/stress merge prompts 在结果前冻结；
- [ ] primary/replication backbone manifest 与成本预算已冻结；
- [ ] replication backbone 属于不同模型家族并通过 Day 1 probe；
- [ ] BAAI/bge-m3 explicit revision 与 retriever contract 已冻结；
- [ ] Budget-Matched Retain query-conditioned packing regression 通过；
- [ ] periodic reconstruction interval contract 已冻结；
- [ ] offline/online plan property tests 通过；
- [ ] `d_mean/d_max/d_joint/n_supporting_leaves/cross-leaf` descriptors 已实现；
- [ ] G-DEPTH-IDENTIFIABILITY 已完成，或 depth 已明确降为 descriptive；
- [ ] raw-fit、rho-leaf 与 saturation classification 已生成；
- [ ] SATURATION-01 使用真实 Full Context/Retain 运行；
- [ ] 至少一个 signal-bearing budget，或明确标记 budget axis inconclusive；
- [ ] official evaluator parity 通过；
- [ ] project judge 使用冻结 model/provider config；
- [ ] official compatibility audit 已完成或明确记录不可用；
- [ ] 50×3 repeatability 通过；
- [ ] judge cache 可复现；
- [ ] `Delta_primary`、`D_diag` 与 corrected same-plan diagnostic null 有 unit tests；
- [ ] `D_seed^95` 已从 confirmatory AND gate 移除；
- [ ] primary paired permutation 只比较 left-deep vs balanced；
- [ ] right-deep 仅进入 diagnostic/depth analyses；
- [ ] paired permutation 有 block-preservation test；
- [ ] formal NO-GO 依赖 power + CI/equivalence；
- [ ] operation-level audit 明确标为 `eval-protocol-v1.1`；
- [ ] deployment-state/render cost 进入 online-balanced Gate；
- [ ] cost logger 无 silent zero；
- [ ] PlanNodeRaw/NodeArtifact/ModelCallAttemptRaw/AcceptedOutputBindingRaw/
  MergeEventRaw 的 raw schema 与 cross-object validators 全绿；
- [ ] PlanMetrics、MergeEventMetrics、accepted/observed work 和 support exposure
  可由 raw artifacts 完整重建；
- [ ] cache lineage 只来自 creation event，NodeArtifact 没有
  `cache_source_artifact_id`；
- [ ] provider/local-surrogate token、cached/reasoning subset、unknown 与
  optional USD 口径通过回归测试，surrogate 没有被报告为 exact
  model tokens；
- [ ] Q0 前 G-COST 内部的 tokenizer 二选一资格证据已通过；
- [ ] deployment/shared/artifact state、judge overhead 与 memory lifecycle cost
  边界通过回归测试；
- [ ] ConstructionInputView、AnswerInputView 和 ScoringInputView label access
  boundary 通过测试；
- [ ] formal executor/cache/retry/rate-limit/route 与 stage wall-clock contract
  通过测试；
- [ ] mechanism diagnostics 只报告 episode-clustered interval，不产生
  confirmatory p-value；
- [ ] Observability Freeze -> Evaluator Parity -> Judge Repeatability -> Cache
  Qualification -> SATURATION-01 -> Final Judge/Budget Freeze ->
  `eval-protocol-v1.0` -> Q0/D_leaf -> Full Leaves 的状态链完整且顺序正确；
- [ ] progress log 与 stall escalation 已实现；
- [ ] clean rebuild checksum 一致；
- [ ] prompts、models、configs、cache、power artifact 已归档；
- [ ] CI 全绿；
- [ ] 发布 `eval-protocol-v1.0`；
- [ ] acceptance 内容未被读取；
- [ ] 最终方法尚未实现。

## 20.2 Pilot-entry Qualification DoD

在 protocol tag 后还必须满足：

- [ ] D_leaf micro-run 使用预注册 calibration subset；
- [ ] 5 个 leaf seeds、fixed balanced/merge/answer；
- [ ] `leaf_variance_qualification_v1.json` 已归档；
- [ ] D_leaf 成本报告已归档；
- [ ] qualification 期间未修改 frozen protocol；
- [ ] Q0 通过。

只有 20.1 和 20.2 均完成，才能进入 feasibility pilot。

# 21. 完成后唯一下一步：Feasibility Pilot

## 21.1 Primary Pilot

使用全部 calibration `E_8` episodes：

- `k_primary=8`；
- primary backbone；
- fixed leaves；
- primary merge prompt；
- `Pi_primary={left_deep, canonical_balanced}`；
- `right_deep` 作为 `Pi_diag` 独立运行和报告；
- 至少一个 tight signal-bearing budget；
- 一个 transition/loose control；
- `R_pilot=3`；
- common random numbers；
- paired permutation for `Delta_primary`；
- diagnostic three-plan range 和 seed null；
- observed effect 与 `delta_decision`；
- power report；
- depth/evidence-layout descriptors。

Pilot 不具有 hard NO-GO 权限。它判断是否值得进入 formal baseline expansion，以及协议是否工作。


## 21.2 Primary GO

Primary prompt 下至少一个 signal-bearing budget 同时满足：

1. left-deep vs canonical-balanced paired permutation 通过；
2. `abs(Delta_primary) >= delta_decision`；
3. clustered CI 已报告；
4. judge qualification 通过；
5. protocol 无违规。

`D_seed_pair^95` 不再是必要条件。

若 observed effect 位于：

```text
[delta_SESOI, delta_decision)
```

结论是“存在科学上可能有意义、但当前设计不足以作硬决策的信号”，不得直接 GO 或 NO-GO；应考虑增加主推断数据或正式阶段样本。

## 21.3 Sequential NO-GO Check

若 primary prompt 未满足 GO：

1. 确认至少一个 signal-bearing budget；
2. 确认 formal design power `>=0.80`；
3. 确认 judge repeatability；
4. 检查 CI/equivalence 是否有能力排除 `delta_decision`；
5. 在 tight signal-bearing budget 运行预注册 stress prompt；
6. 使用相同 paired permutation 和 formal decision rule。

只有 primary 与 stress prompt 均未达到 `delta_decision`，且 CI/equivalence 可排除该效应，才允许触发 topology-effect 停止条件。

如果 stress prompt 有 effect：

```text
结论 = operator-contingent feasibility
```

此时不能宣称通用 topology effect，也不能直接设计复杂方法；先判断该 prompt 的任务质量和工程合理性。

`D_seed^95` 只随结果报告，不决定停止。

## 21.4 Rewrite-depth Mechanism

- H1 `Delta_primary` paired contrast 是 primary；
- depth/rewrite/pressure/order-role 指标只做 episode-clustered descriptive
  diagnostics，不产生 confirmatory p-value；
- H1 通过且 exposure pattern 一致：只能报告 mechanism-consistent pattern，
  不能声称确认性因果机制；
- H1 通过但 exposure pattern 不一致：说明 plan effect 存在，但当前机制
  descriptor 不足；
- H1 不通过但 exposure pattern 存在：仅 exploratory/operator-contingent
  association；
- 不得用 mechanism diagnostic 替代低功效的 H1；
- 不得把重复观测行数称为独立样本数。


## 21.5 Planned k-sweep

只有 primary feasibility 获得信号后才执行：

```text
k = {4,8,16}
episodes = E_16
backbone = primary
```

报告：

- `Delta_primary(k,B)`；
- `D_diag(k,B)`；
- depth/evidence-layout descriptors；
- leaf/merge/state/cost amplification。

单调增长只视为与 rewrite-depth 机制一致。若要做因果表述，增加 matched-total-leaf-capacity sensitivity。

## 21.6 Backbone Replication

在 primary GO 后、paper-level claim 前执行预注册 replication backbone：

- k=8；
- `Pi_primary`；
- 至少一个 tight signal-bearing budget；
- 使用独立 replication leaves；
- judge/retriever 规则保持冻结；
- 报告 effect direction、rank stability、effect size 和成本。

若 replication 不成立，结论限定为 primary-backbone-specific。

## 21.7 Dataset Replication

LoCoMo 可以执行为 cross-source stress replication，但 cluster 数按 10 conversations 处理。它不能单独升级为高功效 confirmatory dataset。

跨数据集一般性结论必须等待第二个具备足够独立 construction units 的数据集完成。

## 21.8 Online Balanced Gate

即使 topology effect 成立，若 online canonical balanced 在质量、鲁棒性、
deployment state、render cost 和 latency 的 Pareto 上已关闭空间，则停止复杂
方法路线或转为 analysis/benchmark。

## 21.9 执行停滞处理

Pilot 或任何前置 qualification 若触发 P14：

- 立即停止当前重复尝试；
- 生成 stall report；
- 向用户报告；
- 明确建议继续、缩小、换数据/模型或停止；
- 在用户了解阻塞前不得静默进入下一个实验分支。

# 22. 最终执行判断

现在允许立即开始：

- M-1；
- M0；
- M1；
- LongMemEval 数据下载、checksum 与只读审计；
- FC 结构审计；
- 17897 代理探活；
- project judge 与 replication backbone 探活；
- 功效解析筛查。

在以下内容通过前，不得进入真实 LLM construction：

- unified primary budget-axis contract；
- seed/repeat contract；
- power artifact 的输入只使用独立 episodes；
- fixed-leaf cross-budget contract。

在以下内容通过前，不得冻结 `eval-protocol-v1.0`：

- G-POWER-FEASIBILITY；
- `delta_decision`；
- grouped split 与 k masks；
- strong Retain retriever contract；
- primary/diagnostic plan-set separation；
- primary/replication backbone manifest；
- corrected diagnostic null；
- paired permutation；
- project judge config/cache/repeatability；
- budget saturation classification；
- G-DEPTH-IDENTIFIABILITY 或明确降级；
- NO-GO sequential/equivalence gate；
- progress/stall escalation contract。

在以下内容通过前，不得进入 feasibility pilot：

- `eval-protocol-v1.0` tag；
- Q0 D_leaf qualification；
- qualification cost artifact；
- 无未报告的 P14 停滞事件。

执行外网访问时可使用端口 `17897`。如果执行过程中长期停留在同一阶段、重复失败而没有新证据，必须立即反思并告诉用户，不得继续静默原地踏步。
