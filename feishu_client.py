# -*- coding: utf-8 -*-
"""Feishu client: get tenant_access_token and send message to chat."""

import json
import os
import re
import tempfile
import requests
from datetime import datetime
from typing import List, Optional, Tuple


FEISHU_AUTH_URL = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
FEISHU_MESSAGE_URL = "https://open.feishu.cn/open-apis/im/v1/messages"


def get_tenant_access_token(app_id: str, app_secret: str) -> tuple[Optional[str], Optional[str]]:
    """
    Get Feishu tenant_access_token.

    Returns:
        (token, error_message). token is None on failure.
    """
    try:
        r = requests.post(
            FEISHU_AUTH_URL,
            json={"app_id": app_id, "app_secret": app_secret},
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
    except requests.RequestException as e:
        return None, str(e)

    data = r.json()
    if r.status_code != 200:
        return None, f"飞书 token 请求失败: {r.status_code} - {data}"

    code = data.get("code")
    if code != 0:
        return None, f"飞书 token 失败: code={code}, msg={data.get('msg', '')}"

    token = data.get("tenant_access_token")
    if not token:
        return None, "飞书响应中无 tenant_access_token"
    return token, None


def send_text_message(
    token: str,
    receive_id: str,
    text: str,
    receive_id_type: str = "chat_id",
) -> Optional[str]:
    """
    Send a text message to Feishu chat/user.

    Returns:
        None on success, else error message string.
    """
    url = f"{FEISHU_MESSAGE_URL}?receive_id_type={receive_id_type}"
    content = json.dumps({"text": text})
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=utf-8",
    }
    body = {"receive_id": receive_id, "msg_type": "text", "content": content}

    try:
        r = requests.post(url, json=body, headers=headers, timeout=10)
    except requests.RequestException as e:
        return str(e)

    data = r.json()
    if r.status_code != 200:
        return f"飞书发消息请求失败: {r.status_code} - {data}"

    code = data.get("code")
    if code != 0:
        msg = data.get("msg", "")
        if code == 230002:
            return "飞书机器人不在对应群组中，请将机器人拉入群聊"
        if code == 230006:
            return "飞书应用未开启机器人能力"
        return f"飞书发消息失败: code={code}, msg={msg}"

    return None


def reply_to_message(token: str, message_id: str, text: str) -> Optional[str]:
    """
    回复指定消息（用于机器人收到 @ 后回复）。

    message_id: 收到的消息的 open_message_id（事件体中的 message_id）。
    """
    url = f"{FEISHU_MESSAGE_URL}/{message_id}/reply"
    content = json.dumps({"text": text})
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=utf-8",
    }
    body = {"msg_type": "text", "content": content}

    try:
        r = requests.post(url, json=body, headers=headers, timeout=15)
    except requests.RequestException as e:
        return str(e)

    data = r.json()
    if r.status_code != 200:
        return f"飞书回复消息失败: {r.status_code} - {data}"

    code = data.get("code")
    if code != 0:
        msg = data.get("msg", "")
        return f"飞书回复消息失败: code={code}, msg={msg}"

    return None


def send_post_message_with_at(
    token: str,
    receive_id: str,
    body_text: str,
    at_open_ids: List[str],
    receive_id_type: str = "chat_id",
) -> Optional[str]:
    """
    发送富文本（post）消息，并在正文前 @ 指定用户。
    at_open_ids: 飞书用户的 open_id 列表，会按顺序插入 at 标签。
    """
    if not at_open_ids:
        return send_text_message(token, receive_id, body_text, receive_id_type)
    elements = []
    for oid in at_open_ids:
        oid = (oid or "").strip()
        if oid:
            elements.append({"tag": "at", "user_id": oid})
    elements.append({"tag": "text", "text": " \n\n" + (body_text or "")})
    post_content = {"post": {"zh_cn": {"content": [elements]}}}
    url = f"{FEISHU_MESSAGE_URL}?receive_id_type={receive_id_type}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=utf-8",
    }
    body = {"receive_id": receive_id, "msg_type": "post", "content": json.dumps(post_content)}
    try:
        r = requests.post(url, json=body, headers=headers, timeout=10)
    except requests.RequestException as e:
        return str(e)
    data = r.json()
    if r.status_code != 200:
        return f"飞书发消息请求失败: {r.status_code} - {data}"
    code = data.get("code")
    if code != 0:
        msg = data.get("msg", "")
        if code == 230002:
            return "飞书机器人不在对应群组中，请将机器人拉入群聊"
        if code == 230006:
            return "飞书应用未开启机器人能力"
        return f"飞书发消息失败: code={code}, msg={msg}"
    return None


def reply_to_message_post_with_at(
    token: str, message_id: str, body_text: str, at_open_ids: List[str]
) -> Optional[str]:
    """回复消息时使用 post 富文本并在正文前 @ 指定用户。"""
    if not at_open_ids:
        return reply_to_message(token, message_id, body_text)
    elements = []
    for oid in at_open_ids:
        oid = (oid or "").strip()
        if oid:
            elements.append({"tag": "at", "user_id": oid})
    elements.append({"tag": "text", "text": " \n\n" + (body_text or "")})
    post_content = {"post": {"zh_cn": {"content": [elements]}}}
    url = f"{FEISHU_MESSAGE_URL}/{message_id}/reply"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=utf-8",
    }
    body = {"msg_type": "post", "content": json.dumps(post_content)}
    try:
        r = requests.post(url, json=body, headers=headers, timeout=15)
    except requests.RequestException as e:
        return str(e)
    data = r.json()
    if r.status_code != 200:
        return f"飞书回复消息失败: {r.status_code} - {data}"
    if data.get("code") != 0:
        return f"飞书回复消息失败: code={data.get('code')}, msg={data.get('msg', '')}"
    return None


def save_report_to_temp_file(issue_key: str, report_text: str) -> str:
    """
    将完整变更报告写入临时文件，返回文件路径。
    文件名格式: jira_p4_{issue_key}_{date}.txt
    """
    safe_key = "".join(c if c.isalnum() or c in "-_" else "_" for c in issue_key)
    date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    name = f"jira_p4_{safe_key}_{date_str}.txt"
    path = os.path.join(tempfile.gettempdir(), name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(report_text)
    return path


def create_feishu_doc_with_content(
    token: str, title: str, body_text: str
) -> Tuple[Optional[str], Optional[str]]:
    """
    在飞书云文档中创建一篇文档并写入 body_text，返回 (文档链接, 错误信息)。
    需要应用具备「创建及编辑新版文档」等云文档权限。
    文档链接格式: https://open.feishu.cn/docx/{document_id}
    """
    create_url = "https://open.feishu.cn/open-apis/docx/v1/documents"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=utf-8",
    }
    try:
        r = requests.post(
            create_url,
            headers=headers,
            json={"folder_token": "", "title": title[:200]},
            timeout=15,
        )
    except requests.RequestException as e:
        return None, str(e)
    data = r.json()
    if r.status_code != 200 or data.get("code") != 0:
        return None, data.get("msg") or f"创建文档失败: {r.status_code}"
    doc = data.get("data", {}).get("document") or data.get("data", {})
    document_id = doc.get("document_id") or doc.get("id")
    if not document_id:
        return None, "响应中无 document_id"
    doc_url = f"https://open.feishu.cn/docx/{document_id}"

    # 设置「组织内获得链接可阅读」，避免成员点开显示「页面不存在」（需应用具备云文档分享/管理权限）
    perm_url = f"https://open.feishu.cn/open-apis/drive/v1/permissions/{document_id}/public?type=docx"
    try:
        requests.patch(
            perm_url,
            headers=headers,
            json={"link_share_entity": "tenant_readable"},
            timeout=10,
        )
    except requests.RequestException:
        pass

    # 飞书文档根节点 block_id 即为 document_id
    block_id = document_id
    text_preview = body_text[:50000]
    if len(body_text) > 50000:
        text_preview += "\n\n...（内容过长已截断）"
    children = []
    for line in text_preview.replace("\r\n", "\n").split("\n"):
        line = line[:5000]
        children.append({
            "block_type": 1,
            "text": {"elements": [{"text_run": {"content": line + "\n"}}]},
        })
    if not children:
        children = [{"block_type": 1, "text": {"elements": [{"text_run": {"content": "(无内容)"}}]}}]
    add_url = f"https://open.feishu.cn/open-apis/docx/v1/documents/{document_id}/blocks/{block_id}/children"
    try:
        r2 = requests.post(
            add_url,
            headers=headers,
            json={"children": children[:500], "index": 0},
            timeout=30,
        )
    except requests.RequestException as e:
        return doc_url, None
    if r2.status_code != 200 or r2.json().get("code") != 0:
        return doc_url, None
    return doc_url, None


def get_wiki_node_obj_token(access_token: str, node_token: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    通过「获取知识空间节点信息」解析 wiki 节点对应的 obj_token 与 obj_type。
    若节点为多维表格（bitable），obj_token 即为该表格的 app_token；
    若节点为知识库页面（wiki），则尝试在子节点中查找 obj_type=bitable 的节点。
    Returns: (obj_token, obj_type, error_message)
    """
    url = "https://open.feishu.cn/open-apis/wiki/v2/spaces/get_node"
    headers = {"Authorization": f"Bearer {access_token}"}
    params = {"token": node_token}
    try:
        r = requests.get(url, headers=headers, params=params, timeout=10)
    except requests.RequestException as e:
        return None, None, str(e)
    data = r.json()
    if r.status_code != 200 or data.get("code") != 0:
        return None, None, data.get("msg") or f"get_node 失败: {r.status_code}"
    node = (data.get("data") or {}).get("node") or data.get("data")
    if not node:
        return None, None, "响应中无 node"
    obj_token = node.get("obj_token")
    obj_type = (node.get("obj_type") or "").lower()
    if obj_token and obj_type == "bitable":
        return obj_token, obj_type, None
    if obj_token and obj_type:
        return obj_token, obj_type, None
    space_id = node.get("space_id")
    if not space_id:
        return None, obj_type or None, "节点无 space_id，无法查子节点"
    list_url = f"https://open.feishu.cn/open-apis/wiki/v2/spaces/{space_id}/nodes"
    try:
        r2 = requests.get(
            list_url,
            headers=headers,
            params={"parent_node_token": node_token, "page_size": 50},
            timeout=10,
        )
    except requests.RequestException as e:
        return None, obj_type or None, str(e)
    data2 = r2.json()
    if r2.status_code != 200 or data2.get("code") != 0:
        return None, obj_type or None, data2.get("msg") or "获取子节点失败"
    items = (data2.get("data") or {}).get("items") or []
    for item in items:
        if (item.get("obj_type") or "").lower() == "bitable":
            child_token = item.get("node_token")
            if child_token:
                obj_token, _, err = get_wiki_node_obj_token(access_token, child_token)
                if obj_token:
                    return obj_token, "bitable", None
            ot = item.get("obj_token")
            if ot:
                return ot, "bitable", None
    return None, obj_type or None, "未在子节点中找到 bitable"


# 多维表格写入时的列名（需在飞书中建表时与此一致）
BITABLE_FIELD_ISSUE = "JIRA单号"
BITABLE_FIELD_TITLE = "JIRA单标题"
BITABLE_FIELD_TIME = "JIRA单修改时间"
BITABLE_FIELD_CREATOR = "JIRA单创建人"
BITABLE_FIELD_ASSIGNEE = "经办人"
BITABLE_FIELD_STATUS = "JIRA单据状态"
BITABLE_FIELD_CL = "变更CL号"
BITABLE_FIELD_FILES = "变更文件"
BITABLE_FIELD_DETAIL = "变更具体内容"
BITABLE_FIELD_TEST_SCOPE = "测试范围"


def _bitable_find_record_by_issue(
    token: str, app_token: str, table_id: str, issue_key: str
) -> Optional[str]:
    """
    按 JIRA单号 查询多维表格，若存在则返回 record_id，否则返回 None。
    使用 list records 的 filter：CurrentValue.[JIRA单号]="xxx"（值内双引号已转义）。
    """
    if not (issue_key or "").strip():
        return None
    list_url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records"
    headers = {"Authorization": f"Bearer {token}"}
    # 飞书公式：CurrentValue.[字段名]="值"。值中若有 " 则改为 \"，避免公式断裂
    raw = issue_key.strip()
    safe_value = raw.replace("\\", "\\\\").replace('"', '\\"')
    filter_expr = f'CurrentValue.[{BITABLE_FIELD_ISSUE}]="{safe_value}"'
    try:
        r = requests.get(
            list_url,
            headers=headers,
            params={"filter": filter_expr, "page_size": 1},
            timeout=15,
        )
    except requests.RequestException:
        return None
    data = r.json()
    if r.status_code != 200 or data.get("code") != 0:
        return None
    items = (data.get("data") or {}).get("items") or []
    for item in items:
        rid = (item.get("record_id") or "").strip()
        if rid:
            return rid
    return None


def bitable_has_issue(
    token: str, app_token: str, table_id: str, issue_key: str
) -> bool:
    """
    判断多维表格中是否已存在该 JIRA 单号的记录。
    用于 watcher 在写入前跳过已存在的单子（避免重复通知）。
    """
    return _bitable_find_record_by_issue(token, app_token, table_id, issue_key) is not None


def _bitable_list_fields(
    token: str, app_token: str, table_id: str
) -> Tuple[dict, Optional[str]]:
    """
    获取多维表格字段列表，返回 (字段名 -> field_id 的映射, 错误信息)。
    飞书「列出记录」返回的 fields 是以 field_id 为 key，需用此映射按列名取值。
    """
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/fields"
    headers = {"Authorization": f"Bearer {token}"}
    try:
        r = requests.get(url, headers=headers, params={"page_size": 200}, timeout=15)
    except requests.RequestException as e:
        return {}, str(e)
    data = r.json()
    if r.status_code != 200 or data.get("code") != 0:
        return {}, data.get("msg") or f"列出字段失败: {r.status_code}"
    # 兼容 data 为数组、data.items、或顶层 items（飞书文档不一）
    raw = data.get("data")
    if isinstance(raw, list):
        items = raw
    elif isinstance(raw, dict):
        items = raw.get("items") or raw.get("fields") or []
    else:
        items = data.get("items") or data.get("fields") or []
    name_to_id = {}
    for f in items:
        fid = (f.get("field_id") or "").strip()
        # 飞书文档中列出字段返回 field_name，部分版本为 name / title
        name = (
            (f.get("field_name") or f.get("name") or f.get("title") or "").strip()
        )
        if fid and name:
            name_to_id[name] = fid
    return name_to_id, None


def bitable_get_field_map_and_sample_keys(
    token: str, app_token: str, table_id: str
) -> Tuple[dict, list, any]:
    """
    用于调试：返回 (列名->field_id 映射, 首条记录的 fields 的 key 列表, 首条 JIRA单号 的原始值)。
    当回填全部被跳过时，可据此确认飞书 API 返回的字段 key 格式与取值类型。
    """
    name_to_id, err = _bitable_list_fields(token, app_token, table_id)
    if err:
        return name_to_id, [], None
    list_url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records"
    headers = {"Authorization": f"Bearer {token}"}
    try:
        r = requests.get(list_url, headers=headers, params={"page_size": 1}, timeout=15)
    except requests.RequestException:
        return name_to_id, [], None
    data = r.json()
    if r.status_code != 200 or data.get("code") != 0:
        return name_to_id, [], None
    items = (data.get("data") or {}).get("items") or []
    if not items:
        return name_to_id, [], None
    fields = items[0].get("fields") or {}
    sample_keys = list(fields.keys())
    sample_issue_val = fields.get(BITABLE_FIELD_ISSUE)
    fid = name_to_id.get(BITABLE_FIELD_ISSUE)
    if sample_issue_val is None and fid:
        sample_issue_val = fields.get(fid)
    return name_to_id, sample_keys, sample_issue_val


def bitable_get_first_record_fields_keys(
    token: str, app_token: str, table_id: str, page_size: int = 500
) -> list:
    """调试用：用指定 page_size 拉取一页记录，返回首条记录的 fields 的 key 列表。"""
    list_url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records"
    headers = {"Authorization": f"Bearer {token}"}
    try:
        r = requests.get(
            list_url, headers=headers, params={"page_size": page_size}, timeout=30
        )
    except requests.RequestException:
        return []
    data = r.json()
    if r.status_code != 200 or data.get("code") != 0:
        return []
    items = (data.get("data") or {}).get("items") or []
    if not items:
        return []
    return list((items[0].get("fields") or {}).keys())


def bitable_list_record_ids_and_issue_keys(
    token: str, app_token: str, table_id: str, page_size: int = 500
) -> Tuple[List[Tuple[str, str]], Optional[str]]:
    """
    拉取多维表格记录，通过扫描每条记录的任意字段值匹配 JIRA 单号格式（XXX-123），
    返回 [(record_id, issue_key), ...]。用于 list 接口返回的 key 与列名不一致时的兜底。
    """
    list_url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records"
    headers = {"Authorization": f"Bearer {token}"}
    jira_pat = re.compile(r"^[A-Za-z][A-Za-z0-9]*-\d+$")
    result = []
    page_token = None
    while True:
        params = {"page_size": min(500, max(1, page_size))}
        if page_token:
            params["page_token"] = page_token
        try:
            r = requests.get(list_url, headers=headers, params=params, timeout=30)
        except requests.RequestException as e:
            return [], str(e)
        data = r.json()
        if r.status_code != 200 or data.get("code") != 0:
            return [], data.get("msg") or f"列出记录失败: {r.status_code}"
        d = data.get("data") or {}
        items = d.get("items") or []
        for item in items:
            rid = (item.get("record_id") or "").strip()
            if not rid:
                continue
            fields = item.get("fields") or {}
            if not isinstance(fields, dict):
                continue
            issue_key = ""
            for v in fields.values():
                s = (v if isinstance(v, str) else (str(v[0]) if isinstance(v, list) and v else "")) or ""
                s = s.strip()
                if s and "-" in s and any(c.isdigit() for c in s) and jira_pat.match(s):
                    issue_key = s
                    break
            result.append((rid, issue_key))
        has_more = d.get("has_more") is True
        page_token = d.get("page_token") or None
        if not has_more or not page_token:
            break
    return result, None


def bitable_get_first_record_raw(
    token: str, app_token: str, table_id: str, page_size: int = 500
) -> Optional[dict]:
    """调试用：返回 list records 首条记录的原始 item（含 record_id、fields 等）。"""
    list_url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records"
    headers = {"Authorization": f"Bearer {token}"}
    try:
        r = requests.get(
            list_url, headers=headers, params={"page_size": page_size}, timeout=30
        )
    except requests.RequestException:
        return None
    data = r.json()
    if r.status_code != 200 or data.get("code") != 0:
        return None
    items = (data.get("data") or {}).get("items") or []
    return items[0] if items else None


def bitable_list_records(
    token: str,
    app_token: str,
    table_id: str,
    page_size: int = 500,
) -> Tuple[List[dict], Optional[str]]:
    """
    分页拉取多维表格全部记录，用于经办人/状态回填、Watcher 状态同步等。
    返回 (records, error_message)。records 中每项为 {"record_id", "issue_key", "assignee", "status"}，
    其中 issue_key/assignee/status 来自表字段 JIRA单号/经办人/JIRA单据状态（若存在）。
    飞书 API 返回的 fields 以 field_id 为 key，会先拉取字段列表做列名->field_id 映射再解析。
    """
    name_to_id, fields_err = _bitable_list_fields(token, app_token, table_id)
    if fields_err:
        return [], fields_err
    # JIRA 单号格式：PROJECT-123 等，用于无列名匹配时的兜底
    _JIRA_KEY_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9]*-\d+$")

    def _get_field(fields: dict, name: str) -> str:
        val = fields.get(name)
        fid = name_to_id.get(name)
        if val is None and fid:
            val = fields.get(fid)
        if val is None and name:
            name_stripped = (name or "").strip()
            for k, v in (fields or {}).items():
                if (k or "").strip() == name_stripped:
                    val = v
                    break
            if val is None and name_stripped == BITABLE_FIELD_ISSUE:
                for k, v in (fields or {}).items():
                    if k and "JIRA" in str(k) and "单" in str(k) and "号" in str(k):
                        val = v
                        break
        if val is None and name == BITABLE_FIELD_ISSUE and fields:
            for v in (fields or {}).values():
                if isinstance(v, str):
                    s = v.strip()
                elif isinstance(v, list) and v:
                    s = str(v[0]).strip()
                elif isinstance(v, dict):
                    s = (v.get("text") or v.get("value") or "").strip() or str(v).strip()
                else:
                    s = str(v).strip() if v is not None else ""
                if s and "-" in s and any(c.isdigit() for c in s):
                    return s  # 形如 XXX-123 即视为 JIRA 单号
        if val is None:
            return ""
        if isinstance(val, list):
            return str(val[0]).strip() if val else ""
        return (str(val).strip() or "")

    list_url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records"
    headers = {"Authorization": f"Bearer {token}"}
    all_items = []
    page_token = None
    while True:
        params = {"page_size": min(500, max(1, page_size))}
        if page_token:
            params["page_token"] = page_token
        try:
            r = requests.get(list_url, headers=headers, params=params, timeout=30)
        except requests.RequestException as e:
            return [], str(e)
        data = r.json()
        if r.status_code != 200 or data.get("code") != 0:
            return [], data.get("msg") or f"列出记录失败: {r.status_code}"
        d = data.get("data") or {}
        items = d.get("items") or []
        for idx, item in enumerate(items):
            rid = (item.get("record_id") or "").strip()
            if not rid:
                continue
            fields = item.get("fields") or {}
            issue_key = _get_field(fields, BITABLE_FIELD_ISSUE)
            assignee = _get_field(fields, BITABLE_FIELD_ASSIGNEE)
            status = _get_field(fields, BITABLE_FIELD_STATUS)
            if issue_key is None:
                issue_key = ""
            all_items.append({
                "record_id": rid,
                "issue_key": issue_key,
                "assignee": assignee,
                "status": status,
            })
        has_more = d.get("has_more") is True
        page_token = d.get("page_token") or None
        if not has_more or not page_token:
            break
    return all_items, None


def bitable_update_record_fields(
    token: str,
    app_token: str,
    table_id: str,
    record_id: str,
    fields_dict: dict,
) -> Optional[str]:
    """
    仅更新指定记录的指定字段（如经办人、JIRA单据状态），不触达 P4/AI。
    Returns: None 表示成功，否则为错误信息字符串。
    """
    if not record_id or not fields_dict:
        return None
    update_url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records/{record_id}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=utf-8",
    }
    try:
        r = requests.put(update_url, headers=headers, json={"fields": fields_dict}, timeout=15)
    except requests.RequestException as e:
        return str(e)
    data = r.json()
    if r.status_code != 200 or data.get("code") != 0:
        return data.get("msg") or f"更新记录失败: {r.status_code}"
    return None


def add_report_to_bitable(
    token: str,
    app_token: str,
    table_id: str,
    issue_key: str,
    issue_title: str,
    cl_list: list,
    files_by_cl: list,
    full_detail: str,
    issue_reporter: str = "",
    test_scope: str = "",
    issue_assignee: str = "",
    issue_status: str = "",
    *,
    wiki_node_token: Optional[str] = None,
    view_id: Optional[str] = None,
    tenant_base_url: Optional[str] = None,
) -> Tuple[Optional[str], Optional[str]]:
    """
    向已存在的多维表格写入一条变更报告：若该 JIRA单号 已存在则覆盖该记录，否则新增。
    表需包含列：JIRA单号、JIRA单标题、JIRA单修改时间、JIRA单创建人、变更CL号、变更文件、变更具体内容（均为文本）。
    """
    cl_str = "、".join(str(c) for c in (cl_list or []))
    submit_times, file_list = build_bitable_submit_times_and_files(files_by_cl or [])
    brief_analysis = _brief_analysis(files_by_cl or [])
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=utf-8",
    }
    detail = (full_detail or "")[:100000]
    if len(full_detail or "") > 100000:
        detail += "\n\n...（内容过长已截断）"
    fields = {
        BITABLE_FIELD_ISSUE: issue_key or "",
        BITABLE_FIELD_TITLE: (issue_title or "")[:2000],
        BITABLE_FIELD_TIME: (submit_times or "")[:2000],
        BITABLE_FIELD_CREATOR: (issue_reporter or "")[:500],
        BITABLE_FIELD_ASSIGNEE: (issue_assignee or "")[:500],
        BITABLE_FIELD_STATUS: (issue_status or "")[:200],
        BITABLE_FIELD_CL: (cl_str or "")[:2000],
        BITABLE_FIELD_FILES: (file_list or "")[:20000],
        BITABLE_FIELD_DETAIL: (f"变更分析：{brief_analysis}\n\n" if brief_analysis else "") + detail,
    }
    if (test_scope or "").strip():
        fields[BITABLE_FIELD_TEST_SCOPE] = (test_scope or "").strip()[:5000]

    record_id = _bitable_find_record_by_issue(token, app_token, table_id, issue_key or "")
    if record_id:
        update_url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records/{record_id}"
        try:
            r = requests.put(update_url, headers=headers, json={"fields": fields}, timeout=30)
        except requests.RequestException as e:
            return None, str(e)
        data = r.json()
        if r.status_code != 200 or data.get("code") != 0:
            return None, data.get("msg") or f"多维表格更新失败: {r.status_code}"
    else:
        create_url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records/batch_create"
        try:
            r = requests.post(
                create_url,
                headers=headers,
                json={"records": [{"fields": fields}]},
                timeout=30,
            )
        except requests.RequestException as e:
            return None, str(e)
        data = r.json()
        if r.status_code != 200 or data.get("code") != 0:
            return None, data.get("msg") or f"多维表格写入失败: {r.status_code}"

    if (tenant_base_url or "").strip() and (wiki_node_token or "").strip():
        base = tenant_base_url.strip().rstrip("/")
        bitable_url = f"{base}/wiki/{wiki_node_token.strip()}?table={table_id}"
        if (view_id or "").strip():
            bitable_url += f"&view={view_id.strip()}"
    else:
        bitable_url = f"https://open.feishu.cn/base/{app_token}"
    return bitable_url, None


def bitable_list_records(
    token: str, app_token: str, table_id: str, page_size: int = 500
) -> Tuple[List[dict], Optional[str]]:
    """
    分页列出多维表格所有记录，返回每条的 record_id 及 fields（含 JIRA单号、JIRA单据状态等）。
    Returns:
        (items, error_message)，items 为 [{"record_id": "...", "fields": {...}}, ...]
    """
    headers = {"Authorization": f"Bearer {token}"}
    list_url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records"
    all_items = []
    page_token = None
    while True:
        params = {"page_size": min(page_size, 500)}
        if page_token:
            params["page_token"] = page_token
        try:
            r = requests.get(list_url, headers=headers, params=params, timeout=30)
        except requests.RequestException as e:
            return [], str(e)
        data = r.json()
        if r.status_code != 200 or data.get("code") != 0:
            return [], data.get("msg") or f"列出记录失败: {r.status_code}"
        d = data.get("data") or {}
        items = d.get("items") or []
        for it in items:
            all_items.append({
                "record_id": (it.get("record_id") or "").strip(),
                "fields": it.get("fields") or {},
            })
        if not d.get("has_more"):
            break
        page_token = d.get("page_token")
        if not page_token:
            break
    return all_items, None


def bitable_update_record_fields(
    token: str, app_token: str, table_id: str, record_id: str, fields_dict: dict
) -> Optional[str]:
    """仅更新指定记录的指定字段。返回 None 成功，否则为错误信息。"""
    if not (record_id or "").strip():
        return "record_id 为空"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=utf-8",
    }
    update_url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records/{record_id}"
    try:
        r = requests.put(update_url, headers=headers, json={"fields": fields_dict}, timeout=15)
    except requests.RequestException as e:
        return str(e)
    data = r.json()
    if r.status_code != 200 or data.get("code") != 0:
        return data.get("msg") or f"更新记录失败: {r.status_code}"
    return None


def build_bitable_submit_times_and_files(files_by_cl: list) -> Tuple[str, str]:
    """从 files_by_cl 拼出「提交时间」与「文件列表」两段文本，供多维表格写入。"""
    times_parts = []
    files_parts = []
    for item in files_by_cl:
        cl = item[0]
        paths = item[1] if len(item) > 1 else []
        submit_time = item[2] if len(item) > 2 else ""
        file_line_summaries = item[3] if len(item) > 3 else []
        times_parts.append(f"CL {cl}: {submit_time}" if submit_time else f"CL {cl}")
        path_list = [p for p, _ in file_line_summaries] if file_line_summaries else paths
        files_parts.append(f"CL {cl}:\n" + "\n".join(f"  • {p}" for p in path_list[:100]))
        if len(path_list) > 100:
            files_parts[-1] += f"\n  ... 共 {len(path_list)} 个文件"
    return "\n".join(times_parts), "\n\n".join(files_parts)


def _brief_analysis(files_by_cl: list) -> str:
    """根据路径和行变更做简短变更分析。"""
    total_files = 0
    by_suffix = {}
    for item in files_by_cl:
        if len(item) >= 2:
            paths = item[1]
            total_files += len(paths)
            for p in paths:
                if "." in p.split("/")[-1]:
                    ext = p.split(".")[-1].lower()
                    by_suffix[ext] = by_suffix.get(ext, 0) + 1
    if total_files == 0:
        return "无文件变更。"
    parts = [f"共 {total_files} 个文件"]
    for ext, count in sorted(by_suffix.items(), key=lambda x: -x[1])[:5]:
        parts.append(f"{ext} {count} 个")
    return "，".join(parts) + "。"


def build_notification_text(
    issue_key: str,
    cl_list: list,
    files_by_cl: list,
    failed_cls: list,
    jira_url: str = "",
    issue_title: str = "",
) -> str:
    """
    Build plain text for Feishu notification.
    files_by_cl: list of (cl, paths, submit_time, file_line_summaries).
    file_line_summaries: list of (depot_path, line_summary_str).
    """
    cl_str = "、".join(str(c) for c in cl_list)
    lines = [
        f"【Jira-P4 变更提醒】{issue_key}",
        f"【关联 P4 CL】{cl_str}",
        "",
    ]
    if issue_title:
        lines.append(f"标题：{issue_title}")
        lines.append("")
    lines.append("变更文件与行号：")
    if files_by_cl:
        for item in files_by_cl:
            cl = item[0]
            paths = item[1] if len(item) > 1 else []
            submit_time = item[2] if len(item) > 2 else ""
            file_line_summaries = item[3] if len(item) > 3 else []
            lines.append("")
            lines.append(f"【CL {cl}】" + (f"  提交时间：{submit_time}" if submit_time else ""))
            if file_line_summaries:
                for path, line_summary in file_line_summaries[:30]:
                    lines.append(f"    • {path}")
                    lines.append(f"      变动：{line_summary}")
                if len(file_line_summaries) > 30:
                    lines.append(f"    ... 该 CL 共 {len(file_line_summaries)} 个文件")
            else:
                for p in paths[:30]:
                    lines.append(f"    • {p}")
                if len(paths) > 30:
                    lines.append(f"    ... 该 CL 共 {len(paths)} 个文件")
        lines.append("")
        lines.append("变更分析：" + _brief_analysis(files_by_cl))
    else:
        lines.append("  （无）")

    if failed_cls:
        lines.append("")
        lines.append(f"以下 CL 查询失败: {', '.join(str(c) for c in failed_cls)}")

    if jira_url:
        lines.append("")
        lines.append(f"Jira: {jira_url}")
    return "\n".join(lines)


def build_notification_text_short(
    issue_key: str,
    cl_list: list,
    files_by_cl: list,
    failed_cls: list,
    jira_url: str = "",
    issue_title: str = "",
    doc_url: str = "",
    assignee_display_name: str = "",
    issue_status: str = "",
) -> str:
    """
    仅用于消息的简短版：标题、时间、CL 号、提交的文件列表、变更分析；不含 diff 内容。
    完整变更内容应写入云文档，并通过 doc_url 附带链接。
    """
    cl_str = "、".join(str(c) for c in cl_list)
    lines = [
        f"【Jira-P4 变更提醒】{issue_key}",
        f"【关联 P4 CL】{cl_str}",
        "",
    ]
    if issue_title:
        lines.append(f"标题：{issue_title}")
        lines.append("")
    if assignee_display_name:
        lines.append(f"经办人：{assignee_display_name}")
        lines.append("")
    if issue_status:
        lines.append(f"状态：{issue_status}")
        lines.append("")
    lines.append("变更文件：")
    if files_by_cl:
        for item in files_by_cl:
            cl = item[0]
            paths = item[1] if len(item) > 1 else []
            submit_time = item[2] if len(item) > 2 else ""
            file_line_summaries = item[3] if len(item) > 3 else []
            lines.append("")
            lines.append(f"【CL {cl}】" + (f"  提交时间：{submit_time}" if submit_time else ""))
            path_list = [p for p, _ in file_line_summaries] if file_line_summaries else paths
            for p in path_list[:50]:
                lines.append(f"    • {p}")
            if len(path_list) > 50:
                lines.append(f"    ... 该 CL 共 {len(path_list)} 个文件")
        lines.append("")
        lines.append("变更分析：" + _brief_analysis(files_by_cl))
    else:
        lines.append("  （无）")

    if failed_cls:
        lines.append("")
        lines.append(f"以下 CL 查询失败: {', '.join(str(c) for c in failed_cls)}")

    if doc_url:
        lines.append("")
        lines.append(f"详细变更内容（行级 diff、Excel 单元格等）见：{doc_url}")

    if jira_url:
        lines.append("")
        lines.append(f"Jira: {jira_url}")
    return "\n".join(lines)
