# -*- coding: utf-8 -*-
"""
使用飞书官方 SDK「长连接」接收事件：在群内 @ 机器人并发送 Jira 单号，机器人回复变更内容。

无需公网地址、ngrok，只需在飞书开放平台选择「使用长连接接收事件」并运行本脚本。
依赖: pip install lark-oapi
"""

import json
import os
import sys
import threading
from pathlib import Path

# 先加载 .env，这样 FEISHU_BOT_DEBUG 等可写在 .env 里
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent / ".env")
except ImportError:
    pass

# 复用 bot_server 的配置与处理逻辑
from bot_server import load_config, handle_message_event

try:
    import lark_oapi as lark
except ImportError:
    print("请先安装飞书官方 SDK: pip install lark-oapi", file=sys.stderr)
    sys.exit(1)


def _get_text_from_content(content) -> str:
    """从消息 content（JSON 字符串或 dict）中取出 text。"""
    if not content:
        return ""
    try:
        obj = json.loads(content) if isinstance(content, str) else content
        return (obj.get("text") or "").strip()
    except Exception:
        return ""


def _handle_message_payload(message_id: str, text: str) -> None:
    """统一入口：拿到 message_id 和文本后，在后台线程里查 Jira/P4 并回复。"""
    def _run():
        try:
            handle_message_event(message_id, text)
        except Exception as e:
            print(f"[Bot] 处理/回复失败: {e}", flush=True)
            import traceback
            traceback.print_exc()
    threading.Thread(target=_run, daemon=True).start()


def _parse_message_and_reply(data) -> bool:
    """从事件 data 中解析 message_id 和 content 文本。成功解析并已提交后台返回 True。"""
    debug = (os.environ.get("FEISHU_BOT_DEBUG", "").strip().lower() in ("1", "true", "yes"))
    if debug and hasattr(lark, "JSON") and hasattr(lark.JSON, "marshal"):
        try:
            print("[Bot] 收到消息事件 raw:", lark.JSON.marshal(data, indent=2)[:800], flush=True)
        except Exception:
            print("[Bot] 收到消息事件 data type:", type(data), flush=True)

    message_id = ""
    text = ""
    try:
        if hasattr(data, "message"):
            msg = data.message
            message_id = getattr(msg, "message_id", "") or ""
            content = getattr(msg, "content", "") or ""
        elif hasattr(data, "event") and hasattr(data.event, "message"):
            msg = data.event.message
            message_id = getattr(msg, "message_id", "") or ""
            content = getattr(msg, "content", "") or ""
        elif hasattr(data, "message_id"):
            message_id = getattr(data, "message_id", "") or ""
            content = getattr(data, "content", "") or ""
        else:
            raw = getattr(data, "raw", None) or getattr(data, "data", data)
            if hasattr(raw, "get"):
                msg = raw.get("message", raw)
                message_id = msg.get("message_id", "") if hasattr(msg, "get") else ""
                content = msg.get("content", "{}") if hasattr(msg, "get") else "{}"
            else:
                try:
                    s = lark.JSON.marshal(data)
                    obj = json.loads(s) if isinstance(s, str) else s
                    msg = (obj.get("event") or obj).get("message") or obj
                    message_id = msg.get("message_id", "")
                    content = msg.get("content", "{}")
                except Exception:
                    content = "{}"
        text = _get_text_from_content(content)
        message_id = str(message_id).strip()
        if debug:
            print(f"[Bot] 解析结果 message_id={message_id!r} text={text!r}", flush=True)
    except Exception as e:
        print(f"[Bot] 解析消息失败: {e}", flush=True)
        import traceback
        traceback.print_exc()
        return False
    if not message_id:
        print("[Bot] 未解析到 message_id，已忽略（可设 FEISHU_BOT_DEBUG=1 查看原始数据）", flush=True)
        return False
    _handle_message_payload(message_id, text)
    return True


def _on_message(data) -> None:
    """收到消息时由 SDK 调用（P2 / im.message.receive_v1）。"""
    _parse_message_and_reply(data)


def main():
    config = load_config()
    app_id = config.get("feishu", {}).get("app_id") or ""
    app_secret = config.get("feishu", {}).get("app_secret") or ""
    if not app_id or not app_secret:
        print("错误: 请在 .env 或 config.json 中配置 FEISHU_APP_ID、FEISHU_APP_SECRET", file=sys.stderr)
        sys.exit(1)

    # 长连接无需 encrypt_key / verification_token，传空即可；im.message.receive_v1 与 P2 为同一事件，只注册一次
    event_handler = (
        lark.EventDispatcherHandler.builder("", "")
        .register_p2_im_message_receive_v1(_on_message)
        .build()
    )

    log_level = lark.LogLevel.DEBUG if os.environ.get("FEISHU_BOT_DEBUG") else lark.LogLevel.INFO
    cli = lark.ws.Client(
        app_id,
        app_secret,
        event_handler=event_handler,
        log_level=log_level,
    )
    print("飞书长连接已启动。请在群内 @ 机器人并发送 Jira 单号（如 DING-154167）。若无反应可设 FEISHU_BOT_DEBUG=1 再运行查看日志。", file=sys.stderr)
    cli.start()


if __name__ == "__main__":
    main()
