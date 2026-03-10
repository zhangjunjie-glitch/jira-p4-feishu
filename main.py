# -*- coding: utf-8 -*-
"""
Jira + P4 + 飞书提醒工具入口。

用法: python main.py <Jira单号>
示例: python main.py PROJ-1234
"""

import argparse
import json
import os
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

from jira_client import get_issue_cls, get_issue_reporter
from p4_client import get_changed_files_for_cls, get_project_context
from feishu_client import (
    get_tenant_access_token,
    send_text_message,
    build_notification_text,
    build_notification_text_short,
    save_report_to_temp_file,
    create_feishu_doc_with_content,
    add_report_to_bitable,
    get_wiki_node_obj_token,
)
from ai_client import get_test_scope_suggestion


def load_config() -> dict:
    """Load config from config.json or .env. Keys normalized to nested dict."""
    root = Path(__file__).resolve().parent
    config = {
        "jira": {},
        "p4": {},
        "feishu": {},
    }

    # 1) config.json
    config_path = root / "config.json"
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            config["jira"] = data.get("jira") or {}
            config["p4"] = data.get("p4") or {}
            config["feishu"] = data.get("feishu") or {}
            config["ai"] = data.get("ai") or {}
            config["watcher"] = data.get("watcher") or {}
        except Exception as e:
            print(f"警告: 读取 config.json 失败: {e}", file=sys.stderr)

    # 2) .env override
    if load_dotenv is not None:
        env_path = root / ".env"
        if env_path.exists():
            load_dotenv(env_path)
    config["jira"]["base_url"] = os.environ.get("JIRA_BASE_URL") or config["jira"].get("base_url")
    config["jira"]["email"] = os.environ.get("JIRA_EMAIL") or config["jira"].get("email")
    config["jira"]["api_token"] = os.environ.get("JIRA_API_TOKEN") or config["jira"].get("api_token")
    config["jira"]["cl_custom_field_id"] = (
        os.environ.get("JIRA_CL_CUSTOM_FIELD_ID") or config["jira"].get("cl_custom_field_id")
    )
    config["p4"]["cwd"] = os.environ.get("P4_CWD") or config["p4"].get("cwd")
    config["feishu"]["app_id"] = os.environ.get("FEISHU_APP_ID") or config["feishu"].get("app_id")
    config["feishu"]["app_secret"] = os.environ.get("FEISHU_APP_SECRET") or config["feishu"].get("app_secret")
    config["feishu"]["receive_id"] = os.environ.get("FEISHU_RECEIVE_ID") or config["feishu"].get("receive_id")
    config["feishu"]["receive_id_type"] = (
        os.environ.get("FEISHU_RECEIVE_ID_TYPE") or config["feishu"].get("receive_id_type") or "chat_id"
    )
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
    config["ai"]["api_key"] = os.environ.get("AI_API_KEY") or os.environ.get("OPENAI_API_KEY") or (config["ai"].get("api_key") if config.get("ai") else None)
    config["ai"]["base_url"] = os.environ.get("AI_BASE_URL") or config["ai"].get("base_url")
    config["ai"]["model"] = os.environ.get("AI_MODEL") or config["ai"].get("model")
    config["ai"]["provider"] = os.environ.get("AI_PROVIDER") or config["ai"].get("provider") or ""
    config["watcher"] = config.get("watcher") or {}
    config["watcher"]["poll_interval_seconds"] = int(
        os.environ.get("JIRA_WATCHER_POLL_INTERVAL") or config["watcher"].get("poll_interval_seconds") or 300
    )
    config["watcher"]["state_file"] = (
        os.environ.get("JIRA_WATCHER_STATE_FILE") or config["watcher"].get("state_file") or ""
    )
    config["watcher"]["jql_extra"] = (
        os.environ.get("JIRA_WATCHER_JQL_EXTRA") or config["watcher"].get("jql_extra") or ""
    )
    config["watcher"]["status_filter"] = (
        os.environ.get("JIRA_WATCHER_STATUS_FILTER") or config["watcher"].get("status_filter") or ""
    )
    config["watcher"]["no_notify_if_no_cl"] = (
        os.environ.get("JIRA_WATCHER_NO_NOTIFY_IF_NO_CL", "").lower() in ("1", "true", "yes")
        or config["watcher"].get("no_notify_if_no_cl") is True
    )
    config["watcher"]["skip_if_in_bitable"] = (
        os.environ.get("JIRA_WATCHER_SKIP_IF_IN_BITABLE", "1").lower() not in ("0", "false", "no")
        and config["watcher"].get("skip_if_in_bitable", True) is not False
    )

    return config


def run_single_issue_flow(
    issue_key: str,
    config: dict,
    no_notify_if_no_cl: bool = False,
) -> bool:
    """
    对单个 Jira 单号执行完整流程：取 CL → P4 变更 → 项目上下文 → AI 测试范围 → Bitable/云文档 → 飞书群发消息。
    供 main.py 与 jira_watcher.py 复用。
    Returns:
        True 表示流程执行成功（含已发飞书），False 表示失败。
    """
    jira_cfg = config["jira"]
    p4_cwd = config["p4"].get("cwd")
    feishu_cfg = config["feishu"]

    issue, cl_list, jira_err = get_issue_cls(
        base_url=jira_cfg["base_url"],
        issue_key=issue_key,
        cl_custom_field_id=jira_cfg["cl_custom_field_id"],
        email=jira_cfg["email"],
        api_token=jira_cfg["api_token"],
    )
    if jira_err:
        print(f"错误: {jira_err}", file=sys.stderr)
        return False

    jira_url = f"{jira_cfg['base_url'].rstrip('/')}/browse/{issue_key}"
    issue_title = (issue or {}).get("fields", {}).get("summary", "").strip() if issue else ""
    issue_reporter = get_issue_reporter(issue) if issue else ""
    files_by_cl = None
    full_text = ""
    failed_cls = []

    if not cl_list:
        if no_notify_if_no_cl:
            return True
        text = f"【Jira-P4 变更提醒】{issue_key}\n\n"
        if issue_title:
            text += f"标题：{issue_title}\n\n"
        text += "该单号暂无关联的 P4 CL。\n\nJira: " + jira_url
    else:
        files_by_cl, failed_cls, p4_errors = get_changed_files_for_cls(cl_list, cwd=p4_cwd)
        for e in p4_errors:
            print(f"警告: {e}", file=sys.stderr)
        has_any_files = any((len(item) > 1 and item[1]) for item in files_by_cl)
        if not has_any_files and cl_list:
            if failed_cls:
                print("提示: P4 查询失败，请在有 P4 环境的工作目录下运行（或设置 .env 中 P4_CWD），并确保 p4 在 PATH 中。", file=sys.stderr)
            else:
                print("提示: 未解析到变更文件，可在终端执行 p4 describe <CL号> 查看输出格式。", file=sys.stderr)
        full_text = build_notification_text(
            issue_key=issue_key,
            cl_list=cl_list,
            files_by_cl=files_by_cl,
            failed_cls=failed_cls,
            jira_url=jira_url,
            issue_title=issue_title,
        )
        try:
            save_report_to_temp_file(issue_key, full_text)
        except Exception:
            pass

    token, token_err = get_tenant_access_token(
        feishu_cfg["app_id"],
        feishu_cfg["app_secret"],
    )
    if token_err:
        print(f"错误: {token_err}", file=sys.stderr)
        return False

    doc_url = ""
    test_scope = ""
    project_context = ""
    if files_by_cl:
        all_paths = []
        for item in files_by_cl:
            if len(item) > 1 and item[1]:
                all_paths.extend(item[1])
        if all_paths:
            try:
                project_context = get_project_context(all_paths, cwd=p4_cwd)
            except Exception:
                pass
    ai_cfg = config.get("ai") or {}
    if (ai_cfg.get("api_key") or "").strip() and full_text:
        try:
            test_scope = get_test_scope_suggestion(
                full_text,
                api_key=ai_cfg.get("api_key") or "",
                base_url=ai_cfg.get("base_url") or None,
                model=ai_cfg.get("model") or None,
                provider=ai_cfg.get("provider") or None,
                project_context=project_context or None,
            )
        except Exception as e:
            if os.environ.get("FEISHU_REPORT_DOC_DEBUG"):
                print(f"提示: AI 测试范围分析失败: {e}", file=sys.stderr)
    if cl_list and files_by_cl is not None and full_text:
        app_token = feishu_cfg.get("bitable_app_token") or ""
        table_id = feishu_cfg.get("bitable_table_id") or ""
        wiki_node = (feishu_cfg.get("bitable_wiki_node_token") or "").strip()
        if wiki_node and not app_token and token:
            obj_token, obj_type, err = get_wiki_node_obj_token(token, wiki_node)
            if obj_token and (obj_type == "bitable" or not obj_type):
                app_token = obj_token
            if err and os.environ.get("FEISHU_REPORT_DOC_DEBUG"):
                print(f"提示: wiki 节点解析: {err} (obj_type={obj_type})", file=sys.stderr)
        if app_token and table_id:
            doc_url, doc_err = add_report_to_bitable(
                token, app_token, table_id, issue_key, issue_title, cl_list, files_by_cl, full_text, issue_reporter, test_scope
            )
            if doc_err and os.environ.get("FEISHU_REPORT_DOC_DEBUG"):
                print(f"提示: 多维表格写入失败: {doc_err}", file=sys.stderr)
        else:
            doc_title = f"Jira-P4 变更 {issue_key}"
            doc_url, doc_err = create_feishu_doc_with_content(token, doc_title, full_text)
            if doc_err and os.environ.get("FEISHU_REPORT_DOC_DEBUG"):
                print(f"提示: 创建云文档失败: {doc_err}", file=sys.stderr)

    if cl_list:
        text = build_notification_text_short(
            issue_key=issue_key,
            cl_list=cl_list,
            files_by_cl=files_by_cl,
            failed_cls=failed_cls,
            jira_url=jira_url,
            issue_title=issue_title,
            doc_url=doc_url or "",
        )

    send_err = send_text_message(
        token=token,
        receive_id=feishu_cfg["receive_id"],
        text=text,
        receive_id_type=feishu_cfg["receive_id_type"],
    )
    if send_err:
        print(f"错误: {send_err}", file=sys.stderr)
        return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="根据 Jira 单号查 P4 变更并在飞书提醒")
    parser.add_argument("issue_key", help="Jira 单号，如 PROJ-1234")
    parser.add_argument(
        "--no-notify-if-no-cl",
        action="store_true",
        help="当未找到 CL 时不发送飞书通知（默认仍会发送一条「暂无关联 CL」的提醒）",
    )
    args = parser.parse_args()
    issue_key = args.issue_key.strip()

    config = load_config()
    jira_cfg = config["jira"]
    feishu_cfg = config["feishu"]

    if not jira_cfg.get("base_url") or not jira_cfg.get("email") or not jira_cfg.get("api_token"):
        print("错误: 请配置 Jira (base_url, email, api_token)，见 README 配置说明", file=sys.stderr)
        return 1
    if not jira_cfg.get("cl_custom_field_id"):
        print("错误: 请配置 Jira 的 CL 自定义字段 id (cl_custom_field_id)", file=sys.stderr)
        return 1
    if not feishu_cfg.get("app_id") or not feishu_cfg.get("app_secret") or not feishu_cfg.get("receive_id"):
        print("错误: 请配置飞书 (app_id, app_secret, receive_id)", file=sys.stderr)
        return 1

    ok = run_single_issue_flow(issue_key, config, no_notify_if_no_cl=args.no_notify_if_no_cl)
    if ok:
        print("已发送飞书提醒。")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
