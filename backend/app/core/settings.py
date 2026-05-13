import json
from copy import deepcopy
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

BACKEND_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BACKEND_ROOT.parent

PLATFORM_COOKIE_FILES: Dict[str, str] = {
    "weibo": "cookies_weibo.json",
    "douyin": "cookies_douyin.json",
    "bilibili": "cookies_bili.json",
    "zhihu": "cookies_zhihu.json",
    "xhs": "cookies_xhs.json",
}

PLATFORM_COOKIE_ALIASES: Dict[str, List[str]] = {
    "bilibili": ["cookies_bilibili.json"],
    "douyin": ["cookies_dy.json"],
}

DEFAULT_SETTINGS = {
    "system": {
        "site_name": "社交媒体分析系统",
        "site_description": "专业的社交媒体热点话题发现与情感分析平台",
        "max_tasks_per_user": 10,
        "task_timeout": 3600,
        "enable_registration": True,
        "enable_email_verification": False,
    },
    "model": {
        "model_name": "lxyuan/distilbert-base-multilingual-cased-sentiments-student",
        "batch_size": 32,
        "max_length": 128,
        "confidence_threshold": 0.6,
        "enable_gpu": True,
        "model_version": "1.0.0",
        "auto_update": False,
    },
    "llm": {
        "provider": "openai",
        "model": "qwen-plus",
        "api_base": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "api_key": "",
        "max_tokens": 1000,
        "temperature": 0.7,
        "top_p": 0.9,
        "frequency_penalty": 0.0,
        "presence_penalty": 0.0,
    },
    "agent": {
        "memory_backend": "local",
        "redis_url": "redis://localhost:6379/0",
        "redis_connect_timeout": 0.5,
        "redis_socket_timeout": 0.5,
        "session_ttl_seconds": 3600,
        "session_round_limit": 5,
        "retrieval_backend": "keyword",
        "retrieval_top_k": 3,
        "retrieval_candidate_limit": 24,
        "retrieval_score_threshold": 0.15,
        "embedding_model": "moka-ai/m3e-base",
        "embedding_allow_download": False,
        "redis_index_name": "idx:agent_knowledge",
        "redis_vector_field": "embedding",
        "redis_doc_prefix": "agent:doc",
        "milvus_collection": "agent_knowledge",
        "milvus_host": "localhost",
        "milvus_port": "19530",
        "milvus_uri": "",
        "milvus_token": "",
        "enable_tool_logging": True,
    },
    "platform": {
        "weibo": {
            "enabled": True,
            "max_posts_per_request": 100,
            "request_delay": 2,
        },
        "douyin": {
            "enabled": True,
            "max_posts_per_request": 80,
            "request_delay": 3,
        },
        "bilibili": {
            "enabled": True,
            "max_posts_per_request": 50,
            "request_delay": 2,
        },
        "xhs": {
            "enabled": False,
            "max_posts_per_request": 60,
            "request_delay": 2.5,
        },
    },
}


def get_default_setting(key: str):
    return deepcopy(DEFAULT_SETTINGS.get(key, {}))


def get_cookie_file_path(platform: str) -> Path:
    if platform not in PLATFORM_COOKIE_FILES:
        raise ValueError(f"Unsupported platform: {platform}")
    return BACKEND_ROOT / PLATFORM_COOKIE_FILES[platform]


def get_cookie_file_candidates(platform: str) -> List[str]:
    names = [PLATFORM_COOKIE_FILES.get(platform, f"cookies_{platform}.json")]
    names.extend(PLATFORM_COOKIE_ALIASES.get(platform, []))

    candidates: List[str] = []
    seen = set()
    for base_dir in (BACKEND_ROOT, PROJECT_ROOT, Path.cwd()):
        for name in names:
            path = str((base_dir / name).resolve())
            if path in seen:
                continue
            seen.add(path)
            candidates.append(path)
    return candidates


def _extract_cookie_pairs(raw_cookie: str) -> List[Tuple[str, str]]:
    pairs: List[Tuple[str, str]] = []
    for item in raw_cookie.split(";"):
        if "=" not in item:
            continue
        name, value = item.strip().split("=", 1)
        name = name.strip()
        value = value.strip()
        if name:
            pairs.append((name, value))
    return pairs


def _normalize_cookie_json(data) -> Tuple[str, int]:
    cookie_list = data.get("cookies") if isinstance(data, dict) else data
    if not isinstance(cookie_list, list):
        raise ValueError("Cookie JSON 必须是数组，或包含 cookies 数组字段。")

    normalized = []
    for item in cookie_list:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        value = item.get("value")
        if not name or value is None:
            continue
        normalized.append(item)

    if not normalized:
        raise ValueError("未识别到有效的 Cookie 项。")

    return json.dumps(normalized, ensure_ascii=False, indent=2), len(normalized)


def normalize_cookie_content(raw_content: str) -> Dict[str, object]:
    content = raw_content.strip()
    if not content:
        raise ValueError("Cookie 内容不能为空。")

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        parsed = None

    if parsed is not None:
        normalized_content, cookie_count = _normalize_cookie_json(parsed)
        return {
            "content": normalized_content,
            "cookie_count": cookie_count,
            "format": "json",
        }

    pairs = _extract_cookie_pairs(content)
    if not pairs:
        raise ValueError("未识别到有效的 Cookie，请粘贴浏览器 Cookie 串或 Cookie JSON。")

    return {
        "content": "; ".join(f"{name}={value}" for name, value in pairs),
        "cookie_count": len(pairs),
        "format": "raw",
    }


def read_cookie_metadata(platform: str) -> Dict[str, object]:
    file_path = get_cookie_file_path(platform)
    if not file_path.exists():
        for candidate in get_cookie_file_candidates(platform):
            candidate_path = Path(candidate)
            if candidate_path.exists():
                file_path = candidate_path
                break

    if not file_path.exists():
        return {
            "has_cookie": False,
            "cookie_file": str(get_cookie_file_path(platform)),
            "cookie_count": 0,
            "updated_at": None,
            "format": None,
        }

    raw_content = file_path.read_text(encoding="utf-8").strip()
    normalized = normalize_cookie_content(raw_content)
    stat = file_path.stat()
    return {
        "has_cookie": True,
        "cookie_file": str(file_path),
        "cookie_count": normalized["cookie_count"],
        "updated_at": int(stat.st_mtime),
        "format": normalized["format"],
    }


def read_platform_cookie_status(platforms: Iterable[str]) -> Dict[str, Dict[str, object]]:
    return {platform: read_cookie_metadata(platform) for platform in platforms}
