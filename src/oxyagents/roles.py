"""多智能体角色定义（OxyGent）。

设计原则（见 docs/方案整合.md）：
1. **5 个角色上限**。角色多于 5 个时，调框架的时间会吃掉做交互研究的时间。
2. **职责互斥**。每个 Agent 只回答一类问题，便于在界面上把结论归属到具体角色。
3. **校验与生成分离**。校验 Agent 不产出答案，只质疑——这既是质量手段，也是 C 条件里
   「分歧」区块的数据来源。这一条借鉴了开源方案 OG-A-MAS 的 Auditor / Reviewer 分层。
"""

from __future__ import annotations

#: 主控 Agent
MASTER = "master_agent"

#: 参与协作的专家 Agent（顺序即展示顺序）
EXPERTS: list[str] = ["search_agent", "reader_agent", "code_agent", "verify_agent"]

PROMPTS: dict[str, str] = {
    MASTER: (
        "你是多智能体团队的协调者。给你一个问题和若干专家的结论、以及校验者的质疑，"
        "你需要：1) 判断哪个结论可信；2) 如果专家之间存在冲突，说明你选择其中一方的理由；"
        "3) 严格按题目要求的格式输出最终答案，不要输出解释。"
        "如果题目要求『仅输出数字』，就只输出数字。"
    ),
    "search_agent": (
        "你负责定位信息源。给定一个问题，你要判断需要用哪类来源回答（网页、GitHub、"
        "商品详情页、官方文档、公开数据集），并给出你找到的关键事实与来源 URL。"
        "如果无法访问网络，明确说『无法获取来源』，不要编造。"
    ),
    "reader_agent": (
        "你负责从附件中抽取事实。附件可能是 PDF、PPTX、XLSX、图片、音频或视频。"
        "先列出文件结构，再定位与问题相关的页/帧/单元格，最后给出精确摘录。"
        "不确定的数值必须标注为不确定。"
    ),
    "code_agent": (
        "你负责计算与核对。用 Python 把问题转化为可执行代码，运行后给出结果。"
        "涉及单位、进制、日期、矩阵顺序时必须显式写出假设。"
    ),
    "verify_agent": (
        "你是校验者，不产出答案。你要检查三件事："
        "1) 候选答案是否满足题目中的全部约束（格式、单位、取值范围）；"
        "2) 推理链里有没有跳步、来源缺失或自相矛盾；"
        "3) 最不确定的是哪一步。"
        "如果你认为候选答案有错，直接指出错在哪一步以及你认为正确的值。"
    ),
}


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

    temperature 默认 0.0：实验要求可复现，随机性只应来自模型本身而非采样参数。
    enable_web=True 时挂载浏览器/检索工具；离线实验建议关闭，改用缓存快照。
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

    tools = {
        "reader_agent": ["file_tools"],
        "code_agent": ["math_tools", "python_tools"],
        "search_agent": ["search_tools"] if enable_web else [],
        "verify_agent": [],
        MASTER: [],
    }

    for tool_group in ("file_tools", "math_tools", "python_tools"):
        if hasattr(preset_tools, tool_group):
            space.append(getattr(preset_tools, tool_group))

    for name in [*EXPERTS, MASTER]:
        kwargs = {
            "name": name,
            "desc": PROMPTS[name].split("。")[0],
            "prompt": PROMPTS[name],
            "tools": tools.get(name, []),
        }
        if name == MASTER:
            kwargs.update({"is_master": True, "sub_agents": list(EXPERTS)})
        space.append(oxy.ReActAgent(**kwargs))

    return space
