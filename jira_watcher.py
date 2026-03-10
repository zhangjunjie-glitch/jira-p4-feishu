# -*- coding: utf-8 -*-
"""
Jira 分配监控：常驻进程，按间隔轮询「分配给我」的工单，
对新分配或已更新的单子自动执行与 main.py 相同的流程并通知飞书群。
"""

import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Optional

from jira_client import (
    get_issues_assigned_to_me,
    get_issue_status_only,
    get_issue_assignee_and_status,
)
from main import load_config, run_single_issue_flow
from feishu_client import (
    get_tenant_access_token,
    get_wiki_node_obj_token,
    bitable_has_issue,
    bitable_list_records,
    bitable_update_record_fields,
    BITABLE_FIELD_ISSUE,
    BITABLE_FIELD_ASSIGNEE,
    BITABLE_FIELD_STATUS,
)


def _setup_logging(log_file: Optional[Path] = None) -> logging.Logger:
    """配置并返回 Watcher 使用的 logger，带时间戳与 [Watcher] 前缀。可同时输出到控制台和文件。"""
    log = logging.getLogger("jira_watcher")
    if log.handlers:
        return log
    log.setLevel(logging.DEBUG if os.environ.get("JIRA_WATCHER_DEBUG") else logging.INFO)
    fmt = logging.Formatter("[%(asctime)s] [Watcher] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    # 控制台
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    log.addHandler(console)
    # 文件（便于后台运行时查看）
    if log_file:
        try:
            fh = logging.FileHandler(log_file, mode="a", encoding="utf-8")
            fh.setFormatter(fmt)
            log.addHandler(fh)
        except Exception:
            pass
    return log


logger: logging.Logger = logging.getLogger("jira_watcher")  # run() 内会重新配置并覆盖


def load_state(state_path: Path) -> tuple:
    """
    加载状态：processed 与 completed_or_cancelled。
    Returns:
        (processed: dict, completed_or_cancelled: set)
        - processed: { issue_key: updated }
        - completed_or_cancelled: 处于「已完成/已取消」的单号集合，本轮及之后不再检测直到再次变为 Testing
    """
    processed = {}
    completed_or_cancelled = set()
    if not state_path.exists():
        return processed, completed_or_cancelled
    try:
        with open(state_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return processed, completed_or_cancelled
        processed = data.get("processed") or {}
        raw = data.get("completed_or_cancelled")
        if isinstance(raw, list):
            completed_or_cancelled = set(str(k) for k in raw if k)
        elif isinstance(raw, dict):
            completed_or_cancelled = set(str(k) for k in raw if k)
    except Exception:
        pass
    return processed, completed_or_cancelled


def save_state(
    state_path: Path, processed: dict, completed_or_cancelled: Optional[set] = None
) -> None:
    """持久化已处理记录与已完成/已取消跳过集合"""
    payload = {"processed": processed}
    if completed_or_cancelled is not None:
        payload["completed_or_cancelled"] = list(completed_or_cancelled)
    try:
        with open(state_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error("写入状态文件失败: %s", e)


def run() -> None:
    global logger
    root = Path(__file__).resolve().parent
    config = load_config()
    jira_cfg = config.get("jira") or {}
    watcher_cfg = config.get("watcher") or {}
    poll_interval = max(30, int(watcher_cfg.get("poll_interval_seconds") or 300))
    delay_after_issue = max(0, float(watcher_cfg.get("delay_after_issue_seconds") or 2))
    state_file = (watcher_cfg.get("state_file") or "").strip()
    state_path = Path(state_file) if state_file else root / "watcher_state.json"
    log_file_raw = os.environ.get("JIRA_WATCHER_LOG_FILE") or watcher_cfg.get("log_file") or ""
    log_path = Path(log_file_raw).resolve() if log_file_raw.strip() else root / "jira_watcher.log"
    logger = _setup_logging(log_path)
    jql_extra = (watcher_cfg.get("jql_extra") or "").strip()
    assignee_extra_raw = watcher_cfg.get("assignee_extra")
    if isinstance(assignee_extra_raw, list):
        assignee_extra = [str(x).strip() for x in assignee_extra_raw if (x or "").strip()]
    elif isinstance(assignee_extra_raw, str) and assignee_extra_raw.strip():
        assignee_extra = [x.strip() for x in assignee_extra_raw.split(",") if x.strip()]
    else:
        assignee_extra = []
    status_filter = (watcher_cfg.get("status_filter") or "").strip()
    if status_filter:
        safe_status = status_filter.replace('"', '\\"')
        jql_extra = f'AND status = "{safe_status}"' + (" " + jql_extra if jql_extra else "")
    no_notify_if_no_cl = watcher_cfg.get("no_notify_if_no_cl") is True
    skip_if_in_bitable = watcher_cfg.get("skip_if_in_bitable", True) is not False
    completed_statuses_raw = watcher_cfg.get("completed_statuses")
    if isinstance(completed_statuses_raw, list):
        completed_statuses = set(str(s).strip() for s in completed_statuses_raw if (s or "").strip())
    elif isinstance(completed_statuses_raw, str) and completed_statuses_raw.strip():
        completed_statuses = set(s.strip() for s in completed_statuses_raw.split(",") if s.strip())
    else:
        completed_statuses = {"已完成", "已取消"}

    if not jira_cfg.get("base_url") or not jira_cfg.get("email") or not jira_cfg.get("api_token"):
        logger.error("请配置 Jira (base_url, email, api_token)")
        sys.exit(1)
    if not jira_cfg.get("cl_custom_field_id"):
        logger.error("请配置 Jira 的 cl_custom_field_id")
        sys.exit(1)

    processed, completed_or_cancelled = load_state(state_path)
    logger.info("========  Jira 分配监控已启动  ========")
    logger.info("轮询间隔: %s 秒 | 状态文件: %s | 日志文件: %s", poll_interval, state_path, log_path)
    assignee_desc = "当前用户" + ((" + " + ", ".join(assignee_extra)) if assignee_extra else "")
    logger.info("已记录 %s 个已处理单子，%s 个已完成/已取消跳过；将按间隔轮询 Jira（经办人=%s%s）",
                len(processed), len(completed_or_cancelled), assignee_desc, ("，状态=" + status_filter) if status_filter else "")

    try:
        while True:
            try:
                logger.info("开始轮询 Jira（分配给我）...")
                issues, err = get_issues_assigned_to_me(
                    base_url=jira_cfg["base_url"],
                    email=jira_cfg["email"],
                    api_token=jira_cfg["api_token"],
                    jql_extra=jql_extra if jql_extra else None,
                    assignee_extra=assignee_extra if assignee_extra else None,
                    max_results=50,
                )
                if err:
                    logger.warning("Jira 查询失败: %s", err)
                else:
                    logger.info("轮询完成，共 %s 个分配给我的单子", len(issues))
                    if issues:
                        logger.debug("单子列表: %s", [k for k, _ in issues])
                    current_keys = {key for key, _ in issues}
                    need_run = 0
                    feishu_cfg = config.get("feishu") or {}
                    token = None
                    app_token = (feishu_cfg.get("bitable_app_token") or "").strip()
                    table_id = (feishu_cfg.get("bitable_table_id") or "").strip()
                    if skip_if_in_bitable and (app_token or (feishu_cfg.get("bitable_wiki_node_token") or "").strip()):
                        tok, _ = get_tenant_access_token(feishu_cfg.get("app_id") or "", feishu_cfg.get("app_secret") or "")
                        if tok:
                            token = tok
                            if not app_token:
                                wiki_node = (feishu_cfg.get("bitable_wiki_node_token") or "").strip()
                                if wiki_node:
                                    obj_token, _, _ = get_wiki_node_obj_token(token, wiki_node)
                                    if obj_token:
                                        app_token = obj_token
                    for issue_key, updated in issues:
                        if issue_key not in processed or (updated and updated > processed.get(issue_key, "")):
                            need_run += 1
                            if skip_if_in_bitable and token and app_token and table_id:
                                if bitable_has_issue(token, app_token, table_id, issue_key):
                                    logger.info("单子 %s 已存在于多维表格，跳过", issue_key)
                                    processed[issue_key] = updated or ""
                                    save_state(state_path, processed, completed_or_cancelled)
                                    if delay_after_issue > 0:
                                        time.sleep(delay_after_issue)
                                    continue
                            logger.info("处理单子: %s (updated=%s)", issue_key, updated or "-")
                            if run_single_issue_flow(issue_key, config, no_notify_if_no_cl=no_notify_if_no_cl):
                                processed[issue_key] = updated or ""
                                save_state(state_path, processed, completed_or_cancelled)
                                logger.info("单子 %s 处理完成，已更新状态", issue_key)
                            else:
                                logger.warning("单子 %s 处理失败，稍后重试", issue_key)
                            if delay_after_issue > 0:
                                time.sleep(delay_after_issue)
                    if need_run == 0 and issues:
                        logger.debug("本轮无需处理的单子（均已处理且无更新），跳过")
                    for key in list(processed.keys()):
                        if key not in current_keys:
                            del processed[key]
                            save_state(state_path, processed, completed_or_cancelled)
                            logger.info("单子 %s 已不再分配给我，已从状态移除", key)

                    if not token and (feishu_cfg.get("app_id") and feishu_cfg.get("app_secret")):
                        token, _ = get_tenant_access_token(
                            feishu_cfg.get("app_id") or "", feishu_cfg.get("app_secret") or ""
                        )
                    if token and not app_token and (feishu_cfg.get("bitable_wiki_node_token") or "").strip():
                        wiki_node = (feishu_cfg.get("bitable_wiki_node_token") or "").strip()
                        obj_token, _, _ = get_wiki_node_obj_token(token, wiki_node)
                        if obj_token:
                            app_token = obj_token
                    if token and app_token and table_id:
                        try:
                            items, list_err = bitable_list_records(token, app_token, table_id)
                            if list_err:
                                logger.debug("多维表格列出记录失败（状态同步跳过）: %s", list_err)
                            else:
                                issue_key_to_record = {}
                                for rec in items:
                                    rid = rec.get("record_id")
                                    fields = rec.get("fields") or {}
                                    issue_key = (fields.get(BITABLE_FIELD_ISSUE) or "").strip()
                                    if issue_key and rid:
                                        issue_key_to_record[issue_key] = (rid, fields)
                                for rec in items:
                                    rid = rec.get("record_id")
                                    fields = rec.get("fields") or {}
                                    issue_key = (fields.get(BITABLE_FIELD_ISSUE) or "").strip()
                                    if not issue_key or not rid:
                                        continue
                                    if issue_key in completed_or_cancelled:
                                        continue
                                    current_status = (fields.get(BITABLE_FIELD_STATUS) or "").strip()
                                    jira_status = get_issue_status_only(
                                        jira_cfg["base_url"], issue_key,
                                        jira_cfg["email"], jira_cfg["api_token"],
                                    )
                                    if jira_status is not None and jira_status != current_status:
                                        err = bitable_update_record_fields(
                                            token, app_token, table_id, rid,
                                            {BITABLE_FIELD_STATUS: jira_status},
                                        )
                                        if err:
                                            logger.debug("更新单号 %s 状态失败: %s", issue_key, err)
                                        else:
                                            logger.info("已同步单号 %s 状态为: %s", issue_key, jira_status)
                                    if jira_status is not None and jira_status in completed_statuses:
                                        completed_or_cancelled.add(issue_key)
                                        save_state(state_path, processed, completed_or_cancelled)
                                        logger.info("单号 %s 已为「%s」，后续不再检测直至再次变为 %s",
                                                    issue_key, jira_status, status_filter or "目标状态")
                                        if delay_after_issue > 0:
                                            time.sleep(delay_after_issue)
                                        continue
                                    current_assignee = (fields.get(BITABLE_FIELD_ASSIGNEE) or "").strip()
                                    if not current_assignee or not current_status:
                                        assignee, status = get_issue_assignee_and_status(
                                            jira_cfg["base_url"], issue_key,
                                            jira_cfg["email"], jira_cfg["api_token"],
                                        )
                                        backfill = {}
                                        if not current_assignee and assignee:
                                            backfill[BITABLE_FIELD_ASSIGNEE] = assignee
                                        if not current_status and status:
                                            backfill[BITABLE_FIELD_STATUS] = status
                                        if backfill:
                                            err = bitable_update_record_fields(
                                                token, app_token, table_id, rid, backfill,
                                            )
                                            if err:
                                                logger.debug("回填单号 %s 经办人/状态失败: %s", issue_key, err)
                                            else:
                                                logger.info("已回填单号 %s 经办人/状态", issue_key)
                                    if delay_after_issue > 0:
                                        time.sleep(delay_after_issue)
                                for issue_key in list(completed_or_cancelled):
                                    jira_status = get_issue_status_only(
                                        jira_cfg["base_url"], issue_key,
                                        jira_cfg["email"], jira_cfg["api_token"],
                                    )
                                    if jira_status is None:
                                        continue
                                    if jira_status in completed_statuses:
                                        continue
                                    rec_info = issue_key_to_record.get(issue_key)
                                    if not rec_info:
                                        continue
                                    rid, _ = rec_info
                                    err = bitable_update_record_fields(
                                        token, app_token, table_id, rid,
                                        {BITABLE_FIELD_STATUS: jira_status},
                                    )
                                    if err:
                                        logger.debug("单号 %s 恢复检测后更新状态失败: %s", issue_key, err)
                                    else:
                                        completed_or_cancelled.discard(issue_key)
                                        save_state(state_path, processed, completed_or_cancelled)
                                        logger.info("单号 %s 已变为「%s」，恢复检测", issue_key, jira_status)
                                    if delay_after_issue > 0:
                                        time.sleep(delay_after_issue)
                        except Exception as sync_ex:
                            logger.debug("状态同步/回填异常: %s", sync_ex)
            except Exception as e:
                logger.exception("本轮异常: %s", e)
            logger.info("下次轮询于 %s 秒后执行", poll_interval)
            time.sleep(poll_interval)
    except KeyboardInterrupt:
        logger.info("收到退出信号，已保存状态并退出")
        save_state(state_path, processed, completed_or_cancelled)


if __name__ == "__main__":
    run()
