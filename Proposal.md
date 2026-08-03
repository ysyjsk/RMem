# Plan-Robust Agent Memory Materialization

## 预算条件下的在线、固定叶语义归约

**文档状态：Research Proposal v0.2（最终核验修订版）**  
**日期：2026 年 8 月 1 日**  
**当前阶段：冻结研究命题、系统模型与评测协议；尚未选择最终方法**

---

## 0. Proposal 的目的

本 proposal 定义一个具备顶会研究潜力、但可被早期 baseline 结果直接证伪的 Agent Memory 问题，并规定后续研究必须遵循的测试集、测试原则、评价指标、baseline 与停止条件。

当前阶段不要求预先提出完整方法，也不单独建设一套 motivation experiment。研究流程为：

$$
\text{冻结问题与系统契约}
\rightarrow
\text{冻结评测协议}
\rightarrow
\text{运行 Baseline}
\rightarrow
\text{确认方法空间}
\rightarrow
\text{设计方法}
\rightarrow
\text{完整实验与论文}
$$

Baseline 结果同时承担三项功能：

1. 验证测试协议能否隔离所研究的现象；
2. 判断简单规范化方案或现有强方法是否已经解决问题；
3. 为后续方法提供明确、可量化的改进目标。

本 proposal 不承诺论文一定被顶会录用。只有当以下条件同时成立时，工作才具备完整的顶会方法论文形态：

- fixed-leaf 协议下存在超出生成随机性的行为级拓扑效应；
- 该效应在多个预算区间、数据集或 memory backend 上成立；
- matched-budget retention、规范平衡归约、在线平衡归约、周期重建及现有可靠性方法不能同时解决质量、鲁棒性和成本问题；
- 最终方法改善三维 Pareto 前沿，而不是仅增加成本或退化为全量 raw history。

---

# 1. 研究背景与已知前提

长期运行的 LLM Agent 通常同时维护两类信息：

1. **Raw episodic evidence**：原始对话、轨迹、工具调用和环境反馈；
2. **Consolidated memory**：通过总结、抽象、合并、更新或结构化得到的派生记忆。

Raw evidence 保真度较高，但随着历史增长，查询时的检索、上下文组织和重复处理成本会持续增加。Consolidation 的价值不是保证提高绝对准确率，而是在受限 memory/query budget 下，用更紧凑的派生表示提高 evidence coverage、复用效率或查询成本表现。

已有工作已经建立两个前提，本研究不重复将其作为新发现：

- [LightMem](https://arxiv.org/abs/2510.18866) 表明压缩、短期聚合与离线更新可以显著降低 token、API 调用和运行时间，说明 memory construction 的效率价值真实存在。
- [Useful Memories Become Faulty When Continuously Updated by LLMs](https://arxiv.org/abs/2605.12978) 表明连续 LLM consolidation 可能退化；同一 trajectory pool 在 Static-Group、Static-All 和 Stream 等不同 regime 下产生不同 memory 和下游结果，raw episodic control 具有很强竞争力。

此外，[Retain or Consolidate?](https://arxiv.org/abs/2607.17545) 说明 retention 与 consolidation 的相对价值是 **budget-conditioned** 的：紧预算下 consolidation 可通过提高 coverage 显著获益；松预算下该优势消失，部分 operator 甚至不如 retention。因此，本研究的所有结论必须写成预算条件下的结论，而不能宣称 consolidation 或 retention 普遍占优。

本研究不再声称：

- 首次发现 schedule 会影响 memory；
- 首次发现 continuous consolidation 会退化；
- 首次提出 raw evidence 应保留；
- consolidation 必然比 raw memory 更准确。

---

# 2. 最终核心 Idea

## 2.1 一句话命题

> **在固定叶级表示、固定 evidence 顺序和固定输出预算下，生成式 LLM merge 可能因归约拓扑不同而产生行为不同的派生 memory；精确路径不变的集合式 retention 又缺乏跨 evidence 的语义合成能力。本研究刻画并缩小这种“路径收敛性—语义组合能力”之间的差距，目标是在在线、可查询的长期 memory 中同时获得较高任务质量、较低拓扑敏感性和可接受生命周期成本。**

## 2.2 相较现有工作的核心 wedge

*Useful Memories Become Faulty* 已经比较不同 grouping/update regime，但这些 regime 同时改变了：

- 叶级输入内容；
- 每次 constructor 可见的 evidence；
- 中间状态被重写的次数；
- 最终归约结构。

因此，它没有单独隔离：

$$
\text{固定叶级表示之后，仅归约括号结构本身是否改变最终行为。}
$$

本研究的主协议先生成完全相同、字节级复用的叶节点，再只改变归约拓扑。这是与现有 schedule-level 诊断工作的主要实验差异。

## 2.3 不是“为什么不用 balanced tree”的预设答案

一个固定的 balanced tree 是必须运行的强简单 baseline，但不能预先假设它必然解决问题。

同时必须承认：未知流长并不意味着 balanced reduction 无法在线实现。可以使用二进制计数器式或 LSM 式 compaction，在 evidence 持续到达时维护近似平衡层级。因此，proposal 不采用“balanced 必须等待所有叶子到齐”这一错误前提。

真正需要测试的是：

> **简单的离线或在线规范平衡归约，是否已经在合理成本下关闭 topology gap？**

若答案为“是”，则新方法空间显著缩小，应停止方法论文路线或转为 analysis/benchmark 工作；不能为了保留论文故事而忽略这个简单答案。

---

# 3. 系统模型与 Merge Operator 契约

原 proposal 使用了未定义的 $\oplus$。本版在任何代码实现前冻结如下契约。

## 3.1 原始 evidence 与固定叶

给定按语义时间顺序排列的 immutable evidence stream：

$$
E=(e_1,e_2,\ldots,e_n).
$$

先使用固定 leaf constructor $g$，按固定连续边界生成叶节点：

$$
L=(l_1,l_2,\ldots,l_k).
$$

每个叶节点至少包含：

```text
ViewNode
├── content: textual or structured representation
├── span: [start_index, end_index]
├── provenance: source evidence IDs
├── temporal metadata: optional event/valid time
└── token_count
```

在 primary topology experiment 中，同一个 episode、budget 和 leaf seed 下的叶节点只生成一次并缓存；所有 tree plans 复用完全相同的叶节点字节，避免 leaf-generation variance 与 topology effect 混淆。

## 3.2 有序、区间感知的二元 merge

定义：

```text
merge(
    left_view,
    right_view,
    left_span,
    right_span,
    capacity,
    provenance_metadata
) -> merged_view
```

对应数学记号：

$$
v=\mu_B(v_L,v_R).
$$

前置条件：

- $v_L$ 覆盖较早连续区间 $[a,m]$；
- $v_R$ 覆盖较晚连续区间 $[m+1,b]$；
- 两区间连续、不重叠，且保持原始 evidence 顺序；
- 输出覆盖区间 $[a,b]$；
- 输出 token 数不超过节点预算 $B$；
- 输出保留可审计 provenance，所有事实性 claim 应可映射到 source IDs 或明确标记为推导性抽象。

该 operator **不是对称算子，也不要求交换性**。知识更新和时间覆盖具有方向，左、右参数的时序角色必须显式保留。本研究主要测试其在行为等价意义下的结合性或近似结合性。

## 3.3 在线部署模型

Online track 假设：

- evidence 持续到达，最终长度未知；
- query 可以在任意 prefix 后到达；
- 系统必须在每个 prefix 提供可查询的当前 memory view；
- memory output capacity 受限；
- 写侧调用和 query context 成本均计入生命周期成本。

该模型允许在线 balanced compaction，不强制所有系统使用 left-deep；但所有在线方法必须满足 prefix-queryability，不能只在 episode 结束后输出最终 memory。

---

# 4. 形式化研究对象

## 4.1 Reduction tree

给定固定叶序列 $L$，一个保持叶顺序的二叉归约树 $T$ 定义最终 view：

$$
M_T=\operatorname{Fold}_T(L;\mu_B).
$$

不同 tree 只改变括号结构，不改变叶内容和叶顺序。

## 4.2 行为等价

文本不同本身不构成错误。给定与方法开发严格分离的 held-out query/task set $Q_{test}$，定义行为表示：

$$
\mathcal{B}(M;Q_{test})
$$

包括：

- 原任务回答正确性；
- knowledge-update / temporal state；
- task success；
- supporting-evidence faithfulness；
- stale、omission、corruption 和 hallucination 行为。

两个 memory 在测试集合上近似行为等价，记为：

$$
M_{T_1}\simeq_{Q_{test}}M_{T_2}.
$$

这不是文本相似度，也不宣称在全部未知查询上的逻辑等价。

## 4.3 拓扑鲁棒性与结合性

若 merge operator 在行为等价关系下满足：

$$
\mu_B(\mu_B(a,b),c)
\simeq_Q
\mu_B(a,\mu_B(b,c)),
$$

则固定叶序列的所有合法 parenthesization 在该等价关系下具有 tree invariance。反之，若所有三叶序列的两种括号结果均等价，则 operator 在该域上满足相应的行为结合性。

该形式化是问题刻画，不预先断言现有 LLM operator 一定非结合，也不要求最终方法实现字节级结合律。

## 4.4 两个方法端点：收敛与组合

### 端点 A：路径不变的集合状态与确定性 render

保留 content-addressed atomic units，deployment state 使用 set union；query/render 时依据固定、query-independent 的 total order 或检索规则，在预算内确定性选择内容。

这类方案可获得精确的 delivery-order / merge-path invariance，但通常：

- 不产生跨记录的新抽象；
- 在极紧预算下可能 coverage 不足；
- durable source state 仍随历史增长。

注意：若原子项长度不同，直接对每个中间状态执行 token-budget greedy truncation 未必保持结合性。因此 exact endpoint 应采用“完整集合状态 + 确定性预算 render”，或固定大小原子项上的 fixed-$K$ selection，而不能未经证明地把任意 token-budget TopK 写成结合算子。

### 端点 B：自由生成式语义 merge

LLM 可以跨 evidence 去重、总结、抽象和解析冲突，具有更强的 semantic composition，但可能：

- 遗漏或错误覆盖事实；
- 累积多次重写误差；
- 对 tree topology 和维护路径敏感。

本研究最终的方法目标不是简单选择某个端点，而是在该轴上找到更好的点：

$$
\text{更接近路径不变}
\quad+
\text{保留跨 evidence 语义组合}
\quad+
\text{成本低于频繁全量重建}.
$$

---

# 5. 研究问题与可证伪假设

## RQ1：固定叶后，当前 LLM merge 是否仍有行为级 topology effect？

在相同 leaf bytes、原始顺序、模型、prompt、节点容量和 answer pipeline 下，仅改变 tree topology，任务表现是否变化？

该 RQ 是对 *Faulty Memories* 的因果收缩，而不是重复其 schedule-level 发现。

## RQ2：计划差异是否超出普通生成随机性？

比较：

- 同一 topology 的 repeated-run / seed variance；
- 不同 topology 的 paired behavioral difference。

不能仅因三组 noisy estimates 的 max–min 大于零就宣称存在计划效应。

## RQ3：rewrite-depth profile 能否解释错误？

定义叶 $l_i$ 在树 $T$ 中经历的生成式 merge 次数：

$$
d_i(T)=\text{leaf }l_i\text{ 到根节点路径上的 generative merges 数}.
$$

测试：

- 深度更大的 evidence 是否更容易遗漏或失真；
- depth、序列位置、budget、事实类型和冲突类型之间是否存在交互；
- balanced 是否因降低最大/平均 rewrite depth 而改善质量；
- left/right skew 是否对旧事实和新事实产生不同错误分布。

“质量随 depth 单调下降”仅是待检验机制假设，不是预设定律。已有连续更新结果可能呈 inverted-U，且 evidence quantity 与 rewrite count 存在混淆。

## RQ4：简单 canonical tree 是否已经足够？

比较：

- offline canonical balanced tree；
- online canonical balanced compaction；
- eager left-deep；
- periodic rebuild。

若简单在线 balanced 在近似成本下关闭主要质量和方差差距，则不再硬做复杂方法。

## RQ5：路径不变 selection 与生成式 composition 之间的真实代价是什么？

比较 exact set+render retention endpoint 与 generative merge，量化：

- topology variance；
- evidence coverage；
- multi-evidence reasoning；
- temporal update；
- lifecycle cost。

## RQ6：现有可靠性方法是否已解决？

测试 transition verifier、transaction boundary、provenance/non-destructive update、周期重建等方法，判断它们是否能同时改善：

$$
(Q_{mean},Q_{worst},\Delta Q_{plan},C_{life}).
$$

---

# 6. 研究范围与明确非目标

## 6.1 第一版研究范围

第一版只研究：

- 固定原始 evidence 顺序；
- 固定叶级表示；
- 有序、区间感知的二元 merge；
- reduction topology；
- budget-conditioned 行为；
- 在线 prefix-queryability；
- construction 与 repeated-query 的生命周期成本。

## 6.2 第一版不研究

暂不研究：

- 任意 session 重排序；
- 未标注语义独立性的 permutation；
- 多 GPU 调度；
- construction job priority；
- deadline / queue backlog；
- 多租户资源分配；
- future utility prediction；
- admission control。

任意重排序需要 supersession、因果、define-use 和独立性标注，否则不同结果可能只是违反真实语义顺序，而非系统错误。

---

# 7. 测试集设计

本工作不从零创建语义任务，而是在现有 Agent Memory benchmark 上增加 fixed-leaf topology evaluation wrapper。

## 7.1 Episode 基本契约

```text
Episode
├── ordered raw experiences
├── downstream queries or tasks
├── gold answers / outcomes
├── original evaluator
└── optional evidence / temporal / conflict annotations
```

## 7.2 主数据集优先级

### A. MemoryAgentBench FactConsolidation-SH

主开发数据集。用于：

- 多 evidence consolidation；
- 单跳 fact consolidation；
- 规避 FactConsolidation-MH 的严重地板效应；
- 测试固定叶后不同 topology 的影响。

### B. MemoryAgentBench Conflict Resolution

用于：

- 新旧事实更新；
- 冲突解析；
- old/new evidence 对不同 rewrite-depth profile 的敏感性。

### C. LongMemEval-S 的 knowledge-update / temporal 类

用于：

- 长期会话事实更新；
- temporal reasoning；
- budget sweep；
- 与 Retain-or-Consolidate、MemDelta 和 MemTxn 的相关设置对齐。

## 7.3 Replication 与错误审计

### LoCoMo

降为真实多 session 会话 replication，不独立承担主结论。必须按问题类型分层报告，而不能预设其效应一定为零。

### HaluMem

作为 operation-level audit：

- coverage；
- preservation；
- faithfulness；
- omission；
- corruption；
- hallucination；
- stale update。

## 7.4 Context Saturation Gap

必须加入 Full Context baseline，并报告 Context Saturation Gap 作为 diagnostic；但不将其用作 episode 的硬过滤规则。Full Context 可解并不意味着该样本不能用于评价 memory 的成本、可更新性和 topology robustness。

---

# 8. Maintenance Plan 协议

## 8.1 Primary：Fixed-Leaf Offline Topology

固定同一组叶节点：

$$
L=(l_1,\ldots,l_k).
$$

测试：

### Left-deep

$$
(((l_1\oplus l_2)\oplus l_3)\oplus\cdots)\oplus l_k.
$$

代表 eager streaming update 的典型形态。

### Balanced

按固定、确定性的平衡树递归归约。

代表降低最大 rewrite depth 的简单规范计划。

### Right-deep

$$
l_1\oplus(l_2\oplus(\cdots\oplus l_k)).
$$

在区间感知 merge 契约下保持原始 leaf order，因此可作为 **offline algebraic diagnostic**。它不属于自然在线部署计划，因为需要先构造未来子树；若 backend 的 API 只能表达 `old_state + new_chunk` 且无显式区间语义，则不纳入该 backend 的合法主计划。

## 8.2 Primary Online Track

### Eager left-deep

每个新 leaf 到达后立即更新一个单一 current view。

### Online canonical balanced compaction

采用确定性 level-based / binary-counter compaction：相同 level 的相邻连续区间合并，保持每个 leaf 的 rewrite depth 为 $O(\log n)$。任意 prefix 后系统可能持有一个有序 forest；query 时使用固定 packing/render 规则生成当前 view。

该 baseline用于直接回答“为什么不简单一直 balanced”。

### Periodic reconstruction

每隔固定 interval 从 immutable leaves 或 raw evidence 重新构建 view，作为高成本鲁棒基线。

## 8.3 Budget 扫描

Memory capacity 是一等实验轴，而非只固定一个值。

每个数据集至少覆盖：

- severe/tight；
- transition；
- loose；

四个或以上预算点。具体绝对 token 值通过 dev/calibration split 选择，使 matched-budget retention 的 evidence-fit fraction 覆盖从低到高的区间。

同时报告：

$$
r=\frac{B}{|E|_{tokens}}
$$

或与 candidate evidence 长度对应的相对压缩率，避免把某个绝对 token threshold 错当成跨数据集规律。

## 8.4 Secondary：Contiguous Partition

batch size / chunk boundary 会同时改变 leaf 内容、调用次数和检索粒度，因此只作为生态 sensitivity 或附录实验，不作为证明 topology effect 的主协议。

## 8.5 第一版禁止的计划

禁止：

- 任意 random shuffle；
- 无标注的 independent swap；
- 破坏原始时间顺序；
- 在无区间语义时将旧事实作为“新 chunk”写回；
- 将不同 leaf constructor 输出误当成 topology-only 对照。

---

# 9. 测试原则

## 9.1 原始任务质量优先

保留原 benchmark 的 accuracy、F1、judge score、task success 和 conflict-resolution accuracy。Memory 文本相似度不作为主质量指标。

## 9.2 行为等价，而非文本等价

不同 wording 可以同样正确。鲁棒性必须由 query/task behavior 和 source-grounded audit 判断。

## 9.3 Q_dev 与 Q_test 严格分离

若后续方法使用 probe、query、verifier 或 utility model，则用于训练、阈值校准和 candidate selection 的 $Q_{dev}$ 与最终 $Q_{test}$ 必须在 question、episode 或 template 层面隔离。

## 9.4 Immutable source of truth

所有方法保留 raw evidence 或可恢复的 source journal。Raw evidence 可用于 audit、rebuild 和错误定位，但每次 query 的读取成本必须真实记账。

## 9.5 资源控制优先级

Primary topology comparison 中硬固定：

1. leaf bytes；
2. leaf order；
3. merge operator 与 prompt；
4. internal merge count；
5. per-node / final output capacity；
6. retriever、answer model 和 query context budget。

不同 topology 的 constructor input tokens 可能天然不同，不能同时被强行固定。实际 construction tokens、calls 和 wall-clock 必须完整报告，并进入成本轴。

## 9.6 Backbone 与 retrieval 控制

依据 MemDelta 的评价警告：

- 同一 controlled track 固定 embedding model；
- 固定 retrieval pipeline；
- 固定 answer model；
- 对不同 backbone 进行独立 replication；
- 不将 backbone 或 embedding 变化造成的收益归因于 memory architecture。

## 9.7 Benchmark Observability 的科学边界

除了测量 topology 引起的行为差异，本 benchmark 还在 plan、merge、node 和
evidence 粒度记录预注册的可观测变量，包括生成式重写深度、内容相对预算
暴露、合并对象平衡、顺序角色暴露和资源用量。这些变量由原始运行产物事后
重建，仅作为带 episode-clustered 不确定性区间的描述性 secondary diagnostics，
不用于筛选 episode、调整 prompt 或 budget、生成 plan、自适应构造策略，亦不
用于提出确认性机制结论。

In addition to measuring topology-induced behavioral differences, the benchmark
records preregistered, fine-grained observability variables at plan, merge, node,
and evidence levels, including generative rewrite depth, content-to-budget
exposure, merge-partner balance, order-role exposure, and resource usage. These
variables are reconstructed from raw run artifacts and used only as descriptive
secondary diagnostics with episode-clustered uncertainty intervals. They are
never used to select episodes, tune prompts or budgets, generate plans, adapt
construction policies, or produce confirmatory mechanism claims.

本节只规定科学 framing。具体 raw fields、schema、派生公式、访问边界、执行
配置和测试以唯一 Workplan、现有 schemas、metric specification 与 tests 为
execution source of truth，不另行建立并行 observability 文档或对象体系。

---

# 10. 评价指标与统计协议

核心评价保持四项，避免冗余指标堆叠：

$$
\boxed{
Q_{mean},\quad
Q_{worst},\quad
\Delta Q_{plan}^{cal},\quad
C_{life}
}
$$

## 10.1 Mean quality

$$
Q_{mean}(B)=\frac{1}{|\Pi|}\sum_{T\in\Pi}Q_T(B).
$$

## 10.2 Worst tested-plan quality

$$
Q_{worst}(B)=\min_{T\in\Pi}Q_T(B).
$$

必须称为 **worst tested-plan**，不宣称覆盖全部可能计划。

## 10.3 Null-calibrated plan effect

原始极差：

$$
D_{plan}(B)=\max_TQ_T(B)-\min_TQ_T(B).
$$

但该值在零假设下也可能因 seed noise 为正。因此同时运行同一计划的 repeated trials，得到 within-plan null distribution $D_{seed}$。

正式统计使用：

- 一个主检验：episode/question-level paired permutation test 或合适的 mixed-effects model；
- 一个 robustness check：clustered paired bootstrap；
- plan、budget 及 plan×budget 为固定效应，episode 为随机效应；
- 正式实验每条件建议不少于 5 个 repeated runs，pilot 可先使用 3 个。

报告：

- effect size 与置信区间；
- $D_{plan}$ 相对 null band 的位置；
- 预注册的 minimum effect of interest $\delta_{min}$。

$\delta_{min}$ 必须在 calibration split 上依据任务方差和实际意义确定，不能根据 test 结果事后选择。

## 10.4 Lifecycle cost

$$
C_{life}=C_{construct}+C_{query}.
$$

Construction 至少记录：

- constructor input/output tokens；
- LLM calls；
- merge/update calls；
- embedding calls；
- final memory tokens；
- deployment state size（shared source state 与 experiment artifact footprint
  分开报告）。

Query 至少记录：

- retrieval context tokens；
- final prompt tokens；
- answer generation tokens；
- query calls；
- 所有 benchmark queries 的累计成本。

Lifecycle cost remains a separate primary result. The benchmark additionally
records accepted-path and observed operational resource work, provider/local
token provenance, stage wall-clock, deployment state, shared source state and
artifact footprint. These observability variables are descriptive and are not
collapsed into a composite score or used to replace `Task Quality` or `Plan
Robustness`; exact field names and rebuild formulas are frozen in the Workplan
and metric specification.

Mechanism diagnostics (rewrite depth, content-to-budget pressure, merge-partner
balance and order-role exposure) are secondary descriptive variables with
episode-clustered uncertainty intervals only. They do not create a new primary
outcome or a confirmatory mechanism test.

最终结果按 budget 绘制 quality–robustness–cost Pareto/frontier，不强行合并为未经验证的单一总分。

---

# 11. Baseline 设计

## Tier 0：归因与边界

### Full Context

诊断 context saturation 与高查询成本边界。

### Raw-RAG

对 immutable raw evidence 做统一检索，不进行 generative consolidation。

### Budget-Matched Retain

在与 consolidated view 相同的 query token budget 下，选择并原样保留 atomic raw notes/evidence，不生成摘要。这是必须 baseline，用于区分 compression coverage 与 generative replacement 的作用。

### Static One-Shot Consolidation

所有 evidence 可见后一次性生成最终 view，隔离 incremental path effect。

### Set-State + Deterministic Render

content-addressed atomic units 使用 set union 保存，query 时通过固定 deterministic render 在预算内选择。该 baseline代表高路径收敛、低跨记录语义组合的端点。

## Tier 1：规范计划与在线简单答案

### Eager Left-Deep

标准流式更新。

### Offline Canonical Balanced

固定叶上的规范平衡树。

### Online Canonical Balanced Compaction

未知流长、prefix-queryable 的 level-based 平衡归约。

### Periodic Reconstruction

周期性从 immutable source 重建。

### Right-Deep Diagnostic

仅在 interval-aware contract 下用于机制分析。

## Tier 2：强相关现有方法

### LightMem

效率型 STM aggregation 与 sleep-time update baseline。

### TrustMem

transition-level coverage、preservation 和 faithfulness verifier baseline。

### MemTxn

仅在 knowledge-update / FactConsolidation 等适用 track 上测试 source-supported update、temporal resolution 和 recovery。若无可复现官方实现，则明确标记为 component-level adaptation，不伪称完整复现。

### TOKI-style structured operator

仅用于结构化事实冲突 track，不泛化到自由文本技能 consolidation。

### Retain-or-Consolidate / OAS

作为预算条件下 representation/operator selection baseline；重点比较 matched candidates 与 matched answer budget。

## Related-work analogy，而非直接 baseline

[Cache Merging as a Convergent Replicated State](https://arxiv.org/abs/2607.01308) 证明了 latent fragment set + deterministic render 可以实现精确 permutation invariance 和 CvRDT 属性，但其状态合并不进行有损文本语义重写，且论文明确指出 $k>2$ 时 merge 能 transport/colocate traces，却不能自行完成组合。因此它提供“收敛端点”和 state/render 分离的强类比，不直接解决本研究的 generative semantic reduction-tree 问题。

---

# 12. Benchmark 有效性与研究 Gate

本研究不单独建设 motivation experiment。Baseline 结果直接决定研究是否继续。

## G0：协议与控制成立

必须完成：

- merge contract；
- fixed leaf cache；
- offline/online plan generator；
- budget scan；
- unified evaluator；
- cost logger；
- seed/repeat control；
- Q_dev/Q_test leakage guard。

## G1：存在 null-calibrated topology effect

在至少一个 tight/transition budget 和至少一个主数据集上：

- fixed-leaf plans 的行为差异显著超出 within-plan null；
- 差异影响原任务质量或 operation-level correctness；
- 差异不是仅体现在 memory 文本。

若不成立，停止该方向。

## G2：效应归因于 generative materialization

Raw-RAG、budget-matched retention、set+render 和 Static One-Shot 的 plan variance 应显著低于递归 generative merge，或表现出不同错误模式。否则效应可能来自 answer/retrieval noise，而非 consolidation path。

## G3：简单 canonical tree 尚未完全解决

必须首先运行 offline 与 online canonical balanced baselines。

若 online canonical balanced 在合理成本下同时：

- 关闭主要 plan gap；
- 达到最优或近最优 mean/worst quality；
- 满足 prefix-queryability；

则复杂方法路线停止或转向 analysis/engineering paper。

## G4：存在非平凡预算条件下的质量—鲁棒性—成本空间

G4 不要求 consolidation 在所有预算下显著优于 retention。合理前提是至少存在一个实际预算区间，使某种 compact/generative view：

$$
Q_{compact}\ge Q_{retain}-\epsilon
$$

并且至少满足其一：

- 更低 query/lifecycle cost；
- 在相同 budget 下覆盖更多必要 evidence；
- 更高 multi-evidence reasoning quality。

同时，现有 incremental plan 在该区间仍有明显 topology variance 或 worst-plan loss。

这与 Retain-or-Consolidate 的结论一致：紧预算下 consolidation 可能显著占优，松预算下其优势可能消失，甚至仅达到与 retention 统计上无差异。

## G5：现有可靠性方法仍未关闭方法空间

TrustMem、MemTxn、OAS、periodic reconstruction、set+render 和 provenance-preserving baseline 不能同时获得：

- 高 mean quality；
- 高 worst tested-plan quality；
- 低 null-calibrated plan effect；
- 低 lifecycle cost。

只有 G1–G5 成立，才进入最终方法设计。

---

# 13. 方法空间的组织原则

不再罗列互不相关的七种机制，而围绕一条主轴组织：

$$
\text{Exact path convergence}
\longleftrightarrow
\text{Generative semantic composition}.
$$

## 13.1 收敛端

- immutable/content-addressed evidence；
- set union state；
- deterministic render；
- fixed canonical plan；
- non-destructive versioning。

优势：可重放、可审计、路径稳定。  
限制：紧预算下覆盖不足，缺乏跨 evidence 抽象和组合。

## 13.2 组合端

- free-form merge；
- abstract / rewrite；
- conflict interpretation；
- cross-note synthesis。

优势：更高压缩率和组合能力。  
限制：路径依赖、遗漏、漂移和无来源生成。

## 13.3 潜在中间方法

最终方法应根据 baseline 错误分布选择，候选包括：

- canonical structured intermediate representation；
- source-grounded generative merge；
- bounded-depth online compaction；
- deterministic fact layer + generative schema layer；
- depth-triggered rebuild/reconciliation；
- candidate merge verification；
- divergence-triggered repair；
- plan-consistency training。

方法必须解释自己在上述轴上的位置，以及相较两个端点增加了什么能力、付出了什么成本。

---

# 14. 预期贡献

若研究成功，论文贡献应为：

## C1：Formal Characterization

不仅提出“计划鲁棒性”定义，而是：

- 定义 ordered interval-aware generative merge；
- 将 fixed-leaf tree invariance 与行为结合性联系起来；
- 区分 exact set-state convergence 与 generative semantic composition；
- 建立 rewrite-depth profile 等可证伪机制变量。

不强行提出未经证明的不可能性定理。

## C2：Budget-Conditioned Evaluation Protocol

构建统一 harness：

- fixed-leaf offline topology；
- online prefix-queryable compaction；
- budget scan；
- matched-budget retention；
- seed-null calibration；
- mean/worst quality；
- lifecycle cost；
- operation-level audit。

## C3：Online Plan-Robust Materialization Method

在简单 canonical online balanced 尚不足时，提出一种方法：

- 提高 mean 和 worst tested-plan quality；
- 降低 topology-induced variance；
- 保留 source grounding；
- 支持任意 prefix 查询；
- 成本低于频繁 full reconstruction；
- 在紧/过渡预算下优于或不劣于 matched-budget retention。

只有 C1+C2 而无有效 C3，工作应按 analysis/benchmark 形态重新定位；不能包装为完整方法论文。

---

# 15. 实施顺序

## Phase 0：设计阻塞项

在正式 harness 前完成：

1. 冻结 ordered interval-aware merge contract；
2. 冻结 online prefix-queryability 语义；
3. 实现 offline balanced 与 online canonical balanced 的计划定义；
4. 冻结 budget scan 与 leaf caching 规则。

## Phase 1：最小 feasibility pilot

目的不是论文 motivation，而是避免在无信号问题上投入完整工程。

建议初始设置：

- 数据：FactConsolidation-SH + LongMemEval knowledge-update/temporal 的小型 calibration 子集；
- 至少覆盖约 100 个 query-level evaluation units，而不是只看单个 conversation；
- $k=8$ fixed leaves；
- plans：left-deep / balanced / right-deep diagnostic；
- repeated runs：pilot 每条件 3 次；
- budgets：一个 tight、一个 loose，依据 retention-fit calibration 选择；
- 逐节点容量硬约束；
- leaf bytes 跨 plans 完全复用。

Pilot 判据：

- 在 tight/transition budget 下，plan effect 超出同计划 repeated-run null；
- effect size 达到预注册的 $\delta_{min}$；
- 错误出现在任务行为而非只在 memory wording；
- 若 online canonical balanced 已在近似成本下关闭主要差距，则进入 analysis/pivot 分支，不继续设计复杂方法。

不预先承诺具体调用量或美元成本；answer calls 取决于每个 episode 的 query 数，不能仅由 tree 数量推导。

## Phase 2：正式 Benchmark Harness

完成：

- schema；
- leaf cache；
- plan generator；
- online forest/view semantics；
- evaluator；
- cost logger；
- statistical analysis；
- leakage guard。

## Phase 3：Baseline

先运行低成本关键 baselines：

1. Full Context；
2. Raw-RAG；
3. Budget-Matched Retain；
4. Set-State + Deterministic Render；
5. Static One-Shot；
6. Eager Left-Deep；
7. Offline Balanced；
8. Online Canonical Balanced；
9. Periodic Reconstruction。

再接入 TrustMem、LightMem、MemTxn/OAS 等强方法。

## Phase 4：错误诊断与方法选择

围绕：

- rewrite depth；
- evidence position；
- temporal conflict；
- coverage/replacement；
- provenance loss；
- online compaction state；

决定方法，而不是预先选定。

## Phase 5：最终实验与论文

扩展至：

- 多数据集；
- 多 constructor/backbone；
- 多 budget；
- 多 seeds；
- system cost；
- 消融与案例分析。

---

# 16. 停止与转向条件

出现以下任一情况时，应停止或重新定义方向：

1. fixed-leaf topology effect 不超过 repeated-run null；
2. 差异只存在于 memory 文本，不影响任务行为；
3. matched-budget Retain / Raw-RAG 在所有合理预算下同时具有更低 lifecycle cost 和更高质量；
4. Static One-Shot、online canonical balanced 或简单 periodic reconstruction 已以较低成本解决；
5. balanced 在全部条件下最优，且 online balanced 能自然部署，则转 analysis/engineering，不硬造 C3；
6. TrustMem、MemTxn、OAS 或其他现有方法已关闭主要差距；
7. 最终方法只能以数倍成本换取轻微鲁棒性改善；
8. 结果只在单一数据集、单一模型或极端预算成立；
9. 所谓 depth effect 在控制 budget、position 和 evidence type 后消失；
10. 无法构造严格 fixed-leaf、matched-budget、Q_dev/Q_test 隔离的评测协议。

---

# 17. 一段式最终定义

本研究将长期 Agent Memory 中的 consolidated memory 视为 immutable raw evidence 上的有损语义物化视图。已有工作已经证明连续 LLM consolidation 会退化，且不同 grouping/update regime 会产生不同结果；本研究不重复这一发现，而是通过固定叶级表示、固定 evidence 顺序和预算扫描，隔离归约拓扑本身对下游行为的影响。我们定义有序、区间感知的 generative merge，比较 eager left-deep、offline/online canonical balanced、periodic reconstruction、matched-budget retention 和 exact set-state render，并将问题组织为“路径收敛性—语义组合能力”的权衡。最终目标是在任意 prefix 可查询的在线 memory 中，获得更高 mean/worst task quality、更低 null-calibrated topology variance 和低于频繁全量重建的生命周期成本；若简单 online balanced 已足够，则明确停止复杂方法路线。

---

# 18. 关键参考文献

1. Zhang et al. [Useful Memories Become Faulty When Continuously Updated by LLMs](https://arxiv.org/abs/2605.12978), 2026.
2. Fang et al. [LightMem: Lightweight and Efficient Memory-Augmented Generation](https://arxiv.org/abs/2510.18866), ICLR 2026.
3. Kang et al. [Retain or Consolidate? Budget-Dependent Operator Selection for Language Agent Memory](https://arxiv.org/abs/2607.17545), 2026.
4. Wang. [MemDelta: Controlled Baselines and Hidden Confounds in Agent Memory Evaluation](https://arxiv.org/abs/2606.29914), 2026.
5. Baquero and Brito. [Cache Merging as a Convergent Replicated State for Multi-Agent Latent Reasoning](https://arxiv.org/abs/2607.01308), 2026.
6. Yang et al. [TRUSTMEM: Learning Trustworthy Memory Consolidation for LLM Agents with Long-Term Memory](https://arxiv.org/abs/2606.25161), 2026.
7. Cui et al. [MemTxn: A Transaction Boundary for Source-Supported Updates and Complete-State Recovery in Agent Memory](https://arxiv.org/abs/2607.27834), 2026.
8. Wang. [TOKI: A Bitemporal Operator Algebra for Contradiction Resolution in LLM-Agent Persistent Memory](https://arxiv.org/abs/2606.06240), 2026.
9. Hu et al. [Evaluating Memory in LLM Agents via Incremental Multi-Turn Interactions](https://arxiv.org/abs/2507.05257), 2025.
10. Chen et al. [HaluMem: Evaluating Hallucinations in Memory Systems of Agents](https://arxiv.org/abs/2511.03506), 2025.
11. Jiang et al. [Anatomy of Agentic Memory](https://arxiv.org/abs/2602.19320), 2026.
