import json
from typing import Any, Callable, Dict, List


def _format_messages(messages: List[Dict[str, Any]]) -> str:
    if not messages:
        return "无"
    return "\n".join(
        f"{item.get('role', 'unknown')}: {item.get('content', '')}" for item in messages
    )


def _format_long_memory(memory: Dict[str, Any]) -> str:
    items = memory.get("results", [])
    if not items:
        return "无"
    rows = []
    for item in items:
        content = item.get("summary") or item.get("content") or ""
        rows.append(
            f"- task_id={item.get('task_id')} platform={item.get('platform')} "
            f"keyword={item.get('keyword')} content={content}"
        )
    return "\n".join(rows)


def _format_tools(tools: Dict[str, Callable]) -> str:
    rows = []
    for name, func in tools.items():
        description = getattr(getattr(func, "__func__", func), "_description", "")
        parameters = getattr(getattr(func, "__func__", func), "_parameters_schema", {})
        risk_level = getattr(getattr(func, "__func__", func), "_risk_level", "low")
        rows.append(
            f"- {name}: {description}\n"
            f"  risk_level={risk_level}\n"
            f"  parameters={json.dumps(parameters, ensure_ascii=False)}"
        )
    return "\n".join(rows)


def _format_trace(trace: List[Dict[str, Any]]) -> str:
    if not trace:
        return "无"
    rows = []
    for step in trace:
        rows.append(
            f"- step={step.get('step')} action={step.get('action')} "
            f"status={step.get('status')} summary={step.get('observation_summary', '')}"
        )
    return "\n".join(rows)


def build_decision_prompt(
    query: str,
    short_memory: List[Dict[str, Any]],
    long_memory: Dict[str, Any],
    tools: Dict[str, Callable],
    trace: List[Dict[str, Any]] | None = None,
    step: int = 1,
    max_steps: int = 3,
) -> str:
    return f"""你是舆情分析系统中的多工具 Agent，需要按 ReAct 思路决定下一步动作。

你可以直接回答，也可以选择一个工具继续获取信息。除非用户明确要求实时采集，否则优先使用已有任务数据和长期记忆。
实时采集类工具风险较高，只有在用户明确要求“现在抓取/实时采集/重新采集”时才使用。

当前步数: {step}/{max_steps}

可用工具:
{_format_tools(tools)}

短期记忆:
{_format_messages(short_memory)}

长期记忆:
{_format_long_memory(long_memory)}

已完成步骤:
{_format_trace(trace or [])}

用户问题:
{query}

请只输出 JSON，不要输出 Markdown 代码块。格式如下:
{{
  "thought": "简短说明为什么选择这个动作",
  "action": "工具名或 direct_answer",
  "parameters": {{}},
  "final": false
}}

如果已有信息足够回答，请使用 action=direct_answer，并将 final 设为 true。
"""


def build_answer_prompt(
    query: str,
    short_memory: List[Dict[str, Any]],
    long_memory: Dict[str, Any],
    used_tool: str,
    observation: Dict[str, Any],
    trace: List[Dict[str, Any]] | None = None,
) -> str:
    return f"""请基于以下信息回答用户，使用中文，结论明确，必要时分点说明。
如果工具调用失败，要说明失败原因，并给出下一步可操作建议。

用户问题:
{query}

短期记忆:
{_format_messages(short_memory)}

长期记忆:
{_format_long_memory(long_memory)}

本轮主要使用工具:
{used_tool}

工具观察结果:
{json.dumps(observation, ensure_ascii=False, default=str)}

Agent 执行轨迹:
{_format_trace(trace or [])}
"""
