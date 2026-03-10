# -*- coding: utf-8 -*-
"""
飞书事件订阅服务：在群内 @ 机器人并发送 Jira 单号，机器人回复该单号的 P4 变更内容。

启动后需在飞书开放平台配置「事件订阅」请求 URL，并订阅「接收消息」。
"""

import json
import os
import re
import threading
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

from flask import Flask, request, jsonify

from jira_client import get_issue_cls, get_issue_reporter, get_issue_assignee, get_issue_status
from p4_client import get_changed_files_for_cls, get_project_context
from feishu_client import (
    get_tenant_access_token,
    reply_to_message,
    reply_to_message_post_with_at,
    build_notification_text,
    build_notification_text_short,
    create_feishu_doc_with_content,
    add_report_to_bitable,
    get_wiki_node_obj_token,
)
from ai_client import get_test_scope_suggestion

# Jira 单号格式：项目键 + 数字，如 DING-154167、PROJ-123
JIRA_KEY_PATTERN = re.compile(r"[A-Z][A-Z0-9]+-\d+", re.IGNORECASE)


def load_config() -> dict:
    """与 main.py 一致的配置加载逻辑。"""
    root = Path(__file__).resolve().parent
    config = {"jira": {}, "p4": {}, "feishu": {}}

    config_path = root / "config.json"
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            config["jira"] = data.get("jira") or {}
            config["p4"] = data.get("p4") or {}
            config["feishu"] = data.get("feishu") or {}
            config["ai"] = data.get("ai") or {}
        except Exception:
            pass

    if load_dotenv is not None:
        load_dotenv(root / ".env")

    config["jira"]["base_url"] = os.environ.get("JIRA_BASE_URL") or config["jira"].get("base_url")
    config["jira"]["email"] = os.environ.get("JIRA_EMAIL") or config["jira"].get("email")
    config["jira"]["api_token"] = os.environ.get("JIRA_API_TOKEN") or config["jira"].get("api_token")
    config["jira"]["cl_custom_field_id"] = (
        os.environ.get("JIRA_CL_CUSTOM_FIELD_ID") or config["jira"].get("cl_custom_field_id")
    )
    config["p4"]["cwd"] = os.environ.get("P4_CWD") or config["p4"].get("cwd")
    config["feishu"]["app_id"] = os.environ.get("FEISHU_APP_ID") or config["feishu"].get("app_id")
    config["feishu"]["app_secret"] = os.environ.get("FEISHU_APP_SECRET") or config["feishu"].get("app_secret")
    config["feishu"]["bitable_app_token"] = (
        os.environ.get("FEISHU_BITABLE_APP_TOKEN") or config["feishu"].get("bitable_app_token")
    )
    config["feishu"]["bitable_table_id"] = (
        os.environ.get("FEISHU_BITABLE_TABLE_ID") or config["feishu"].get("bitable_table_id")
    )
    config["feishu"]["bitable_wiki_node_token"] = (
        os.environ.get("FEISHU_BITABLE_WIKI_NODE_TOKEN") or config["feishu"].get("bitable_wiki_node_token")
    )
    config["ai"] = config.get("ai") or {}
    config["ai"]["api_key"] = os.environ.get("AI_API_KEY") or os.environ.get("OPENAI_API_KEY") or config["ai"].get("api_key")
    config["ai"]["base_url"] = os.environ.get("AI_BASE_URL") or config["ai"].get("base_url")
    config["ai"]["model"] = os.environ.get("AI_MODEL") or config["ai"].get("model")

    return config


def extract_jira_key(text: str):
    """从消息文本中提取第一个 Jira 单号。"""
    if not text or not text.strip():
        return None
    m = JIRA_KEY_PATTERN.search(text.strip())
    return m.group(0).upper() if m else None


def handle_message_event(message_id: str, content_text: str) -> None:
    """在后台线程中：根据消息内容查 Jira/P4 并回复。"""
    config = load_config()
    jira_cfg = config["jira"]
    p4_cwd = config["p4"].get("cwd")
    feishu_cfg = config["feishu"]

    reply = None
    issue_key = extract_jira_key(content_text)
    cl_list = []
    files_by_cl = None
    failed_cls = []
    jira_url = ""
    issue_title = ""
    issue_reporter = ""
    issue_assignee = ""
    issue_status = ""
    full_text = ""

    if not issue_key:
        reply = "请发送 Jira 单号，例如：DING-154167"
    else:
        issue, cl_list, jira_err = get_issue_cls(
            base_url=jira_cfg.get("base_url", ""),
            issue_key=issue_key,
            cl_custom_field_id=jira_cfg.get("cl_custom_field_id", ""),
            email=jira_cfg.get("email", ""),
            api_token=jira_cfg.get("api_token", ""),
        )
        if jira_err:
            reply = f"查询 Jira 失败：{jira_err}"
        else:
            jira_url = f"{jira_cfg['base_url'].rstrip('/')}/browse/{issue_key}"
            issue_title = (issue or {}).get("fields", {}).get("summary", "").strip() if issue else ""
            issue_reporter = get_issue_reporter(issue) if issue else ""
            issue_assignee = get_issue_assignee(issue) if issue else ""
            issue_status = get_issue_status(issue) if issue else ""
            if not cl_list:
                reply = None
            else:
                files_by_cl, failed_cls, _ = get_changed_files_for_cls(cl_list, cwd=p4_cwd)
                full_text = build_notification_text(
                    issue_key=issue_key,
                    cl_list=cl_list,
                    files_by_cl=files_by_cl,
                    failed_cls=failed_cls,
                    jira_url=jira_url,
                    issue_title=issue_title,
                )
                reply = None

    token, token_err = get_tenant_access_token(
        feishu_cfg.get("app_id", ""),
        feishu_cfg.get("app_secret", ""),
    )
    if token_err:
        reply = f"飞书鉴权失败：{token_err}"
    if not token:
        print(f"[Bot] 无法回复（无 token）: {reply[:80] if reply else 'N/A'}", flush=True)
        return

    # 有 CL 时：可选获取项目结构上下文，再 AI 分析测试范围
    test_scope = ""
    project_context = ""
    if reply is None and files_by_cl:
        all_paths = []
        for item in files_by_cl:
            if len(item) > 1 and item[1]:
                all_paths.extend(item[1])
        if all_paths:
            try:
                project_context = get_project_context(all_paths, cwd=p4_cwd)
            except Exception:
                pass
    if reply is None and full_text and (config.get("ai") or {}).get("api_key"):
        try:
            ai_cfg = config.get("ai") or {}
            test_scope = get_test_scope_suggestion(
                full_text,
                api_key=ai_cfg.get("api_key") or "",
                base_url=ai_cfg.get("base_url") or None,
                model=ai_cfg.get("model") or None,
                project_context=project_context or None,
            )
        except Exception:
            pass
    doc_url = ""
    app_token = feishu_cfg.get("bitable_app_token") or ""
    table_id = feishu_cfg.get("bitable_table_id") or ""
    wiki_node = (feishu_cfg.get("bitable_wiki_node_token") or "").strip()
    if wiki_node and not app_token and token:
        obj_token, obj_type, _ = get_wiki_node_obj_token(token, wiki_node)
        if obj_token and (obj_type == "bitable" or not obj_type):
            app_token = obj_token
    if reply is None and token and app_token and table_id:
        tenant_base = (feishu_cfg.get("tenant_base_url") or "").strip()
        view_id = (feishu_cfg.get("bitable_view_id") or "").strip()
        doc_url, _ = add_report_to_bitable(
            token, app_token, table_id, issue_key, issue_title,
            cl_list or [], files_by_cl or [], full_text, issue_reporter, test_scope,
            issue_assignee=issue_assignee,
            issue_status=issue_status,
            wiki_node_token=wiki_node or None,
            view_id=view_id or None,
            tenant_base_url=tenant_base or None,
        )
    elif reply is None and cl_list and full_text:
        doc_title = f"Jira-P4 变更 {issue_key}"
        doc_url, _ = create_feishu_doc_with_content(token, doc_title, full_text)

    if reply is None and cl_list:
        reply = build_notification_text_short(
            issue_key=issue_key,
            cl_list=cl_list,
            files_by_cl=files_by_cl,
            failed_cls=failed_cls,
            jira_url=jira_url,
            issue_title=issue_title,
            doc_url=doc_url or "",
            assignee_display_name=issue_assignee,
            issue_status=issue_status,
        )
    elif reply is None and not cl_list and issue_key:
        reply = f"【Jira-P4 变更提醒】{issue_key}\n\n"
        if issue_title:
            reply += f"标题：{issue_title}\n\n"
        if issue_assignee:
            reply += f"经办人：{issue_assignee}\n\n"
        if issue_status:
            reply += f"状态：{issue_status}\n\n"
        reply += "该单号暂无关联的 P4 CL。"
        if doc_url:
            reply += f"\n\n详细内容见：{doc_url}"
        reply += f"\n\nJira: {jira_url}"

    if reply is not None:
        assignee_open_id_map = feishu_cfg.get("assignee_open_id_map") or {}
        at_open_id = assignee_open_id_map.get(issue_assignee) if isinstance(assignee_open_id_map, dict) else None
        if at_open_id:
            err = reply_to_message_post_with_at(token, message_id, reply, [at_open_id])
        else:
            err = reply_to_message(token, message_id, reply)
        if err:
            print(f"[Bot] 回复消息失败: {err}", flush=True)


app = Flask(__name__)


@app.route("/feishu_event", methods=["GET", "POST"])
def feishu_event():
    """飞书事件订阅回调：URL 校验 + 接收消息后异步处理并回复。"""
    if request.method == "GET":
        return "ok"

    try:
        body = request.get_json(force=True, silent=True) or {}
    except Exception:
        return jsonify({"error": "invalid json"}), 400

    # 1) URL 校验（飞书配置请求地址时发送）
    if body.get("type") == "url_verification":
        challenge = body.get("challenge", "")
        return jsonify({"challenge": challenge})

    # 2) 事件回调（2.0 协议）
    if body.get("type") == "event_callback":
        event = body.get("event", {})
        if event.get("type") != "im.message.receive_v1":
            return jsonify({"ok": True})

        msg = event.get("message", {})
        message_id = msg.get("message_id")
        if not message_id:
            return jsonify({"ok": True})

        content = msg.get("content", "{}")
        try:
            content_obj = json.loads(content) if isinstance(content, str) else content
            text = content_obj.get("text", "").strip()
        except Exception:
            text = ""

        # 异步执行查询并回复，避免超时
        threading.Thread(target=handle_message_event, args=(message_id, text)).start()
        return jsonify({"ok": True})

    return jsonify({"ok": True})


if __name__ == "__main__":
    import sys

    port = int(os.environ.get("PORT", "9000"))
    host = os.environ.get("HOST", "0.0.0.0")
    print(f"飞书事件服务: http://{host}:{port}/feishu_event", file=sys.stderr)
    print("在飞书开放平台将「事件订阅」请求 URL 配置为此地址（需 HTTPS，内网可用 ngrok 等）", file=sys.stderr)
    app.run(host=host, port=port, debug=False, threaded=True)
