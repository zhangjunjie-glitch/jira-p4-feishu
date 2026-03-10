# -*- coding: utf-8 -*-
"""
AI 客户端：根据变更内容调用大模型分析需要测试的范围。
支持 OpenAI、Gemini（Google AI）及兼容 OpenAI 的接口。
"""

import requests
from typing import Optional

# 默认模型与端点（可被配置覆盖）
DEFAULT_OPENAI_BASE = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_GEMINI_MODEL = "gemini-1.5-flash"

# 发给模型的上下文长度上限（字符），避免超长
MAX_CONTEXT_CHARS = 30000


def _call_openai(
    api_key: str,
    base_url: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
) -> str:
    """调用 OpenAI 或兼容接口的 chat/completions。"""
    url = f"{base_url.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key.strip()}",
        "Content-Type": "application/json",
    }
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "max_tokens": 1500,
        "temperature": 0.3,
    }
    r = requests.post(url, headers=headers, json=body, timeout=60)
    if r.status_code != 200:
        return ""
    try:
        data = r.json()
    except Exception:
        return ""
    choices = data.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") or {}
    text = (message.get("content") or "").strip()
    return text[:8000] if text else ""


def _call_gemini(
    api_key: str,
    base_url: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
) -> str:
    """调用 Google Gemini generateContent 接口。"""
    base = base_url.rstrip("/")
    url = f"{base}/models/{model}:generateContent"
    headers = {
        "x-goog-api-key": api_key.strip(),
        "Content-Type": "application/json",
    }
    body = {
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"parts": [{"text": user_prompt}]}],
        "generationConfig": {
            "maxOutputTokens": 1500,
            "temperature": 0.3,
        },
    }
    r = requests.post(url, headers=headers, json=body, timeout=60)
    if r.status_code != 200:
        return ""
    try:
        data = r.json()
    except Exception:
        return ""
    candidates = (data.get("candidates") or [])
    if not candidates:
        return ""
    parts = (candidates[0].get("content") or {}).get("parts") or []
    if not parts:
        return ""
    text = (parts[0].get("text") or "").strip()
    return text[:8000] if text else ""


def get_test_scope_suggestion(
    change_content: str,
    api_key: str,
    base_url: Optional[str] = None,
    model: Optional[str] = None,
    provider: Optional[str] = None,
    project_context: Optional[str] = None,
) -> str:
    """
    根据变更内容（及可选的项目结构上下文）调用大模型，生成「需要测试的范围」建议。

    Args:
        change_content: 变更摘要（含文件列表、diff 片段、Excel 变更等），会截断到 MAX_CONTEXT_CHARS。
        api_key: API 密钥（OpenAI、Gemini 或兼容服务的 key）。
        base_url: 可选，接口 base；不填时 OpenAI 用默认，Gemini 用 generativelanguage.googleapis.com/v1beta。
        model: 可选，模型名；不填时 OpenAI 默认 gpt-4o-mini，Gemini 默认 gemini-1.5-flash。
        provider: 可选，'gemini' 表示使用 Google Gemini，否则使用 OpenAI 兼容接口。
        project_context: 可选，与变更相关的项目 depot 区域结构（目录与文件示例），便于从全项目角度给出测试范围。

    Returns:
        模型返回的测试范围建议文本；失败或未配置则返回空字符串。
    """
    if not (api_key or "").strip():
        return ""
    use_gemini = (provider or "").strip().lower() == "gemini"
    if use_gemini:
        base = (base_url or "").strip() or DEFAULT_GEMINI_BASE
        model_name = (model or "").strip() or DEFAULT_GEMINI_MODEL
    else:
        base = (base_url or "").strip() or DEFAULT_OPENAI_BASE
        model_name = (model or "").strip() or DEFAULT_MODEL

    content = (change_content or "")[:MAX_CONTEXT_CHARS]
    if len(change_content or "") > MAX_CONTEXT_CHARS:
        content += "\n\n...（以上为截断后的变更内容）"

    system_prompt = """你是一个测试分析助手。根据开发提交的代码/配置/文档变更内容，以及（若提供）项目 depot 区域的结构与文件列表，从**整个项目**角度分析「需要测试的范围」。
请结合：1）本次变更涉及的文件与具体改动；2）项目内同区域或相关模块（根据路径与目录结构推断），给出更全面的测试建议。
用简洁的中文列出：建议重点测试的功能模块、可能受影响的功能与上下游、建议的测试类型（如回归、接口、UI、配置校验、依赖该模块的其他功能等）。若仅有变更内容而无项目结构，则主要根据变更本身推断；若有项目结构，请结合目录与文件示例推断关联模块，使测试范围更全面。不要编造变更或项目中未出现的内容。"""

    project_block = ""
    if (project_context or "").strip():
        project_block = f"""【项目结构（与本次变更相关的 depot 区域）】
{project_context.strip()}

"""
    user_prompt = f"""{project_block}【本次变更的文件与具体内容】
{content}

---
请根据上述{('项目结构与' if project_block else '')}变更内容，分析并给出需要测试的范围建议（直接给出结论，无需重复原文）。建议结合项目内相关模块，使测试范围更全面。输出格式：分条或分段均可。"""

    try:
        if use_gemini:
            return _call_gemini(api_key, base, model_name, system_prompt, user_prompt)
        return _call_openai(api_key, base, model_name, system_prompt, user_prompt)
    except requests.RequestException:
        return ""
