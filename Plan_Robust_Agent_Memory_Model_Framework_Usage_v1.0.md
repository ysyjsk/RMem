# Plan-Robust Agent Memory：模型调用框架使用说明 v1.0

## 0. 文档定位

本文档是 `Plan_Robust_Agent_Memory_Phase1_TDD_Workplan` 的配套执行说明。

注意api-key已经通过

export OPENAI_API_KEY="具体API_KEY"

注入了，如果用openai的接口的话，把baseurl改成https://api.labforge.cc/v1

curl "https://api.labforge.cc/v1/models" \
  -H "Authorization: Bearer sk-你的 API Key"

如果出现问题请停止直接向我报告

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

# 1. 总体架构

正式实验采用以下固定分工：

```text
远程 API
├── gpt-5.6-sol
│   ├── Leaf Constructor
│   ├── Internal Merge
│   ├── Full Context Answer
│   ├── Budget-Matched Retain Answer
│   ├── Topology Memory Answer
│   └── D_leaf Qualification
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
```

核心原则：

> 除 embedding 和纯工程计算外，正式生成式工作全部走 API。

本地 3090 Ti 不承担：

- 115K Full Context；
- 正式 leaf construction；
- 正式 internal merge；
- 正式 answer generation；
- 正式 LLM judge。

---

# 2. 模型角色总表

| 角色 | 固定模型 | 运行位置 | 是否进入正式结果 | 是否允许自动降级 |
|---|---|---|---:|---:|
| Leaf Constructor | `gpt-5.6-sol` | API | 是 | 否 |
| Internal Merge | `gpt-5.6-sol` | API | 是 | 否 |
| Full Context Answer | `gpt-5.6-sol` | API | 是 | 否 |
| Budget-Matched Retain Answer | `gpt-5.6-sol` | API | 是 | 否 |
| Topology Memory Answer | `gpt-5.6-sol` | API | 是 | 否 |
| Primary Judge | `gpt-5.5` | API | 是 | 否 |
| Official Compatibility Judge | 官方 LongMemEval 指定模型快照 | 官方 API | 只作兼容审计 | 否 |
| Embedding | `BAAI/bge-m3` | 本地 3090 Ti | 是 | 否 |
| API Smoke Test | `gpt-5.4-mini` | API | 否 | 可 |
| 低成本工程调试 | `gpt-5.6-luna` | API | 否 | 可 |
| 可选成本消融 | `gpt-5.6-terra` | API | 仅单独消融 | 否 |
| 代码 Review | `codex-auto-review` | API | 否 | 不适用 |

任何正式 artifact 中都必须记录：

```text
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
created_at
```

---

# 3. 正式生成模型：gpt-5.6-sol

## 3.1 使用范围

`gpt-5.6-sol` 用于所有会影响最终科学结论的生成任务：

1. leaf construction；
2. internal merge；
3. Full Context 回答；
4. Budget-Matched Retain 回答；
5. topology memory 回答；
6. online balanced baseline；
7. periodic reconstruction baseline；
8. D_leaf qualification；
9. prompt stress branch；
10. acceptance 正式回答。

不得在不同 topology 之间替换模型。

## 3.2 为什么统一使用同一模型

统一使用 `gpt-5.6-sol` 可以保证 primary experiment 中只改变 topology，不引入以下混淆：

- constructor 模型能力变化；
- merge 模型能力变化；
- answer 模型能力变化；
- provider 路由差异；
-模型间不同压缩习惯；
- 模型间不同时间推理能力。

正式实验中的 operator 应写作：

```text
mu_(gpt-5.6-sol, prompt_id, B)
```

而不是模糊写成“LLM merge”。

## 3.3 固定调用参数

推荐冻结为：

```yaml
model: gpt-5.6-sol
endpoint: responses
temperature: 0
top_p: 1
max_retries: 3
timeout_seconds: 300
stream: false
```

若 API 不接受 `temperature`、`top_p` 或显式 seed：

1. 删除不支持参数；
2. 不伪造 determinism；
3. 记录 provider 实际接受的参数；
4. repeated run 定义为“相同配置下独立调用”；
5. 不宣称是可控随机种子实验。

正式实验禁止自动切换到其他模型。

---

# 4. Leaf Constructor

## 4.1 固定模型

```yaml
role: leaf_constructor
model: gpt-5.6-sol
location: API
```

## 4.2 固定结构

```yaml
k: 8
C_leaf: 512
s_leaf: 0
```

每个 LongMemEval episode 约 115K token，按八个连续 token-balanced 区间划分。每个 leaf 输入平均约：

```text
115K / 8 ≈ 14.4K tokens
```

## 4.3 Leaf Constructor 输入

仅允许输入：

- 当前 leaf 覆盖的原始 sessions；
- session 时间；
- evidence IDs；
- leaf 输出 schema；
- `C_leaf` 限制；
- leaf prompt。

禁止输入：

- question；
- gold answer；
- answer_session_ids；
- supporting evidence 标注；
- topology；
- budget；
-其他 leaf 的输出。

## 4.4 Leaf Constructor 输出

输出必须包含：

```json
{
  "memory": "...",
  "source_evidence_ids": ["..."],
  "time_range": {
    "start": "...",
    "end": "..."
  }
}
```

要求：

- `memory` 不超过 `C_leaf`；
- provenance 可回溯；
- 不允许静默截断；
- 不允许因“结果不好”而重复生成直到满意。

## 4.5 Leaf Cache

Leaf cache key：

```text
sha256(
  dataset_commit
  + episode_id
  + evidence_span
  + C_leaf
  + leaf_prompt_hash
  + model
  + decoding_config
  + s_leaf
)
```

不得包含：

```text
budget_id
topology_id
query_id
answer_id
```

同一个 leaf 生成一次，跨所有 budget 和 topology 复用。

## 4.6 禁止替代模型

正式 leaf 禁止使用：

- `gpt-5.4-mini`；
- `gpt-5.6-luna`；
- `gpt-5.6-terra`；
- 本地开源模型；
- judge 模型。

原因：leaf 是所有后续实验的共享基础，低质量 leaf 会系统性污染所有条件。

---

# 5. Internal Merge

## 5.1 固定模型

```yaml
role: merge
model: gpt-5.6-sol
location: API
```

## 5.2 Primary Operator

```yaml
prompt: merge_prompt_v1_primary
model: gpt-5.6-sol
```

Primary prompt 目标：

- 保留事实；
- 保留时间顺序；
- 正确处理旧值与新值；
- 合并重复事实；
- 不引入无来源事实；
- 输出不超过 B；
- 保留 provenance。

## 5.3 Stress Operator

```yaml
prompt: merge_prompt_v2_stress
model: gpt-5.6-sol
```

Stress prompt：

- 与 primary 使用相同模型；
- 使用相同容量；
- 使用相同输出 schema；
- 更强调抽象、去重和跨 evidence 综合；
- 仍必须保持事实与时间正确；
- 不得故意设计为容易失败的 prompt。

Stress prompt 只在 primary prompt 全部为 null 的 NO-GO 分支中运行。

## 5.4 Budget

Primary budget sweep：

```yaml
B_grid:
  - 512
  - 1024
  - 2048
  - 4096
```

在每个预算点：

```text
B_merge = B_final = B_query = B
```

其中：

- `B_merge`：每个 internal merge 的最大输出；
- `B_final`：root memory 最大输出；
- `B_query`：最终送给 answer model 的 memory payload 上限。

## 5.5 Merge 输入

每次 merge 只允许输入：

- 左子节点；
- 右子节点；
- 它们的 provenance；
- 它们的时间范围；
- 当前 budget；
- merge prompt。

禁止输入：

- query；
- gold；
- answer evidence；
- plan 名称；
- “哪个 topology 应该更好”的提示。

## 5.6 Merge Repeated Runs

```yaml
R_pilot: 3
R_formal: 5
```

Repeated run 只改变独立调用编号：

```text
replicate_id = 0, 1, 2, ...
```

同一 replicate ID 在所有 topology 之间配对。

如果 provider 支持 seed：

```text
s_merge = replicate_id
```

如果 provider 不支持 seed：

- 使用相同调用配置；
- 每个 topology 独立调用；
- 记录 request ID；
- 不宣称严格随机种子可控。

---

# 6. Answer Model

## 6.1 固定模型

```yaml
role: answer
model: gpt-5.6-sol
location: API
```

所有正式回答条件必须使用同一个 answer model：

- Full Context；
- Budget-Matched Retain；
- left-deep；
- balanced；
- right-deep；
- online balanced；
- periodic reconstruction；
- 后续正式方法。

## 6.2 Full Context

输入：

```text
完整约 115K history
+ 当前 question
+ 固定 answer prompt
```

默认：

```yaml
max_output_tokens: 512
temperature: 0
```

用途：

- SATURATION-01；
- Context Saturation Gap；
- 任务上界诊断；
- calibration Full Context baseline。

Full Context 不走本地 3090 Ti。

## 6.3 Budget-Matched Retain

输入：

```text
在 B_query 内保留的 raw evidence
+ question
+ answer prompt
```

必须使用与 topology answer 相同的：

- `gpt-5.6-sol`；
- answer prompt；
- max output；
- decoding；
- question formatting。

## 6.4 Topology Memory Answer

输入：

```text
最终 memory view
+ question
+ answer prompt
```

禁止附加：

- topology 名称；
- merge depth；
-构造过程说明；
- hidden provenance；
-其他 topology 输出。

## 6.5 Answer Cache

Cache key：

```text
sha256(
  question_id
  + context_or_memory_hash
  + answer_prompt_hash
  + model
  + decoding_config
  + replicate_id
)
```

Acceptance 阶段禁止 cache miss 后静默重算。

---

# 7. Judge

## 7.1 项目内主 Judge

```yaml
role: judge
model: gpt-5.5
location: API
```

选择独立于生成模型的 `gpt-5.5`，避免使用 `gpt-5.6-sol` 自评。

Judge 使用范围：

- LongMemEval-compatible task correctness；
- Full Context 判分；
- Retain 判分；
- topology answer 判分；
- judge repeatability；
- acceptance 正式判分。

## 7.2 Judge 输入

只允许输入：

- question；
- reference answer；
- candidate answer；
- 官方兼容 judge rubric；
- strict output schema。

禁止输入：

- topology；
-方法名；
- budget；
-模型名；
-成本；
- expected result；
-其他候选答案。

## 7.3 Judge 输出

推荐：

```json
{
  "label": 0,
  "reason": "..."
}
```

正式 task score 只使用 `label`。

`reason` 仅用于错误检查，不作为自动二次判分输入。

## 7.4 Judge 参数

```yaml
model: gpt-5.5
temperature: 0
max_output_tokens: 128
response_format: json
```

如果 provider 不支持严格 JSON schema：

- 使用文本输出；
- 本地 parser 严格验证；
- parsing failure 不自动记为 0；
- parsing failure 必须进入 retry/qualification 日志。

## 7.5 Judge Repeatability

在正式使用前运行：

```text
50 cases × 3 independent judgments
```

要求：

```text
unanimity_rate >= 0.95
pairwise_flip_rate <= 0.05
parse_success_rate = 1.00
```

不通过时：

1. 不得继续正式 LongMemEval 判分；
2. 改为预注册 3-vote majority；
3. 使用新 qualification subset 复验；
4. 仍失败则该 judge 不具备 confirmatory 资格。

## 7.6 Judge Cache

Cache key：

```text
sha256(
  question_id
  + reference_answer_hash
  + candidate_answer_hash
  + judge_prompt_hash
  + judge_model
  + decoding_config
  + output_schema_version
)
```

相同 candidate answer 只能 judge 一次。正式统计只读冻结 cache。

## 7.7 官方 LongMemEval 兼容性

当前 API 模型列表中没有官方 GPT-4o judge，因此：

- `gpt-5.5` 定位为项目内 LongMemEval-compatible judge；
- 不能直接宣称完全复现官方 LongMemEval 分数；
- 最终论文如需与官方数字直接横向比较，应另行使用官方 OpenAI GPT-4o 日期快照，对固定子集做 agreement audit；
- 官方兼容审计不能改变项目内主 judge 已冻结的结果。

---

# 8. Embedding 与 Retrieval

## 8.1 固定 Embedding 模型

```yaml
role: embedding
model: BAAI/bge-m3
location: local_3090ti
precision: fp16
batch_size: auto_probe
```

Embedding 用于：

- Budget-Matched Retain；
- retrieval baseline；
-近重复检测辅助；
- evidence ranking；
-后续检索诊断。

## 8.2 Embedding 禁止事项

Embedding 不用于：

- leaf construction；
- merge；
- answer；
- judge；
-支持答案正确性判定；
-替代原 evaluator。

## 8.3 Retrieval

Retrieval 全部在本地运行。正式 retrieval 配置必须冻结：

```text
embedding model
chunk definition
similarity metric
top-k or token budget
tie-break
index version
```

不得根据 acceptance query 表现修改 retrieval。

---

# 9. 各 Workplan 阶段的模型调用清单

## M-1：Phase 0

需要模型：

```text
gpt-5.6-sol：115K Full Context probe
gpt-5.6-sol：4096 output probe
gpt-5.5：judge endpoint probe
```

本阶段不产生正式科学结果，只验证：

- 上下文窗口；
-输出上限；
-吞吐；
-usage；
- provider route；
-模型名；
-成本。

## M0：测试骨架

不需要正式模型。

允许：

```text
gpt-5.4-mini
```

只用于 API client smoke test。输出不能进入数据或科学 artifact。

## M1：Schema 与术语

不需要模型。

## M2：LongMemEval Adapter

不需要生成式模型。

只使用：

- 本地 Python；
- tokenizer；
- checksum；
- schema validation。

## M3：Split 与 Leakage

不需要生成式模型。

Embedding near-duplicate 警报可以使用：

```text
BAAI/bge-m3
```

但 embedding 相似度不能自动决定删除。

## M4：Evaluator Wrapper

需要：

```text
gpt-5.5
```

用于：

- judge probe；
- 50×3 repeatability；
- judge cache；
- parser qualification。

## M5：MemoryAgentBench Audit

不需要生成式模型。

## M6：Fixed Leaf 与 Prompt

需要：

```text
gpt-5.6-sol
```

用途：

- development prompt micro-test；
-正式 leaf generation；
- prompt output schema test。

正式 leaf 只能在所有合同和测试通过后生成。

## M7：Plan Generator

不需要模型。

## M8：Budget 与 SATURATION-01

需要：

```text
gpt-5.6-sol
    Full Context Answer
    Budget-Matched Retain Answer

gpt-5.5
    Judge
```

本阶段是首次真实大上下文质量调用。

## M9：统计协议

不需要生成式模型。

## M10：Protocol Freeze

不允许新增模型调用。

只允许读取：

- frozen model configs；
- probe results；
- judge qualification；
- cache manifests；
- checksums。

## Q0：D_leaf Qualification

需要：

```text
gpt-5.6-sol
```

固定：

- balanced topology；
- merge replicate；
- answer replicate。

只改变：

```text
s_leaf ∈ {0,1,2,3,4}
```

Judge：

```text
gpt-5.5
```

Q0 完成后才能进入 pilot。

## Feasibility Pilot

需要：

```text
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
```

---

# 10. Day 1 推理基座探针

## 10.1 必须探测的模型

```text
gpt-5.6-sol
gpt-5.5
```

可选 smoke model：

```text
gpt-5.4-mini
```

## 10.2 gpt-5.6-sol Probe

选择 5 个 development episode，加 1 个 warm-up。

测试：

```yaml
input_tokens: approximately 115000
max_output_tokens: 512
concurrency:
  - 1
  - 2
  - 4
```

额外执行：

```yaml
input_tokens: small
max_output_tokens: 4096
```

记录：

- success；
- prompt tokens；
- completion tokens；
- TTFT；
- total latency；
- request ID；
- returned model；
- retry；
- HTTP status；
- cost；
- proxy route。

## 10.3 gpt-5.5 Judge Probe

执行至少 5 个固定 QA pair：

- 2 个正确；
- 2 个错误；
- 1 个部分正确。

检查：

-接口可达；
- JSON 可解析；
-模型名返回；
- usage 完整；
-无 rolling fallback。

## 10.4 通过条件

```text
115K request success = 5/5
context length error = 0
silent truncation = 0
usage available = true
P95 latency <= 180 s
concurrency 4 error rate <= 5%
4096 output probe success = true
judge parser success = 100%
```

未通过时，不得冻结：

- `C_leaf`；
- budget grid；
- answer model；
- SATURATION-01；
-正式成本估计。

---

# 11. 模型降级规则

## 11.1 正式模型禁止自动降级

以下模型失败时不得静默切换：

```text
gpt-5.6-sol
gpt-5.5
BAAI/bge-m3
```

## 11.2 Answer / Constructor / Merge 的人工降级顺序

仅在 Day 1 probe 或明确基础设施失败时讨论：

```text
gpt-5.6-sol
→ gpt-5.5
→ gpt-5.4
```

每次切换必须：

1. 生成 decision log；
2. 说明原模型失败原因；
3. 重跑 115K probe；
4. 重跑 prompt micro-test；
5. 更新全部 model config；
6. protocol version 发生变化。

不得切到 `mini/luna` 作为正式模型。

## 11.3 Judge 的人工替换

若 `gpt-5.5` 不稳定：

```text
gpt-5.5
→ 重新资格验证的独立强模型
```

不能直接换为 answer model 后继续使用旧 qualification。

## 11.4 Embedding 替换

更换 embedding 会改变 retrieval baseline，因此必须：

- 更新 index；
-重跑 retrieval；
-升级 protocol；
-禁止复用旧 retrieval cache。

---

# 12. API 与代理配置

## 12.1 环境变量

```bash
export OPENAI_API_KEY="..."
export OPENAI_BASE_URL="https://<provider>/v1"
```

外网访问失败时：

```bash
export HTTP_PROXY=http://127.0.0.1:17897
export HTTPS_PROXY=http://127.0.0.1:17897
export ALL_PROXY=http://127.0.0.1:17897
```

## 12.2 连接顺序

```text
直连 probe
→ 失败后使用 127.0.0.1:17897
→ 记录实际 route
```

代理不能永久硬编码到科学配置中。网络 route 属于运行环境 metadata。

## 12.3 API Client

推荐：

```yaml
client: httpx.AsyncClient
connect_timeout: 30
read_timeout: 300
write_timeout: 300
pool_timeout: 60
max_connections: 8
max_keepalive_connections: 4
```

正式并发从 4 开始，不直接使用 8 或更高并发。

---

# 13. 配置文件建议

## configs/models/formal.yaml

```yaml
provider:
  base_url_env: OPENAI_BASE_URL
  api_key_env: OPENAI_API_KEY
  endpoint: responses

leaf_constructor:
  model: gpt-5.6-sol
  max_output_tokens: 512
  temperature: 0
  seed: 0

merge:
  model: gpt-5.6-sol
  temperature: 0
  pilot_replicates: 3
  formal_replicates: 5

answer:
  model: gpt-5.6-sol
  max_output_tokens: 512
  temperature: 0

judge:
  model: gpt-5.5
  max_output_tokens: 128
  temperature: 0
  cache_required: true

embedding:
  model: BAAI/bge-m3
  device: cuda
  precision: fp16
```

## configs/models/development.yaml

```yaml
smoke:
  model: gpt-5.4-mini

cheap_debug:
  model: gpt-5.6-luna

code_review:
  model: codex-auto-review
```

Development 模型的任何结果都不能复制进正式 artifact。

---

# 14. 成本控制

## 14.1 成本日志

每次调用记录：

```text
role
model
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
```

## 14.2 Hard Cap

每个实验命令必须接受：

```bash
--max-cost <value>
```

达到上限后：

-停止发新请求；
-等待已提交请求结束；
-写出 partial manifest；
-不丢失已完成 cache；
-提示用户重新确认预算。

## 14.3 不允许省钱的环节

以下环节不得为了节省成本使用弱模型：

-正式 leaf；
-正式 merge；
-Full Context；
-topology answer；
-正式 judge；
-D_leaf qualification；
-acceptance。

可以使用弱模型的环节：

- API smoke；
- schema 测试；
-错误处理测试；
- parser 测试；
-代码 review。

---

# 15. 卡住时的处理规则

如果同一模型步骤出现以下任一情况：

- 两次实质不同的修复后仍无进展；
- 连续一个工作会话没有新增通过测试；
-反复出现相同 API 错误；
-不断重试但没有新增诊断证据；
-成本持续增加但成功率未改善；

必须立即停止盲目重试。

生成：

```text
artifacts/stall_reports/<timestamp>.md
```

至少包含：

```text
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
```

并立即告诉用户。

不得：

-静默循环；
-无限 retry；
-偷偷切换模型；
-偷偷降低输入长度；
-偷偷改变 prompt；
-把失败样本删除后继续。

---

# 16. 最终冻结清单

进入正式 pilot 前，必须确认：

- [ ] Leaf 使用 `gpt-5.6-sol`
- [ ] Merge 使用 `gpt-5.6-sol`
- [ ] Answer 使用 `gpt-5.6-sol`
- [ ] Judge 使用 `gpt-5.5`
- [ ] Embedding 使用本地 `BAAI/bge-m3`
- [ ] 本地 3090 Ti 不承担正式生成
- [ ] 115K probe 已通过
- [ ] 4096 output probe 已通过
- [ ] concurrency 1/2/4 已测
- [ ] model ID 与 provider response 已记录
- [ ] leaf cache 已冻结
- [ ] answer cache 合同已冻结
- [ ] judge cache 已冻结
- [ ] judge repeatability 已通过
- [ ] API proxy `17897` 已探活
- [ ] hard cost cap 已生效
- [ ] 自动 fallback 已关闭
- [ ] formal 与 development 配置已隔离
- [ ] stalled-stage 报告机制已实现

---

# 17. 一句话执行规则

```text
正式生成统一使用 gpt-5.6-sol，
正式判分使用 gpt-5.5，
embedding 和所有非生成工作使用本地 3090 Ti，
mini/luna 只做工程调试，
任何正式模型切换都必须停止实验、记录原因并重新资格验证。
```
