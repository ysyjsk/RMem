# Plan-Robust Agent Memory：模型调用框架使用说明

> **统一版本说明**：历史讨论中的“模型框架 v1.0”和“模型框架 v1.1”指同一份执行合同，不是两个版本。为避免与 `eval-protocol-v1.0/v1.1` 的阶段含义混淆，仓库内只允许引用本无版本文件；任何带版本号的模型框架名称均为废弃别名，不得再用于配置、报告或讨论。

## 0. 文档定位

本文档是 `Plan_Robust_Agent_Memory_Phase1_TDD_Workplan` 的配套执行说明。

API key 只通过运行环境注入，不得写入配置、日志或 artifact：

```bash
export OPENAI_API_KEY="..."
```

本项目的 OpenAI-compatible API 合同冻结如下：

```text
base_url: https://api.labforge.cc/v1
model_inventory_endpoint: /models
generation_endpoint: /chat/completions
generation_url: https://api.labforge.cc/v1/chat/completions
request_protocol: OpenAI-compatible Chat Completions
response_field: choices[0].message.content
usage_input_field: prompt_tokens
usage_output_field: completion_tokens
```

所有生成请求必须包含 exactly one `user` message；客户端不得注入 `system` 或 `developer` message，也不得拼接任何隐藏 prompt。`/responses` 不属于本项目 Day 1 或正式实验的生成协议。这里的“纯净回复”指客户端请求体无额外角色或隐藏指令；provider 侧不可见策略不在客户端可验证范围内，不能被宣称为不存在。

连接顺序固定为 direct → `http://127.0.0.1:17897`。两次实质不同的尝试均失败时，必须生成 stall report 并立即报告，不得无限重试。

它只负责冻结以下内容：

1. 哪些步骤需要生成式模型；
2. 每个步骤具体使用哪个模型；
3. 模型运行在 API 还是本地；
4. 模型输入、输出、随机性和缓存如何管理；
5. 什么情况下允许切换模型；
6. 什么情况下禁止继续实验；
7. 每个工作阶段具体会调用哪些模型。

本文档不重新定义数据集、统计检验、split、topology 或评价指标。相关科学合同仍以 workplan 和 `eval-protocol-v1.0` 为准。

---

1. 总体架构

正式实验采用以下固定分工：

远程 API
├── Primary Backbone：gpt-5.6-sol
│   ├── Leaf Constructor
│   ├── Internal Merge
│   ├── Full Context Answer
│   ├── Budget-Matched Retain Answer
│   ├── Topology Memory Answer
│   └── D_leaf Qualification
│
├── Replication Backbone：DAY1_FREEZE_DIFFERENT_FAMILY
│   ├── Replication Leaf Constructor
│   ├── Replication Internal Merge
│   └── Replication Answer
│
└── gpt-5.5
    ├── LongMemEval-Compatible Judge
    ├── Judge Repeatability Test
    └── Judge Cache Generation

本地 3090 Ti
├── BAAI/bge-m3 Embedding
├── Retrieval Baseline
├── Token/Length Analysis
├── Dataset Adaptation
├── Leaf Partition
├── Plan Generation
├── Cache / Manifest / Hash
├── Statistical Test
└── Visualization

核心原则：

除 embedding 和纯工程计算外，正式生成式工作全部走 API。

Primary 结论固定使用 gpt-5.6-sol。另一个不同模型家族的 replication backbone 必须在 Day 1 根据实际 API inventory、窗口、快照和吞吐冻结；不得用同族小型号冒充跨家族复制。

本地 3090 Ti 不承担：

115K Full Context；

正式 leaf construction；

正式 internal merge；

正式 answer generation；

正式 LLM judge。

2. 模型角色总表

角色

固定模型

运行位置

是否进入正式结果

是否允许自动降级

Leaf Constructor

gpt-5.6-sol

API

是

否

Internal Merge

gpt-5.6-sol

API

是

否

Replication Constructor/Merge/Answer

Day 1 冻结的不同模型家族 explicit snapshot

API

replication

否

Full Context Answer

gpt-5.6-sol

API

是

否

Budget-Matched Retain Answer

gpt-5.6-sol

API

是

否

Topology Memory Answer

gpt-5.6-sol

API

是

否

Primary Judge

gpt-5.5

API

是

否

Official Compatibility Judge

官方 LongMemEval 指定模型快照

官方 API

只作兼容审计

否

Embedding

BAAI/bge-m3

本地 3090 Ti

是

否

API Smoke Test

gpt-5.4-mini

API

否

可

低成本工程调试

gpt-5.6-luna

API

否

可

可选成本消融

gpt-5.6-terra

API

仅单独消融

否

代码 Review

codex-auto-review

API

否

不适用

任何正式 artifact 中都必须记录：

backbone_id
model_family
k
requested_model
returned_model
provider
base_url
request_id
prompt_hash
config_hash
input_tokens
output_tokens
latency
response_hash
endpoint
request_protocol
message_contract
route
failed_attempts
created_at

3. 正式生成模型：gpt-5.6-sol

3.1 使用范围

gpt-5.6-sol 用于所有会影响最终科学结论的生成任务：

leaf construction；

internal merge；

Full Context 回答；

Budget-Matched Retain 回答；

topology memory 回答；

online balanced baseline；

periodic reconstruction baseline；

D_leaf qualification；

prompt stress branch；

acceptance 正式回答。

不得在不同 topology 之间替换模型。Primary plan set 只比较 left-deep 与 canonical balanced；right-deep 只作 diagnostic。

3.2 为什么统一使用同一模型

统一使用 gpt-5.6-sol 可以保证 primary experiment 中只改变 topology，不引入以下混淆：

constructor 模型能力变化；

merge 模型能力变化；

answer 模型能力变化；

provider 路由差异；-模型间不同压缩习惯；

模型间不同时间推理能力。

正式实验中的 operator 应写作：

mu_(gpt-5.6-sol, prompt_id, B)

而不是模糊写成“LLM merge”。

3.3 固定调用参数

推荐冻结为：

model: gpt-5.6-sol
base_url: https://api.labforge.cc/v1
endpoint: /chat/completions
messages: exactly one user message
system_or_developer_message: forbidden
request_output_limit_field: max_tokens
temperature: 0
top_p: 1
max_route_attempts: 2
timeout_seconds: 300
stream: false

若 API 不接受 temperature、top_p 或显式 seed：

删除不支持参数；

不伪造 determinism；

记录 provider 实际接受的参数；

repeated run 定义为“相同配置下独立调用”；

不宣称是可控随机种子实验。

正式实验禁止自动切换到其他模型。

4. Replication Backbone

4.1 Day 1 必须冻结

不得在文档中臆造当前 provider 不一定提供的模型。Day 1 从实际 /models inventory 中选择一个满足以下条件的 explicit snapshot：

与 gpt-5.6-sol 不属于同一基础模型家族；

支持至少 primary leaf 输入和 merge/answer 输出；

可以固定 model ID/provider version；

通过 constructor、merge、answer smoke probe；

禁止自动 fallback；

成本可进入预注册 replication budget。

生成：

configs/models/replication.yaml
artifacts/qualification/replication_backbone_probe.json
artifacts/reports/replication_backbone_cost_budget.json

4.2 Replication 边界

Primary pilot 和 primary GO/NO-GO 仍只使用 gpt-5.6-sol；

replication backbone 只在 primary GO 后运行；

replication 必须重新生成 leaves；

不得跨模型复用 primary leaf cache；

judge 和 retrieval contract保持固定；

若没有合格的不同家族模型，必须报告 single-backbone limitation。

4.3 Power

Replication 使用与 primary 相同的独立 episode 数。Day 1 只能做设计功效评估，不能假设其真实 effect/noise 与 primary 相同。正式 replication 前用 development micro-run 更新 variance/discordance 假设，但不得读取 acceptance。

5. Leaf Constructor

5.1 固定模型

role: leaf_constructor
model: gpt-5.6-sol
location: API

5.2 k 与容量

K_planned: [4, 8, 16]
k_primary: 8
C_leaf_primary: 512
s_leaf: 0

规则：

primary 只生成 k=8 leaves；

future k-sweep 在 E_16 上分别生成 k=4/8/16 的独立 leaf caches；

leaf cache key 必须包含 k 和 partition hash；

不同 k 不复用 leaf；

固定 C_leaf 的 k-sweep是系统级缩放，不直接宣称纯 depth 因果。

对任意 k 使用：

boundary_j ≈ j × total_tokens / k

primary k=8 时，每个 leaf 输入平均约 14.4K tokens。实际分布必须由数据审计产物给出。

5.3 Leaf Constructor 输入

仅允许输入：

当前 leaf 覆盖的原始 sessions；

session 时间；

evidence IDs；

leaf 输出 schema；

C_leaf 限制；

leaf prompt。

禁止输入：

question；

gold answer；

answer_session_ids；

supporting evidence 标注；

topology；

budget；-其他 leaf 的输出。

5.4 Leaf Constructor 输出

输出必须包含：

{
  "memory": "...",
  "source_evidence_ids": ["..."],
  "time_range": {
    "start": "...",
    "end": "..."
  }
}

要求：

memory 不超过 C_leaf；

provenance 可回溯；

不允许静默截断；

不允许因“结果不好”而重复生成直到满意。

5.5 Leaf Cache

Leaf cache key：

sha256(
  dataset_commit
  + episode_id
  + k
  + partition_hash
  + evidence_span
  + C_leaf
  + leaf_prompt_hash
  + model
  + decoding_config
  + s_leaf
)

不得包含：

budget_id
topology_id
query_id
answer_id

同一个 leaf 生成一次，跨所有 budget 和 topology 复用。

5.6 禁止替代模型

正式 leaf 禁止使用：

gpt-5.4-mini；

gpt-5.6-luna；

gpt-5.6-terra；

本地开源模型；

judge 模型。

原因：leaf 是所有后续实验的共享基础，低质量 leaf 会系统性污染所有条件。

6. Internal Merge

6.1 固定模型

role: merge
model: gpt-5.6-sol
location: API

6.2 Primary Operator

prompt: merge_prompt_v1_primary
model: gpt-5.6-sol

Primary prompt 目标：

保留事实；

保留时间顺序；

正确处理旧值与新值；

合并重复事实；

不引入无来源事实；

输出不超过 B；

保留 provenance。

6.3 Stress Operator

prompt: merge_prompt_v2_stress
model: gpt-5.6-sol

Stress prompt：

与 primary 使用相同模型；

使用相同容量；

使用相同输出 schema；

更强调抽象、去重和跨 evidence 综合；

仍必须保持事实与时间正确；

不得故意设计为容易失败的 prompt。

Stress prompt 只在 primary prompt 全部为 null 的 NO-GO 分支中运行。

6.4 Budget

Primary budget sweep：

B_grid:
  - 512
  - 1024
  - 2048
  - 4096

在每个预算点：

B_merge = B_final = B_query = B

其中：

B_merge：每个 internal merge 的最大输出；

B_final：root memory 最大输出；

B_query：最终送给 answer model 的 memory payload 上限。

6.5 Merge 输入

每次 merge 只允许输入：

左子节点；

右子节点；

它们的 provenance；

它们的时间范围；

当前 budget；

merge prompt。

禁止输入：

query；

gold；

answer evidence；

plan 名称；

“哪个 topology 应该更好”的提示。

6.6 Merge Repeated Runs

R_pilot: 3
R_formal: 5

Repeated run 只改变独立调用编号；同一 (backbone,k,budget) 内跨 topology 配对：

replicate_id = 0, 1, 2, ...

同一 replicate ID 在所有 topology 之间配对。

如果 provider 支持 seed：

s_merge = replicate_id

如果 provider 不支持 seed：

使用相同调用配置；

每个 topology 独立调用；

记录 request ID；

不宣称严格随机种子可控。

7. Answer Model

7.1 固定模型

role: answer
model: gpt-5.6-sol
location: API

同一 backbone 内所有正式回答条件必须使用同一个 answer model。Primary headline 只比较 left-deep 与 canonical balanced；right-deep 只作 diagnostic。

正式回答条件包括：

Full Context；

Budget-Matched Retain；

left-deep；

balanced；

right-deep；

online balanced；

periodic reconstruction；

后续正式方法。

7.2 Full Context

输入：

完整约 115K history
+ 当前 question
+ 固定 answer prompt

默认：

max_tokens: 512
temperature: 0

用途：

SATURATION-01；

Context Saturation Gap；

任务上界诊断；

calibration Full Context baseline。

Full Context 不走本地 3090 Ti。

7.3 Budget-Matched Retain

输入：

在 B_query 内保留的 raw evidence
+ question
+ answer prompt

必须使用与 topology answer 相同的：

gpt-5.6-sol；

answer prompt；

max output；

decoding；

question formatting。

7.4 Topology Memory Answer

输入：

最终 memory view
+ question
+ answer prompt

禁止附加：

topology 名称；

merge depth；-构造过程说明；

hidden provenance；-其他 topology 输出。

7.5 Answer Cache

Cache key：

sha256(
  question_id
  + context_or_memory_hash
  + answer_prompt_hash
  + model
  + decoding_config
  + replicate_id
)

Acceptance 阶段禁止 cache miss 后静默重算。

8. Judge

8.1 项目内主 Judge

role: judge
model: gpt-5.5
location: API

选择独立于生成模型的 gpt-5.5，避免使用 gpt-5.6-sol 自评。

Judge 使用范围：

LongMemEval-compatible task correctness；

Full Context 判分；

Retain 判分；

topology answer 判分；

judge repeatability；

acceptance 正式判分。

8.2 Judge 输入

只允许输入：

question；

reference answer；

candidate answer；

官方兼容 judge rubric；

strict output schema。

禁止输入：

topology；-方法名；

budget；-模型名；-成本；

expected result；-其他候选答案。

8.3 Judge 输出

推荐：

{
  "label": 0,
  "reason": "..."
}

正式 task score 只使用 label。

reason 仅用于错误检查，不作为自动二次判分输入。

8.4 Judge 参数

model: gpt-5.5
temperature: 0
max_tokens: 128
response_format: not sent; local strict JSON parser is authoritative

如果 provider 不支持严格 JSON schema：

使用文本输出；

本地 parser 严格验证；

parsing failure 不自动记为 0；

parsing failure 必须进入 retry/qualification 日志。

8.5 Judge Repeatability

在正式使用前运行：

50 cases × 3 independent judgments

要求：

unanimity_rate >= 0.95
pairwise_flip_rate <= 0.05
parse_success_rate = 1.00

不通过时：

不得继续正式 LongMemEval 判分；

改为预注册 3-vote majority；

使用新 qualification subset 复验；

仍失败则该 judge 不具备 confirmatory 资格。

8.6 Judge Cache

Cache key：

sha256(
  question_id
  + reference_answer_hash
  + candidate_answer_hash
  + judge_prompt_hash
  + judge_model
  + decoding_config
  + output_schema_version
)

相同 candidate answer 只能 judge 一次。正式统计只读冻结 cache。

8.7 官方 LongMemEval 兼容性

当前模型框架以项目可用 API 为准，因此：

gpt-5.5 定位为项目内 LongMemEval-compatible judge；

不能直接宣称完全复现官方 LongMemEval 分数；

最终论文如需与官方数字直接横向比较，应另行使用官方 OpenAI GPT-4o 日期快照，对固定子集做 agreement audit；

官方兼容审计不能改变项目内主 judge 已冻结的结果。

9. Embedding 与 Budget-Matched Retain

9.1 固定 Embedding

role: embedding
model: BAAI/bge-m3
revision: DAY1_FREEZE_EXPLICIT_REVISION
tokenizer_revision: DAY1_FREEZE_EXPLICIT_REVISION
location: local_3090ti
precision: fp16
similarity: cosine
normalize_embeddings: true

Day 1 必须把实际 revision 写入 config 和 index manifest，禁止只保留 rolling repository name。

9.2 Retrieval Unit

默认一个 timestamped session 为一个 unit。超长 session 使用 workplan 冻结的 deterministic turn-boundary chunking。

9.3 Strong Retain Ranking

Budget-Matched Retain 是 query-conditioned baseline：

query 只来自当前 question；

禁止使用 gold、answer_session_ids、support labels；

默认对全部 units 排序：

candidate_top_k = all

若设置 cap，必须证明在 design pool 上不绑定。

Tie-break：

score desc
→ sequence_index asc
→ evidence_id

9.4 Token-budget Packing

按 ranking greedy pack：

计入 timestamp、speaker、separator；

unit 不完整则不放入；

超预算时跳过并继续；

选择后按原始时间顺序渲染；

exact payload 不超过 B_query。

9.5 Retrieval Cache

Cache/index manifest 必须包含：

embedding revision
tokenizer revision
raw evidence manifest hash
retrieval unit version
question ID
B_query
ranking/packing config
index version

Embedding 变化属于单独 sensitivity，不得混入 primary topology comparison。

10. 各 Workplan 阶段的模型调用清单

M-1：Phase 0

需要模型：

gpt-5.6-sol：115K Full Context、4096 output、constructor/merge probe
gpt-5.5：judge endpoint probe
replication backbone：constructor/merge/answer probe
BAAI/bge-m3：revision、显存、吞吐和 embedding probe

本阶段不产生正式科学结果，只验证：

上下文窗口；-输出上限；-吞吐；-usage；

provider route；-模型名；-成本。

M0：测试骨架

不需要正式模型。

允许：

gpt-5.4-mini

只用于 API client smoke test。输出不能进入数据或科学 artifact。

M1：Schema 与术语

不需要模型。

M2：LongMemEval Adapter

不需要生成式模型。

只使用：

本地 Python；

tokenizer；

checksum；

schema validation。

M3：Split 与 Leakage

不需要生成式模型。

Embedding near-duplicate 警报可以使用：

BAAI/bge-m3

但 embedding 相似度不能自动决定删除。

M4：Evaluator Wrapper

需要：

gpt-5.5

用于：

judge probe；

50×3 repeatability；

judge cache；

parser qualification。

M5：Secondary Dataset Audits

MemoryAgentBench、LoCoMo 和其他候选的结构审计不需要生成式模型。

M6：Fixed Leaf 与 Prompt

需要：

gpt-5.6-sol

用途：

development prompt micro-test；

primary k=8 leaf generation；

prompt output schema test。

同时使用本地 BAAI/bge-m3 建立 strong Retain index；future k-sweep 和 replication leaves 不在 primary Phase 1 中提前全量生成。

正式 leaf 只能在所有合同和测试通过后生成。

M7：Plan Generator

不需要模型。

M8：Budget 与 SATURATION-01

需要：

gpt-5.6-sol
    Full Context Answer
    Budget-Matched Retain Answer

gpt-5.5
    Judge

本阶段是首次真实大上下文质量调用。

M9：统计协议

不需要生成式模型。

M10：Protocol Freeze

不允许新增模型调用。

只允许读取：

frozen model configs；

probe results；

judge qualification；

cache manifests；

checksums。

Q0：D_leaf Qualification

需要：

gpt-5.6-sol

固定：

balanced topology；

merge replicate；

answer replicate。

只改变：

s_leaf ∈ {0,1,2,3,4}

Judge：

gpt-5.5

Q0 完成后才能进入 pilot。

Feasibility Pilot

需要：

Leaf:
    gpt-5.6-sol
    直接读取已冻结 leaf cache

Merge:
    gpt-5.6-sol

Answer:
    gpt-5.6-sol

Judge:
    gpt-5.5

Embedding / Retrieval:
    BAAI/bge-m3

11. Day 1 推理基座探针

唯一执行入口：

```bash
python -m plan_robust_memory.probe_day1
```

该命令必须产出以下八个文件；缺任何一个都属于 blocked，而不是 partial pass：

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

生成 wire payload 使用 `max_tokens`；`max_output_tokens` 只可作为内部预算命名，禁止出现在 Chat Completions 请求体。每个生成 artifact 记录 exact endpoint、request_protocol、message_contract、实际 route、failed attempts、usage、request ID 与 response hash。

11.1 必须探测的模型

gpt-5.6-sol
gpt-5.5
DAY1_FREEZE_DIFFERENT_FAMILY replication backbone
BAAI/bge-m3 explicit revision

可选 smoke model：

gpt-5.4-mini

11.2 gpt-5.6-sol Probe

选择 5 个 development episode，加 1 个 warm-up。

测试：

input_tokens: approximately 115000
max_tokens: 512
concurrency:
  - 1
  - 2
  - 4

额外执行：

input_tokens: small
max_tokens: 4096

记录：

success；

prompt tokens；

completion tokens；

TTFT；

total latency；

request ID；

returned model；

retry；

HTTP status；

cost；

actual route (direct or proxy_17897)。

11.3 gpt-5.5 Judge Probe

执行至少 5 个固定 QA pair：

2 个正确；

2 个错误；

1 个部分正确。

检查：

-接口可达；

JSON 可解析；-模型名返回；

usage 完整；-无 rolling fallback。

11.4 Replication Backbone Probe

至少执行：

一个 representative leaf input；

一个 two-node merge；

一个 budgeted answer；

一个输出容量 probe。

记录 model family、explicit model ID、provider、窗口、输出上限、延迟、usage 和成本。不同家族模型不可用时立即报告，不得用同族小号替代。

11.5 Embedding / Retrieval Probe

记录：

BAAI/bge-m3 commit/tag；

tokenizer revision；

3090 Ti 显存；

单 episode embedding latency；

500-instance 全量索引估算；

query ranking 和 greedy packing determinism。

11.6 通过条件

115K request success = 5/5
context length error = 0
silent truncation = 0
usage available = true
P95 latency <= 180 s
concurrency 4 error rate <= 5%
4096 output probe success = true
judge parser success = 100%
replication backbone explicit snapshot selected = true
embedding revision pinned = true
retrieval packing deterministic = true

未通过时，不得冻结：

C_leaf；

budget grid；

answer model；

SATURATION-01；-正式成本估计。

12. 模型降级规则

12.1 正式模型禁止自动降级

以下模型失败时不得静默切换：

gpt-5.6-sol
gpt-5.5
BAAI/bge-m3

12.2 Answer / Constructor / Merge 的人工降级顺序

仅在 Day 1 probe 或明确基础设施失败时讨论：

gpt-5.6-sol
→ gpt-5.5
→ gpt-5.4

每次切换必须：

生成 decision log；

说明原模型失败原因；

重跑 115K probe；

重跑 prompt micro-test；

更新全部 model config；

protocol version 发生变化。

不得切到 mini/luna 作为正式模型。

12.3 Judge 的人工替换

若 gpt-5.5 不稳定：

gpt-5.5
→ 重新资格验证的独立强模型

不能直接换为 answer model 后继续使用旧 qualification。

12.4 Embedding 替换

更换 embedding 会改变 retrieval baseline，因此必须：

更新 index；-重跑 retrieval；-升级 protocol；-禁止复用旧 retrieval cache。

13. API 与代理配置

13.1 环境变量

export OPENAI_API_KEY="..."
export OPENAI_BASE_URL="https://api.labforge.cc/v1"

`OPENAI_BASE_URL` 必须等于上述冻结值。模型 inventory 使用 `https://api.labforge.cc/v1/models`；所有生成任务使用 `https://api.labforge.cc/v1/chat/completions`。不得改用 `/responses`。

外网访问失败时：

export HTTP_PROXY=http://127.0.0.1:17897
export HTTPS_PROXY=http://127.0.0.1:17897
export ALL_PROXY=http://127.0.0.1:17897

13.2 连接顺序

direct → `http://127.0.0.1:17897`。先做直连 probe；只有直连失败后才使用回环代理，并记录实际 route、endpoint、错误分类和每次尝试。两条路径均无进展时生成 stall report。

代理不能永久硬编码到科学配置中。网络 route 属于运行环境 metadata。

13.3 API Client

推荐：

client: httpx.AsyncClient
connect_timeout: 30
read_timeout: 300
write_timeout: 300
pool_timeout: 60
max_connections: 8
max_keepalive_connections: 4

正式并发从 4 开始，不直接使用 8 或更高并发。

14. 配置文件建议

configs/models/formal.yaml

primary_backbone_id: primary_gpt_5_6_sol
replication_backbone_id: DAY1_FREEZE

provider:
  base_url: https://api.labforge.cc/v1
  api_key_env: OPENAI_API_KEY
  model_inventory_endpoint: /models
  generation_endpoint: /chat/completions
  request_protocol: openai_compatible_chat_completions
  message_contract: exactly_one_user_message_no_system_or_developer
  request_output_limit_field: max_tokens
  max_route_attempts: 2
  response_field: choices[0].message.content
  usage_fields: [prompt_tokens, completion_tokens]

leaf_constructor:
  model: gpt-5.6-sol
  max_tokens: 512
  temperature: 0
  seed: 0

merge:
  model: gpt-5.6-sol
  temperature: 0
  pilot_replicates: 3
  formal_replicates: 5

answer:
  model: gpt-5.6-sol
  max_tokens: 512
  temperature: 0

judge:
  model: gpt-5.5
  max_tokens: 128
  temperature: 0
  cache_required: true

embedding:
  model: BAAI/bge-m3
  revision: DAY1_FREEZE
  tokenizer_revision: DAY1_FREEZE
  device: cuda
  precision: fp16

retrieval:
  candidate_top_k: all
  similarity: cosine
  packing: relevance_greedy
  render_order: chronological

configs/models/development.yaml

smoke:
  model: gpt-5.4-mini

cheap_debug:
  model: gpt-5.6-luna

code_review:
  model: codex-auto-review

Development 模型的任何结果都不能复制进正式 artifact。

15. 成本控制

15.1 成本日志

每次调用记录：

role
backbone
model
k
episode
plan
budget
replicate
input tokens
output tokens
cached input tokens
latency
retry
cost

15.2 Hard Cap

每个实验命令必须接受：

--max-cost <value>

达到上限后：

-停止发新请求；-等待已提交请求结束；-写出 partial manifest；-不丢失已完成 cache；-提示用户重新确认预算。

15.3 不允许省钱的环节

以下环节不得为了节省成本使用弱模型：

-正式 leaf；-正式 merge；-Full Context；-topology answer；-正式 judge；-D_leaf qualification；-acceptance。

可以使用弱模型的环节：

API smoke；

schema 测试；-错误处理测试；

parser 测试；-代码 review。

16. 卡住时的处理规则

如果同一模型步骤出现以下任一情况：

两次实质不同的修复后仍无进展；

连续一个工作会话没有新增通过测试；-反复出现相同 API 错误；-不断重试但没有新增诊断证据；-成本持续增加但成功率未改善；

必须立即停止盲目重试。

生成：

artifacts/stall_reports/<timestamp>.md

至少包含：

当前阶段
使用模型
错误类型
已尝试措施
每次尝试结果
累计调用数
累计成本
最可能原因
下一步候选
需要用户决定的问题

并立即告诉用户。

不得：

-静默循环；-无限 retry；-偷偷切换模型；-偷偷降低输入长度；-偷偷改变 prompt；-把失败样本删除后继续。

17. 最终冻结清单

进入正式 pilot 前，必须确认：

Leaf 使用 gpt-5.6-sol

replication backbone 为不同模型家族 explicit snapshot

replication leaf cache 与 primary 隔离

K_planned=[4,8,16]、k_primary=8

Merge 使用 gpt-5.6-sol

Answer 使用 gpt-5.6-sol

Judge 使用 gpt-5.5

Embedding 使用本地 BAAI/bge-m3

embedding/tokenizer revision 已固定

strong Retain ranking/packing/render contract 已冻结

本地 3090 Ti 不承担正式生成

115K probe 已通过

4096 output probe 已通过

concurrency 1/2/4 已测

model ID 与 provider response 已记录

leaf cache 已冻结

answer cache 合同已冻结

judge cache 已冻结

judge repeatability 已通过

网络 probe 必须 direct-first；只有直连失败才记录 `proxy_17897`，两条路径失败即 stall

hard cost cap 已生效

自动 fallback 已关闭

formal 与 development 配置已隔离

stalled-stage 报告机制已实现

18. 一句话执行规则

Primary 正式生成统一使用 gpt-5.6-sol，
正式判分使用 gpt-5.5，
embedding 和所有非生成工作使用本地 3090 Ti，
mini/luna 只做工程调试，
replication 使用 Day 1 冻结的不同模型家族；任何正式模型或 embedding 切换都必须停止实验、记录原因并重新资格验证。
