import logging
import re
from collections import Counter
from typing import Any, Dict, Iterable, List, Optional


logger = logging.getLogger(__name__)


class ErrorHandler:
    _SUMMARY_WORDS = ("总结", "汇总", "概括", "摘要", "归纳")
    _TEXT_FIELDS = ("content", "title", "desc", "description", "text")
    _SUMMARY_STOP_WORDS = {
        "一个",
        "一些",
        "这个",
        "那个",
        "我们",
        "你们",
        "他们",
        "大家",
        "视频",
        "帖子",
        "评论",
        "内容",
        "转发",
        "点赞",
        "关注",
        "搜索",
        "实时",
        "最新",
        "采集",
        "抓取",
        "输出",
        "超过",
        "不超过",
        "总计",
        "关于",
        "这种",
        "真的",
        "感觉",
        "什么",
        "怎么",
        "一下",
        "希望",
        "感谢",
        "谢谢",
        "辛苦",
        "严惩",
        "已经",
        "还是",
        "就是",
        "可以",
        "没有",
        "不是",
        "因为",
        "所以",
        "但是",
        "如果",
        "进行",
        "需要",
    }
    _SUMMARY_THEME_DEFINITIONS = (
        ("强降雨天气", ("暴雨", "大暴雨", "强降雨", "降雨", "大雨", "雨势", "雷暴", "预警", "山洪", "洪水")),
        ("道路积水", ("积水", "内涝", "渍水", "淹水", "水位", "低洼", "排水", "路面积水")),
        ("安全提醒", ("安全", "平安", "涉水", "绕行", "出行", "交通", "封路", "停运", "通行", "注意安全")),
        ("救援处置", ("救援", "消防", "转移", "救助", "抢险", "救灾", "应急", "安置", "处置")),
        ("学生出行", ("学生", "学校", "上学", "放学", "停课", "校车", "孩子", "儿童", "老师")),
        ("城市防汛", ("防汛", "市政", "城管", "部门", "治理", "预案", "排涝", "排水")),
        ("责任追问", ("严惩", "追责", "问责", "责任", "调查", "处罚", "失职")),
        ("民生保障", ("停电", "供水", "物资", "受灾", "群众", "居民", "生活", "家里")),
    )

    @staticmethod
    def build_error_response(
        query: str,
        error: Exception,
        short_memory: list,
        long_memory: dict,
        stage: str,
        used_tool: str = "direct_answer",
        decision_summary: Optional[str] = None,
        agent_trace: Optional[list] = None,
    ) -> Dict[str, Any]:
        error_msg = str(error)

        if "401" in error_msg or "Authentication" in error_msg:
            answer = f"API 认证失败：请检查 API Key 配置是否正确。错误详情：{error_msg}"
        elif "timeout" in error_msg.lower():
            answer = f"请求超时：请检查网络连接后重试。错误详情：{error_msg}"
        elif "connection" in error_msg.lower():
            answer = f"网络连接失败：请检查网络设置。错误详情：{error_msg}"
        else:
            answer = f"Agent 在{stage}处理失败：{error_msg}。请稍后重试。"

        return {
            "answer": answer,
            "used_tool": used_tool,
            "decision_summary": decision_summary or f"{stage}处理失败",
            "observation_summary": error_msg,
            "short_memory_turns": len(short_memory),
            "long_memory_hits": len(long_memory.get("results", [])),
            "tool_observation": {"error": error_msg},
            "agent_trace": agent_trace or [],
        }

    @staticmethod
    def log_tool_error(session_id: str, action: str, error: Exception) -> None:
        logger.warning("Agent 工具调用失败 session=%s action=%s error=%s", session_id, action, error)

    @staticmethod
    def log_llm_error(error: Exception) -> None:
        logger.error("LLM API call failed: %s", error, exc_info=True)

    @staticmethod
    def get_fallback_answer(
        query: str,
        observation: Dict[str, Any],
        generation_error: Optional[Exception] = None,
    ) -> str:
        if (
            "success" in observation
            and "total_posts" in observation
            and "total_comments" in observation
            and observation.get("status") in {"success", "partial_success", "failed"}
        ):
            content_summary = ErrorHandler._build_crawl_content_summary(query, observation)
            if content_summary:
                return content_summary

            platform = observation.get("platform") or "未知平台"
            keyword = observation.get("keyword") or query
            total_posts = observation.get("total_posts", 0)
            total_comments = observation.get("total_comments", 0)
            status_label = {
                "success": "完成",
                "partial_success": "部分完成",
                "failed": "失败",
            }.get(observation.get("status"), observation.get("status"))
            lines = [
                f"实时采集{status_label}：{platform} / {keyword}",
                f"- 帖子：{total_posts} 条",
                f"- 评论：{total_comments} 条",
            ]
            warnings = observation.get("warnings") or []
            if warnings:
                lines.append(f"- 告警：{len(warnings)} 条")
                for warning in warnings[:3]:
                    scope = warning.get("scope") or "runtime"
                    message = warning.get("message") or warning
                    lines.append(f"  - {scope}: {message}")
            if generation_error:
                lines.append("LLM 总结生成超时，已先返回本地采集摘要和结构化结果。")
            return "\n".join(lines)

        error = observation.get("error")
        if error:
            return (
                "我先直接回答：当前工具调用失败，"
                f"原因是“{error}”。请补充更具体的关键词，或先完成相关采集任务后再试。"
            )

        if observation.get("results"):
            count = len(observation["results"])
            return f"已检索到 {count} 条相关信息，但无法生成详细分析。请尝试更具体的问题。"

        return f"已收到你的问题：{query}。当前 Agent 无法访问大模型服务，请检查 API 配置后重试。"

    @staticmethod
    def _build_crawl_content_summary(query: str, observation: Dict[str, Any]) -> str:
        if not any(word in query for word in ErrorHandler._SUMMARY_WORDS):
            return ""

        limit = ErrorHandler._extract_char_limit(query, default=120)
        keyword = str(observation.get("keyword") or "").strip()
        posts = ErrorHandler._extract_texts(observation.get("posts") or [])
        comments = ErrorHandler._extract_texts(observation.get("comments") or [])
        if not posts and not comments:
            return ""

        total_posts = observation.get("total_posts", len(posts))
        total_comments = observation.get("total_comments", len(comments))
        post_themes = ErrorHandler._theme_labels(posts, 3)
        comment_themes = ErrorHandler._theme_labels(comments, 4)
        post_terms = ErrorHandler._top_terms(posts, keyword, 3) if not post_themes else []
        comment_terms = ErrorHandler._top_terms(comments, keyword, 4) if not comment_themes else []

        parts = [f"采集到{total_posts}帖{total_comments}评"]
        if keyword:
            parts.append(f"围绕{keyword}")
        if post_themes:
            parts.append(f"内容集中在{'、'.join(post_themes)}")
        elif post_terms:
            parts.append(f"内容提及{'、'.join(post_terms)}")
        if comment_themes:
            parts.append(f"评论主要关注{'、'.join(comment_themes)}")
        elif comment_terms:
            parts.append(f"评论热词包括{'、'.join(comment_terms)}")

        if len(parts) <= 2:
            snippet = ErrorHandler._best_snippet(posts + comments, keyword)
            if snippet:
                parts.append(snippet)

        return ErrorHandler._fit_limit("，".join(parts) + "。", limit)

    @staticmethod
    def _theme_labels(texts: List[str], limit: int) -> List[str]:
        scores: Counter[str] = Counter()
        for text in texts:
            matched_in_text = set()
            for label, keywords in ErrorHandler._SUMMARY_THEME_DEFINITIONS:
                score = sum(text.count(keyword) for keyword in keywords if keyword in text)
                if score > 0:
                    scores[label] += score
                    matched_in_text.add(label)
            for label in matched_in_text:
                scores[label] += 1
        return [label for label, _ in scores.most_common(limit)]

    @staticmethod
    def _extract_char_limit(query: str, default: int) -> int:
        match = re.search(r"(?:不超过|最多|控制在|限)\s*(\d+)\s*(?:个)?字", query)
        if not match:
            return default
        return max(30, min(int(match.group(1)), 500))

    @staticmethod
    def _extract_texts(items: Iterable[Any]) -> List[str]:
        texts: List[str] = []
        for item in items:
            if isinstance(item, dict):
                text = " ".join(
                    str(item.get(field) or "").strip()
                    for field in ErrorHandler._TEXT_FIELDS
                    if item.get(field)
                )
            else:
                text = str(item or "").strip()
            text = ErrorHandler._clean_text(text)
            if text:
                texts.append(text)
        return texts

    @staticmethod
    def _clean_text(text: str) -> str:
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"https?://\S+", " ", text)
        text = re.sub(r"#([^#\s]{1,30})#", r"\1", text)
        text = re.sub(r"@\S+", " ", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    @staticmethod
    def _top_terms(texts: List[str], keyword: str, limit: int) -> List[str]:
        tokens: List[str] = []
        for text in texts:
            tokens.extend(ErrorHandler._tokenize(text))
        keyword_parts = set(ErrorHandler._tokenize(keyword)) | {keyword}
        counter = Counter(
            token
            for token in tokens
            if token
            and token not in ErrorHandler._SUMMARY_STOP_WORDS
            and token not in keyword_parts
            and not token.isdigit()
        )
        return [token for token, _ in counter.most_common(limit)]

    @staticmethod
    def _tokenize(text: str) -> List[str]:
        try:
            import jieba

            raw_tokens = jieba.lcut(text)
        except Exception:
            raw_tokens = re.findall(r"[\u4e00-\u9fffA-Za-z0-9]{2,8}", text)
        tokens = []
        for token in raw_tokens:
            token = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", str(token).strip())
            if 2 <= len(token) <= 8:
                tokens.append(token)
        return tokens

    @staticmethod
    def _best_snippet(texts: List[str], keyword: str) -> str:
        candidates = [text for text in texts if keyword and keyword in text] or texts
        if not candidates:
            return ""
        snippet = re.split(r"[。！？!?；;，,]", candidates[0], maxsplit=1)[0]
        return ErrorHandler._fit_limit(snippet, 36).rstrip("。")

    @staticmethod
    def _fit_limit(text: str, limit: int) -> str:
        if len(text) <= limit:
            return text
        return text[: max(0, limit - 1)].rstrip("，；、,; ") + "。"
