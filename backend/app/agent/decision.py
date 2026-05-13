import inspect
import json
import re
from typing import Any, Callable, Dict


PLATFORM_ALIASES = {
    "weibo": ("weibo", "微博"),
    "douyin": ("douyin", "抖音"),
    "bilibili": ("bilibili", "b站", "B站"),
}


def parse_llm_decision(raw_text: str, tools: Dict[str, Callable], query: str) -> Dict[str, Any]:
    default = {
        "thought": "LLM 决策解析失败，默认直接回答。",
        "action": "direct_answer",
        "parameters": {},
    }
    if not raw_text:
        return default
    for text in _candidate_json_texts(raw_text):
        try:
            data = json.loads(text)
        except Exception:
            continue
        action = _normalize_action(data.get("action"), tools)
        params = repair_parameters(action, data.get("parameters"), tools, query)
        return {
            "thought": str(data.get("thought", ""))[:200],
            "action": action,
            "parameters": params,
        }
    return default


def repair_parameters(
    action: str, params: Any, tools: Dict[str, Callable], query: str
) -> Dict[str, Any]:
    if action == "direct_answer":
        return {}
    params = params if isinstance(params, dict) else {}
    signature = inspect.signature(tools[action])
    repaired: Dict[str, Any] = {}
    for name, parameter in signature.parameters.items():
        if name == "self":
            continue
        value = params.get(name)
        if value in (None, "", {}):
            value = _infer_value(name, action, query, parameter.default)
        repaired[name] = _coerce_value(value, parameter.annotation, parameter.default)
    return repaired


def _candidate_json_texts(raw_text: str):
    match = re.search(r"```json\s*([\s\S]*?)```", raw_text, re.I)
    if match:
        yield match.group(1).strip()
    match = re.search(r"\{[\s\S]*\}", raw_text)
    if match:
        yield match.group(0)
    yield raw_text.strip()


def _normalize_action(action: Any, tools: Dict[str, Callable]) -> str:
    text = str(action or "direct_answer").strip().lower()
    if text in {"answer", "direct", "direct_answer"}:
        return "direct_answer"
    if text in tools:
        return text
    for name in tools:
        if name in text or text in name:
            return name
    return "direct_answer"


def _infer_value(name: str, action: str, query: str, default: Any) -> Any:
    if name == "text":
        return query
    if name == "query":
        return query
    if name == "top_k":
        return default if default is not inspect._empty else 3
    if name == "platform":
        lowered = query.lower()
        for platform, aliases in PLATFORM_ALIASES.items():
            if any(alias.lower() in lowered for alias in aliases):
                return platform
        return "weibo"
    if name == "keyword":
        cleaned = query
        for aliases in PLATFORM_ALIASES.values():
            for word in aliases:
                cleaned = cleaned.replace(word, " ")
        for word in ["分析", "查询", "检索", "主题", "情感", "舆情", "一下", "帮我", "看看"]:
            cleaned = cleaned.replace(word, " ")
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned or query
    return default if default is not inspect._empty else None


def _coerce_value(value: Any, annotation: Any, default: Any) -> Any:
    if value is None and default is not inspect._empty:
        return default
    if annotation is int:
        try:
            return max(1, int(value))
        except Exception:
            return default if default is not inspect._empty else 1
    if annotation is str:
        return str(value or "").strip()
    return value
