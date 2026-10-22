"""多智能体角色定义（OxyGent）——笔记本购买决策场景。

角色与 PPT 第 5 页一致：检索 / 性能 / 成本 / 风险 / 主控。

设计原则：
1. **5 个角色上限**。角色多于 5 个，调框架的时间会吃掉做交互研究的时间。
2. **职责互斥**。性能 Agent 只看性能，成本 Agent 只看预算，这样在 C 条件界面上
   才能把每条结论明确归属到某个角色，用户也才能"定位到是谁说的"。
3. **风险 Agent 与性能 Agent 故意存在张力**：前者挖坑，后者推荐，二者的冲突
   就是 C 条件「分歧」区块的数据来源。
"""

from __future__ import annotations

MASTER = "master_agent"

#: 专家 Agent（顺序即界面展示顺序）
EXPERTS: list[str] = ["retrieval_agent", "performance_agent", "cost_agent", "risk_agent"]

LABELS: dict[str, str] = {
    "retrieval_agent": "检索 Agent",
    "performance_agent": "性能 Agent",
    "cost_agent": "成本 Agent",
    "risk_agent": "风险 Agent",
    MASTER: "主控 Agent",
}

PROMPTS: dict[str, str] = {
    MASTER: (
        "你是多智能体团队的协调者。给你一个购买需求和若干专家的结论，你要："
        "1) 判断哪条结论最符合用户的硬约束；2) 若专家之间存在冲突，说明你采纳哪一方以及理由；"
        "3) 输出最终建议的机型 ID 与 2 句话理由。"
        "如果没有任何机型能满足全部硬约束，必须直接说明「没有机型满足全部条件」，不得推荐违反约束的机型。"
    ),
    "retrieval_agent": (
        "你负责从候选列表中筛选。给定用户约束和候选机型清单，列出满足硬约束的机型，"
        "并指出哪些机型因何被排除。只做筛选，不评判好坏。"
    ),
    "performance_agent": (
        "你只关注性能：CPU、显卡是否满足使用需求（写代码、跑模型训练）。"
        "给出你认为性能最合适的前 2 款机型及理由。不考虑价格。"
    ),
    "cost_agent": (
        "你只关注价格与预算：核对实际售价是否在预算内，计算性价比。"
        "如果商品页价格与当前实际价格不一致，以实际价格为准并明确指出。"
    ),
    "risk_agent": (
        "你只关注风险：查参数与实物是否一致、差评集中在哪、售后渠道是否可靠、"
        "有没有隐藏的成本（扩展坞、更换电池）。逐条列出风险，并说明哪些风险足以否决某款机型。"
    ),
}


def describe_agents() -> list[dict[str, str]]:
    """给界面用的角色说明（与 Session.agents 的 role 字段保持一致）。"""
    roles = {
        "retrieval_agent": "抓取候选机型的价格、参数与评价，按硬约束初筛",
        "performance_agent": "判断性能（CPU / 显卡）是否满足使用需求",
        "cost_agent": "核对预算与性价比，识别过期价格",
        "risk_agent": "收集差评集中点、参数不符与售后风险",
        MASTER: "汇总各方结论、处理分歧、给出最终建议",
    }
    return [{"id": k, "name": LABELS[k], "role": v} for k, v in roles.items()]


def build_oxy_space(
    *,
    llm_name: str = "default_llm",
    api_key: str | None = None,
    base_url: str | None = None,
    model_name: str | None = None,
    temperature: float = 0.0,
    enable_web: bool = False,
) -> list:
    """构造 OxyGent 的 oxy_space。

    temperature 默认 0.0：实验要求可复现。
    enable_web=False 时使用本地商品库（taskset/catalog.json），保证结果可复现。
    """
    import os

    from oxygent import oxy, preset_tools  # 延迟导入：无 oxygent 环境也能 import 本模块

    space: list = [
        oxy.HttpLLM(
            name=llm_name,
            api_key=api_key or os.getenv("DEFAULT_LLM_API_KEY"),
            base_url=base_url or os.getenv("DEFAULT_LLM_BASE_URL"),
            model_name=model_name or os.getenv("DEFAULT_LLM_MODEL_NAME"),
            llm_params={"temperature": temperature},
        )
    ]

    for tool_group in ("file_tools", "math_tools"):
        if hasattr(preset_tools, tool_group):
            space.append(getattr(preset_tools, tool_group))

    for name in [*EXPERTS, MASTER]:
        kwargs = {
            "name": name,
            "desc": PROMPTS[name].split("。")[0],
            "prompt": PROMPTS[name],
            "tools": ["math_tools"] if name == "cost_agent" else [],
        }
        if name == MASTER:
            kwargs.update({"is_master": True, "sub_agents": list(EXPERTS)})
        space.append(oxy.ReActAgent(**kwargs))

    return space
