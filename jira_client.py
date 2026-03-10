# -*- coding: utf-8 -*-
"""Jira client: fetch issue and parse P4 CL numbers from custom field."""

import re
import requests
from typing import List, Optional, Tuple


def parse_cl_numbers(value) -> List[int]:
    """
    Parse CL numbers from Jira custom field value.
    Supports: single number, comma/space separated string, list of values.
    """
    if value is None:
        return []
    if isinstance(value, (int, float)):
        n = int(value)
        return [n] if n > 0 else []
    if isinstance(value, list):
        out = []
        for item in value:
            if isinstance(item, dict) and "value" in item:
                out.extend(parse_cl_numbers(item["value"]))
            else:
                out.extend(parse_cl_numbers(item))
        return list(dict.fromkeys(out))  # preserve order, dedup
    s = str(value).strip()
    if not s:
        return []
    # 支持英文/中文逗号、空格、换行、分号等分隔，避免只解析出第一个 CL
    parts = re.split(r"[\s,;\n，、；]+", s)
    result = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        # 同一段里可能有多个数字（如 "4875980，4876094" 未正确分割时），用 findall 取全
        for match in re.finditer(r"\d+", part):
            result.append(int(match.group()))
    return list(dict.fromkeys(result))


def get_issues_assigned_to_me(
    base_url: str,
    email: str,
    api_token: str,
    jql_extra: Optional[str] = None,
    assignee_extra: Optional[List[str]] = None,
    max_results: int = 50,
) -> Tuple[List[Tuple[str, str]], Optional[str]]:
    """
    查询「经办人=当前用户」或「经办人在额外列表内」的工单。

    assignee_extra: 额外监听的经办人 Jira 用户名列表（如 ["YaoBo"]），与 currentUser() 一起用 assignee in (...) 查询。
    """
    base_url = base_url.rstrip("/")
    assignees = ["currentUser()"]
    for name in assignee_extra or []:
        n = (name or "").strip()
        if n:
            assignees.append(f'"{n}"')
    assignee_expr = "assignee in (" + ", ".join(assignees) + ")" if len(assignees) > 1 else "assignee = currentUser()"
    jql = f"{assignee_expr} ORDER BY updated DESC"
    if (jql_extra or "").strip():
        jql = f"{assignee_expr} {jql_extra.strip()} ORDER BY updated DESC"
    # Jira Cloud 已移除 /rest/api/2/search，改用 v3: /rest/api/3/search/jql
    url = f"{base_url}/rest/api/3/search/jql"
    auth = (email, api_token)
    params = {
        "jql": jql,
        "maxResults": max(1, min(max_results, 100)),
        "fields": "summary,updated",
    }
    headers = {"Accept": "application/json"}
    try:
        r = requests.get(url, auth=auth, headers=headers, params=params, timeout=30)
    except requests.RequestException as e:
        return [], str(e)
    if r.status_code == 401:
        return [], "Jira 认证失败，请检查 email 与 api_token"
    if r.status_code != 200:
        return [], f"Jira 搜索失败: {r.status_code} - {(r.text or '')[:200]}"
    try:
        data = r.json()
    except Exception as e:
        return [], f"Jira 响应解析失败: {e}"
    issues = data.get("issues") or []
    result = []
    for i in issues:
        key = (i.get("key") or "").strip()
        updated = (i.get("fields") or {}).get("updated") or ""
        if key:
            result.append((key, updated))
    return result, None


def get_issue_cls(
    base_url: str,
    issue_key: str,
    cl_custom_field_id: str,
    email: str,
    api_token: str,
) -> tuple[Optional[dict], List[int], Optional[str]]:
    """
    Fetch Jira issue and extract CL numbers from the given custom field.

    Returns:
        (issue_dict, cl_list, error_message)
        - issue_dict: full issue if success, else None
        - cl_list: list of CL numbers (may be empty if field missing/invalid)
        - error_message: None if success, else error string
    """
    base_url = base_url.rstrip("/")
    url = f"{base_url}/rest/api/2/issue/{issue_key}"
    auth = (email, api_token)
    headers = {"Accept": "application/json"}

    try:
        r = requests.get(url, auth=auth, headers=headers, timeout=30)
    except requests.RequestException as e:
        return None, [], str(e)

    if r.status_code == 404:
        return None, [], f"Jira 单号不存在: {issue_key}"
    if r.status_code == 401:
        return None, [], "Jira 认证失败，请检查 email 与 api_token"
    if r.status_code != 200:
        return None, [], f"Jira 请求失败: {r.status_code} - {r.text[:200]}"

    try:
        data = r.json()
    except Exception as e:
        return None, [], f"Jira 响应解析失败: {e}"

    fields = data.get("fields") or {}
    raw = fields.get(cl_custom_field_id)
    cl_list = parse_cl_numbers(raw)
    return data, cl_list, None


def get_issue_reporter(issue: Optional[dict]) -> str:
    """
    从 Jira issue 中取出报告人（reporter）的显示名，用于多维表格「JIRA单创建人」等。
    优先 displayName，其次 name，再次 emailAddress。
    """
    if not issue or not isinstance(issue, dict):
        return ""
    reporter = (issue.get("fields") or {}).get("reporter")
    if not reporter or not isinstance(reporter, dict):
        return ""
    return (
        (reporter.get("displayName") or "").strip()
        or (reporter.get("name") or "").strip()
        or (reporter.get("emailAddress") or "").strip()
    )


def get_issue_assignee(issue: Optional[dict]) -> str:
    """
    从 Jira issue 中取出经办人（assignee）的显示名。
    优先 displayName，其次 name。
    """
    if not issue or not isinstance(issue, dict):
        return ""
    assignee = (issue.get("fields") or {}).get("assignee")
    if not assignee or not isinstance(assignee, dict):
        return ""
    return (
        (assignee.get("displayName") or "").strip()
        or (assignee.get("name") or "").strip()
    )


def get_issue_status(issue: Optional[dict]) -> str:
    """从 Jira issue 中取出状态名：fields.status.name。"""
    if not issue or not isinstance(issue, dict):
        return ""
    status = (issue.get("fields") or {}).get("status")
    if not status or not isinstance(status, dict):
        return ""
    return (status.get("name") or "").strip()


def get_issue_assignee_and_status(
    base_url: str,
    issue_key: str,
    email: str,
    api_token: str,
) -> Tuple[Optional[str], Optional[str]]:
    """
    仅请求 Jira issue 的 assignee 与 status 字段，用于 Bitable 回填等轻量场景（不触发 P4/AI）。
    Returns:
        (assignee_display_name, status_name)，任一侧失败时为 (None, None) 或 (None, status) / (assignee, None)。
    """
    base_url = base_url.rstrip("/")
    url = f"{base_url}/rest/api/2/issue/{issue_key}"
    auth = (email, api_token)
    headers = {"Accept": "application/json"}
    params = {"fields": "assignee,status"}
    try:
        r = requests.get(url, auth=auth, headers=headers, params=params, timeout=15)
    except requests.RequestException:
        return None, None
    if r.status_code != 200:
        return None, None
    try:
        data = r.json()
    except Exception:
        return None, None
    fields = data.get("fields") or {}
    assignee_str = ""
    a = fields.get("assignee")
    if a and isinstance(a, dict):
        assignee_str = (a.get("displayName") or a.get("name") or "").strip()
    status_str = ""
    s = fields.get("status")
    if s and isinstance(s, dict):
        status_str = (s.get("name") or "").strip()
    return (assignee_str or None, status_str or None)


def get_issue_assignee(issue: Optional[dict]) -> str:
    """
    从 Jira issue 中取出经办人（assignee）的显示名。
    优先 displayName，其次 name，再次 emailAddress。
    """
    if not issue or not isinstance(issue, dict):
        return ""
    assignee = (issue.get("fields") or {}).get("assignee")
    if not assignee or not isinstance(assignee, dict):
        return ""
    return (
        (assignee.get("displayName") or "").strip()
        or (assignee.get("name") or "").strip()
        or (assignee.get("emailAddress") or "").strip()
    )


def get_issue_status(issue: Optional[dict]) -> str:
    """从 Jira issue 中取出状态名（status.name）。"""
    if not issue or not isinstance(issue, dict):
        return ""
    status = (issue.get("fields") or {}).get("status")
    if not status or not isinstance(status, dict):
        return ""
    return (status.get("name") or "").strip()


def get_issue_status_only(
    base_url: str, issue_key: str, email: str, api_token: str
) -> Optional[str]:
    """
    仅请求 Jira issue 的状态，用于 Bitable 状态同步。
    返回 status.name，失败返回 None。
    """
    base_url = base_url.rstrip("/")
    url = f"{base_url}/rest/api/2/issue/{issue_key}"
    auth = (email, api_token)
    headers = {"Accept": "application/json"}
    params = {"fields": "status"}
    try:
        r = requests.get(url, auth=auth, headers=headers, params=params, timeout=15)
    except requests.RequestException:
        return None
    if r.status_code != 200:
        return None
    try:
        data = r.json()
    except Exception:
        return None
    status = (data.get("fields") or {}).get("status")
    if not status or not isinstance(status, dict):
        return None
    return (status.get("name") or "").strip() or None


def get_issue_assignee_and_status(
    base_url: str, issue_key: str, email: str, api_token: str
) -> Tuple[str, str]:
    """
    仅请求 Jira issue 的经办人与状态，用于 Bitable 回填（不触发 P4/AI）。
    Returns:
        (assignee_display_name, status_name)，失败或缺失时为 ("", "")。
    """
    base_url = base_url.rstrip("/")
    url = f"{base_url}/rest/api/2/issue/{issue_key}"
    auth = (email, api_token)
    headers = {"Accept": "application/json"}
    params = {"fields": "assignee,status"}
    try:
        r = requests.get(url, auth=auth, headers=headers, params=params, timeout=15)
    except requests.RequestException:
        return "", ""
    if r.status_code != 200:
        return "", ""
    try:
        data = r.json()
    except Exception:
        return "", ""
    fields = data.get("fields") or {}
    assignee = get_issue_assignee({"fields": fields})
    status = get_issue_status({"fields": fields})
    return assignee or "", status or ""
