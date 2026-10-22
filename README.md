# 一个 AI 还是一个 AI 团队？

**多智能体协作可视化对用户决策与监督的影响** —— 人机交互课程项目

基于 2025 CCF BDCI「京东多智能体挑战赛」与京东开源框架 [OxyGent](https://github.com/jd-opensource/OxyGent)，研究多智能体系统的**协作过程可见性**如何影响用户的决策质量与监督能力。

> 本项目**不参加比赛**，只借用赛题方向与框架。

## 研究设计

场景：7000 元预算的计算机专业学生买笔记本（写代码、偶尔跑模型、需通勤携带、用 4 年）。

三种条件，逐级加入协作与人的参与：

| 条件 | 谁在完成任务 | 界面 | 作用 |
|---|---|---|---|
| A 单个 Agent | 1 个 Agent | 只显示最终建议 | 基线 |
| B 多个 Agent | 多个 Agent 后台协作 | 只显示最终建议 | 隔离多 Agent 协作本身的增益 |
| C 多个 Agent + 人 | 多个 Agent + 用户 | 显示角色、证据、分歧，并在关键节点请求确认与裁决 | 检验把人放进协作回路的效果 |

**B → C 只差"人在不在场"**：C 复用 B 的同一次多 Agent 运行结果，Agent 数量、输入、结论完全一致。

假设：**H1** B 优于 A 但未必提升错误发现；**H2** C 提升错误发现与纠错；**H3** C 增加时间与认知负荷；**H4** 人裁决错误时，人的参与可能反而降低成功率。

### C 条件的三类协作点

| 类型 | 触发时机 |
|---|---|
| `confirm` 确认 | 主控准备定稿前：「准备推荐 X，是否采纳？」 |
| `arbitrate` 裁决 | 两个 Agent 结论冲突时，并列双方主张请用户选边 |
| `augment` 追加约束 | 用户主动收紧/放宽条件后重新给建议 |

## 一分钟跑起来

```bash
# 零依赖，不需要 API key
python3 -m src.experiment.server --port 8000
#   打开 http://localhost:8000/?pid=P01&task=DEMO-ERR&cond=C
#   DEMO-OK  = 系统答对（推荐 磐石 T15）
#   DEMO-ERR = 系统答错（推荐 云舟 A16，其内存实际只有 8GB）
#   用 cond=C 可以看到协作点：系统会把「A16 内存到底多少」的分歧交给你裁决
```

`DEMO-ERR` 里可以完整体验「展开证据 → 标记某步有误 → 换成正确机型」的测量流程。

## 标准答案怎么来

买笔记本本身没有客观对错，所以本项目建了一个**教学用模拟商品库**（8 款虚构机型，明确声明非真实商品）：

1. 每款机型有 `listed`（商品页标称）与 `actual`（实际）两套参数，不一致的即「陷阱机型」。
2. 每个任务给定预算与硬约束，由 `scripts/build_taskset.py` 用 `actual` 值求解，**要求恰好 1 个解**，否则报错退出。

于是"正确"可判定：用户是否选中唯一满足全部硬约束的机型。而系统若采信标称值，就会推荐违反约束的机型——**错误是自然产生的，不是人为植入的**。

8 个任务里有 3 类难点：参数不符（云舟 A16 标称 16GB 实为 8GB）、过期价格（磐石 T15 标称 5299 实为 5999）、以及一个**无解任务**（T08：预算 5000 + 独显 + ≤2kg，正确答案是"无合适机型"）。

## 目录

```
├── 计划书.md                    研究动机、学术研究、方案与实验设计（与 PPT 四部分对应）
├── docs/方案整合.md              外部调研吸收了什么、排除了什么、效度基础怎么补的
├── taskset/
│   ├── catalog.json             模拟商品库（listed + actual + 陷阱标注）
│   ├── decision_tasks.json      8 个任务的约束定义
│   └── experiment_tasks.json    生成结果（金标 + 约束文本）
├── scripts/
│   ├── build_taskset.py         约束求解出金标，校验唯一性
│   └── make_demo_fixtures.py    生成演示数据（人工构造，非真实运行结果）
├── src/
│   ├── schema.py                Session 归一化结构 + 校验 + 判分
│   ├── adapters/                OxyGent trace → Session
│   ├── oxyagents/               5 角色多智能体流水线（需 API key）
│   └── experiment/server.py     零依赖实验服务端（托管界面 + 判分 + 记录日志）
├── web/                         三条件实验界面（原生 JS）
├── fixtures/                    会话数据；sample.json 为演示数据
└── data/                        原始数据与日志（gitignore）
```

## 系统架构

```
主控 Agent ── 汇总各方结论 / 处理分歧 / 给出建议
   ├── 检索 Agent     按硬约束初筛候选机型
   ├── 性能 Agent     只判断 CPU / 显卡是否够用（不看价格）
   ├── 成本 Agent     只核对预算与性价比（识别过期价格）
   └── 风险 Agent     只挖风险（参数不符 / 差评 / 售后）
```

性能 Agent 推荐、风险 Agent 挖坑——这个刻意的张力就是 C 条件「分歧」区块的数据来源。

## 状态

| 阶段 | 状态 |
|---|---|
| 商品库 + 8 个任务 + 金标唯一性校验 | ✅ 完成 |
| 三条件界面 + 行为日志 + 判分链路 | ✅ 完成 |
| OxyGent trace → Session 适配 | ✅ 完成（已在真实 trace 验证） |
| 多 Agent 流水线 | ⚠️ 代码完成，未跑过（**缺 LLM API key**） |
| 真实 fixture 生成 | ⬜ 待 API key |
| 用户实验 | ⬜ |

生成真实 fixture：

```bash
pip install -r requirements.txt
cp .env.example .env          # 填 DEFAULT_LLM_API_KEY
python3 -m src.oxyagents.make_fixtures --dry-run
python3 -m src.oxyagents.make_fixtures
```

## 说明

- `taskset/catalog.json` 的机型与参数均为**虚构**，报告与论文中不得据此对真实商品下结论。
- `fixtures/sample.json` 是人工构造的演示数据，仅用于跑通界面，不得作为实验数据分析。
- 不引用任何第三方参赛仓库宣称的准确率数字。
