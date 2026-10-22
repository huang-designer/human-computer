# 一个 AI 还是一个 AI 团队？

**多智能体协作可视化对用户审核与监督的影响** —— 人机交互课程项目

基于 2025 CCF BDCI「京东多智能体挑战赛」的任务集与京东开源框架 [OxyGent](https://github.com/jd-opensource/OxyGent)，研究多智能体系统的**协作过程可见性**如何影响用户的审核与监督能力。

> 本项目**不参加比赛**，只借用赛题的真实任务数据与框架。

## 一分钟了解

赛题是 GAIA 式基准：给一个复杂问题和附件，产出**唯一确定答案**，按完全匹配准确率计分。这意味着一件事——**标准答案免费且客观**。

于是研究问题可以变得很干净：**当答案质量被固定时，把协作过程给用户看，能不能帮用户发现错误？**

三种条件，底层 Agent 完全相同，只改界面：

| 条件 | 界面 | 作用 |
|---|---|---|
| A 单 Agent | 只显示最终答案 | 基线 |
| B 隐藏式多 Agent | 后台协作，只显示最终答案 | 隔离多 Agent 的算法增益 |
| C 可见式多 Agent | 显示角色分工、证据、分歧、执行时间线 | 检验透明度对监督的作用 |

**B 与 C 的数据除 `condition` 字段外逐字节相同** —— 这是实验效度的基础。

## 快速开始

```bash
# 1. 跑起来看界面（零依赖，不需要 API key）
python3 -m src.experiment.server --port 8000
#   打开 http://localhost:8000/?pid=P01&task=demo-err&cond=C
#   demo-ok  = 系统答对
#   demo-err = 系统答错（可体验「发现错误 → 标记有误 → 改答案」全流程）

# 2. 拉取赛题数据并重新生成实验任务集
python3 scripts/fetch_dataset.py
python3 scripts/analyze_dataset.py      # → data/dataset_report.md
python3 scripts/build_taskset.py        # → taskset/experiment_tasks.json

# 3. 生成真实 fixture（需要 LLM API key）
pip install -r requirements.txt
cp .env.example .env                    # 填入 DEFAULT_LLM_API_KEY 等
python3 -m src.oxyagents.make_fixtures --limit 3 --dry-run   # 先看会跑什么
python3 -m src.oxyagents.make_fixtures --limit 3             # 真跑
```

## 目录

```
├── 计划书.md                  研究问题、假设、实验设计、里程碑、风险
├── docs/方案整合.md            来源整合：赛题数据 / 两个开源仓库 / OxyGent 能力的取舍
├── taskset/
│   ├── selection.json         15 条任务的选型与人工标注（类别、预期错误）
│   └── experiment_tasks.json  生成结果（含标准答案）
├── scripts/
│   ├── fetch_dataset.py       拉取验证集/测试集
│   ├── analyze_dataset.py     结构分析 → data/dataset_report.md
│   ├── build_taskset.py       合并标注 → 实验任务集
│   └── make_demo_fixtures.py  生成演示数据（人工构造，非真实运行结果）
├── src/
│   ├── schema.py              Session 归一化结构 + 校验
│   ├── adapters/              OxyGent trace → Session
│   ├── oxyagents/             5 角色多智能体流水线（需 API key）
│   └── experiment/server.py   零依赖实验服务端（托管界面 + 记录日志）
├── web/                       三条件实验界面（原生 JS）
├── fixtures/                  会话数据；sample.json 为演示数据
└── data/                      原始数据与日志（gitignore）
```

## 系统架构

```
master_agent  ── 分配 / 汇总 / 处理分歧 / 输出
   ├── search_agent   定位信息源
   ├── reader_agent   从附件抽取事实
   ├── code_agent     计算与核对
   └── verify_agent   只质疑，不产出答案
```

校验与生成分离是刻意的：既提升质量，也直接产出 C 条件里「分歧」区块的数据。

## 状态

| 阶段 | 状态 |
|---|---|
| 赛题真实形态核查（100 条验证集） | ✅ 完成 |
| 开源方案调研（3 个仓库） | ✅ 完成 |
| 实验任务集（15 条） | ✅ 完成 |
| 三条件界面 + 行为日志 | ✅ 完成 |
| OxyGent trace → Session 适配 | ✅ 完成（已在真实 trace 验证） |
| 多 Agent 流水线 | ⚠️ 代码完成，未跑过（**缺 LLM API key**） |
| 真实 fixture 生成 | ⬜ 待 API key |
| 用户实验 | ⬜ |

## 说明

- `fixtures/sample.json` 是**人工构造**的演示数据，仅用于跑通界面，不得作为实验数据分析。
- 赛题数据版权归赛方，经第三方仓库（MIT）获取，仅用于课程研究，不再分发原始附件。
- 不引用任何第三方仓库宣称的准确率数字（其文档中的 60–70% 与其提交结果不符）。
