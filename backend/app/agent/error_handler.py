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
        "和",
        "与",
        "及",
        "并",
        "或",
        "了",
        "的",
        "在",
        "是",
        "有",
        "觉得",
        "认为",
        "出来",
        "看到",
        "知道",
        "关键",
        "明显",
        "提升",
        "受到",
        "多款",
        "一些",
        "看清楚",
        "很",
        "才",
        "也",
        "要",
        "都",
        "又",
        "还",
        "再",
        "更",
        "时候",
        "现在",
        "今天",
        "明天",
        "昨天",
        "哈哈",
        "哈哈哈",
        "啊啊",
        "哈哈哈哈",
    }

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
        post_terms = ErrorHandler._key_phrases(posts, keyword, 3)
        comment_terms = ErrorHandler._key_phrases(comments, keyword, 4)
        post_clause = ErrorHandler._representative_clause(posts, post_terms, keyword)
        comment_clause = ErrorHandler._representative_clause(comments, comment_terms, keyword)

        parts = [f"采集到{total_posts}帖{total_comments}评"]
        if keyword:
            parts.append(f"围绕{keyword}")
        if post_terms:
            parts.append(f"帖子内容提到{'、'.join(post_terms)}")
        elif post_clause:
            parts.append(f"帖子内容提到{post_clause}")
        if comment_terms:
            parts.append(f"评论主要讨论{'、'.join(comment_terms)}")
        elif comment_clause:
            parts.append(f"评论主要讨论{comment_clause}")

        if len(parts) <= 2:
            snippet = ErrorHandler._best_snippet(posts + comments, keyword)
            if snippet:
                parts.append(snippet)

        return ErrorHandler._fit_limit("，".join(parts) + "。", limit)

    @staticmethod
    def _key_phrases(texts: List[str], keyword: str, limit: int) -> List[str]:
        keyword_parts = set(ErrorHandler._tokenize(keyword)) | {keyword}
        scores: Counter[str] = Counter()

        try:
            import jieba.analyse

            tags = jieba.analyse.extract_tags(
                "。".join(texts),
                topK=max(limit * 4, 12),
                withWeight=True,
                allowPOS=("n", "nr", "ns", "nt", "nz", "vn", "v", "a"),
            )
            for tag, weight in tags:
                phrase = ErrorHandler._normalize_phrase(tag)
                if ErrorHandler._is_good_phrase(phrase, keyword_parts):
                    scores[phrase] += max(1, int(weight * 2))
        except Exception:
            pass

        for text in texts:
            raw_tokens = ErrorHandler._raw_tokens(text)
            tokens = [
                token
                for token in raw_tokens
                if ErrorHandler._is_good_phrase(token, keyword_parts)
            ]
            for token in tokens:
                scores[token] += 1
            for first, second in zip(raw_tokens, raw_tokens[1:]):
                if first in ErrorHandler._SUMMARY_STOP_WORDS or second in ErrorHandler._SUMMARY_STOP_WORDS:
                    continue
                phrase = ErrorHandler._normalize_phrase(first + second)
                if ErrorHandler._is_good_phrase(phrase, keyword_parts, allow_longer=True):
                    scores[phrase] += 4

        selected: List[str] = []
        for phrase, _ in sorted(scores.items(), key=lambda item: (-item[1], -len(item[0]), item[0])):
            if any(phrase in existing or existing in phrase for existing in selected):
                continue
            selected.append(phrase)
            if len(selected) >= limit:
                break
        return selected

    @staticmethod
    def _representative_clause(texts: List[str], phrases: List[str], keyword: str) -> str:
        candidates: List[str] = []
        for text in texts:
            for clause in re.split(r"[。！？!?；;，,\n]", text):
                clause = ErrorHandler._clean_text(clause)
                if 4 <= len(clause) <= 36:
                    candidates.append(clause)
        if not candidates:
            return ""

        keyword_parts = set(ErrorHandler._tokenize(keyword)) | {keyword}

        def score_clause(clause: str) -> tuple[int, int]:
            phrase_hits = sum(1 for phrase in phrases if phrase and phrase in clause)
            keyword_hits = sum(1 for part in keyword_parts if part and part in clause)
            return (phrase_hits * 3 + keyword_hits, -len(clause))

        best = max(candidates, key=score_clause)
        return ErrorHandler._fit_limit(best, 36).rstrip("。")

    @staticmethod
    def _normalize_phrase(phrase: str) -> str:
        phrase = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", str(phrase or "").strip())
        return phrase

    @staticmethod
    def _is_good_phrase(
        phrase: str,
        keyword_parts: set[str],
        *,
        allow_longer: bool = False,
    ) -> bool:
        if not phrase:
            return False
        max_length = 12 if allow_longer else 8
        if len(phrase) < 2 or len(phrase) > max_length:
            return False
        if phrase.isdigit() or phrase in ErrorHandler._SUMMARY_STOP_WORDS:
            return False
        if phrase in keyword_parts:
            return False
        if any(part and phrase == part for part in keyword_parts):
            return False
        if phrase[0] in "和与及并或的了在是有" or phrase[-1] in "和与及并或的了在是有":
            return False
        if re.fullmatch(r"[A-Za-z0-9]+", phrase) and len(phrase) < 3:
            return False
        return True

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
    def _tokenize(text: str) -> List[str]:
        return [token for token in ErrorHandler._raw_tokens(text) if 2 <= len(token) <= 8]

    @staticmethod
    def _raw_tokens(text: str) -> List[str]:
        try:
            import jieba

            raw_tokens = jieba.lcut(text)
        except Exception:
            raw_tokens = re.findall(r"[\u4e00-\u9fffA-Za-z0-9]{2,8}", text)
        tokens = []
        for token in raw_tokens:
            token = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", str(token).strip())
            if 1 <= len(token) <= 8:
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
