from typing import Any, Callable, Dict, List


def _format_messages(messages: List[Dict[str, Any]]) -> str:
    if not messages:
        return "无"
    return "\n".join(f"{item.get('role', 'unknown')}: {item.get('content', '')}" for item in messages)


def _format_long_memory(memory: Dict[str, Any]) -> str:
    items = memory.get("results", [])
    if not items:
        return "无"
    rows = []
    for item in items:
        rows.append(
            f"- task_id={item.get('task_id')} platform={item.get('platform')} "
            f"keyword={item.get('keyword')} summary={item.get('summary', '')}"
        )
    return "\n".join(rows)


def build_decision_prompt(
    query: str,
    short_memory: List[Dict[str, Any]],
    long_memory: Dict[str, Any],
    tools: Dict[str, Callable],
) -> str:
    tool_lines = []
    for name, func in tools.items():
        description = getattr(getattr(func, "__func__", func), "_description", "")
        tool_lines.append(f"- {name}: {description}")
    return f"""你是舆情分析系统的轻量级单Agent，必须按 ReAct 方式决策。

可用工具:
{chr(10).join(tool_lines)}

短期记忆:
{_format_messages(short_memory)}

长期记忆:
{_format_long_memory(long_memory)}

用户问题:
{query}

请只输出 JSON，不要输出 Markdown 代码块：
{{
  "thought": "你的简短思考",
  "action": "tool名称 或 direct_answer",
  "parameters": {{}}
}}
"""


def build_answer_prompt(
    query: str,
    short_memory: List[Dict[str, Any]],
    long_memory: Dict[str, Any],
    used_tool: str,
    observation: Dict[str, Any],
) -> str:
    return f"""请基于以下信息回答用户，使用中文，结论明确，必要时分点说明。

用户问题:
{query}

短期记忆:
{_format_messages(short_memory)}

长期记忆:
{_format_long_memory(long_memory)}

本轮使用工具:
{used_tool}

工具观察结果:
{observation}
"""
