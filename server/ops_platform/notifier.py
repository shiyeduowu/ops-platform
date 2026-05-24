# -*- coding: utf-8 -*-
"""
告警通知服务

支持钉钉、企业微信、邮件等通知渠道
"""

import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional
from datetime import datetime, timezone

import httpx

logger = logging.getLogger(__name__)


class NotificationChannel:
    """通知渠道基类"""

    def send(self, title: str, content: str, **kwargs) -> bool:
        raise NotImplementedError


class DingTalkChannel(NotificationChannel):
    """钉钉机器人"""

    def __init__(self, webhook_url: str, secret: Optional[str] = None):
        self.webhook_url = webhook_url
        self.secret = secret

    def send(self, title: str, content: str, **kwargs) -> bool:
        try:
            payload = {
                "msgtype": "markdown",
                "markdown": {
                    "title": title,
                    "text": f"## {title}\n\n{content}"
                }
            }

            with httpx.Client(timeout=10) as client:
                resp = client.post(self.webhook_url, json=payload)
                data = resp.json()

            if data.get("errcode") == 0:
                logger.info(f"钉钉通知发送成功: {title}")
                return True
            else:
                logger.error(f"钉钉通知发送失败: {data}")
                return False

        except Exception as e:
            logger.error(f"钉钉通知异常: {e}")
            return False


class WeComChannel(NotificationChannel):
    """企业微信机器人"""

    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    def send(self, title: str, content: str, **kwargs) -> bool:
        try:
            payload = {
                "msgtype": "markdown",
                "markdown": {
                    "content": f"## {title}\n\n{content}"
                }
            }

            with httpx.Client(timeout=10) as client:
                resp = client.post(self.webhook_url, json=payload)
                data = resp.json()

            if data.get("errcode") == 0:
                logger.info(f"企业微信通知发送成功: {title}")
                return True
            else:
                logger.error(f"企业微信通知发送失败: {data}")
                return False

        except Exception as e:
            logger.error(f"企业微信通知异常: {e}")
            return False


class FeishuChannel(NotificationChannel):
    """飞书机器人"""

    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    def send(self, title: str, content: str, **kwargs) -> bool:
        try:
            payload = {
                "msg_type": "interactive",
                "card": {
                    "header": {
                        "title": {"tag": "plain_text", "content": title},
                        "template": "red"
                    },
                    "elements": [
                        {
                            "tag": "markdown",
                            "content": content
                        }
                    ]
                }
            }

            with httpx.Client(timeout=10) as client:
                resp = client.post(self.webhook_url, json=payload)
                data = resp.json()

            if data.get("code") == 0:
                logger.info(f"飞书通知发送成功: {title}")
                return True
            else:
                logger.error(f"飞书通知发送失败: {data}")
                return False

        except Exception as e:
            logger.error(f"飞书通知异常: {e}")
            return False


class EmailChannel(NotificationChannel):
    """邮件通知"""

    def __init__(self, smtp_host: str, smtp_port: int, username: str, password: str,
                 use_tls: bool = True, from_addr: str = None, to_addrs: list[str] = None):
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.username = username
        self.password = password
        self.use_tls = use_tls
        self.from_addr = from_addr or username
        self.to_addrs = to_addrs or []

    def send(self, title: str, content: str, **kwargs) -> bool:
        to_addrs = kwargs.get("to_addrs") or self.to_addrs
        if not to_addrs:
            logger.error("邮件通知缺少收件人")
            return False

        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = title
            msg["From"] = self.from_addr
            msg["To"] = ", ".join(to_addrs)

            # HTML 内容
            html_content = content.replace("\n", "<br>")
            msg.attach(MIMEText(html_content, "html", "utf-8"))

            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                if self.use_tls:
                    server.starttls()
                server.login(self.username, self.password)
                server.sendmail(self.from_addr, to_addrs, msg.as_string())

            logger.info(f"邮件通知发送成功: {title} -> {to_addrs}")
            return True

        except Exception as e:
            logger.error(f"邮件通知异常: {e}")
            return False


class WebhookChannel(NotificationChannel):
    """自定义 Webhook"""

    def __init__(self, webhook_url: str, method: str = "POST",
                 headers: dict = None, template: str = None):
        self.webhook_url = webhook_url
        self.method = method
        self.headers = headers or {}
        self.template = template

    def send(self, title: str, content: str, **kwargs) -> bool:
        try:
            if self.template:
                import json
                safe_title = json.dumps(title)[1:-1]
                safe_content = json.dumps(content)[1:-1]
                body = self.template.replace("{{title}}", safe_title).replace("{{content}}", safe_content)
                payload = json.loads(body)
            else:
                payload = {
                    "title": title,
                    "content": content,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }

            with httpx.Client(timeout=10) as client:
                if self.method.upper() == "POST":
                    resp = client.post(self.webhook_url, json=payload, headers=self.headers)
                else:
                    resp = client.get(self.webhook_url, params=payload, headers=self.headers)

            if resp.status_code < 400:
                logger.info(f"Webhook通知发送成功: {title}")
                return True
            else:
                logger.error(f"Webhook通知发送失败: {resp.status_code}")
                return False

        except Exception as e:
            logger.error(f"Webhook通知异常: {e}")
            return False


class CustomHTTPChannel(NotificationChannel):
    """自定义 HTTP 通知 — 用户完全控制 URL、方法、Headers、Body 模板"""

    # 可用模板变量
    AVAILABLE_VARS = [
        "alert_id", "alert_type", "severity", "hostname", "agent_id",
        "message", "timestamp", "fingerprint", "details_json",
        "title", "content",
    ]

    # 默认请求体模板
    DEFAULT_BODY_TEMPLATE = (
        '{\n'
        '  "alert_id": "{{alert_id}}",\n'
        '  "type": "{{alert_type}}",\n'
        '  "severity": "{{severity}}",\n'
        '  "hostname": "{{hostname}}",\n'
        '  "agent_id": "{{agent_id}}",\n'
        '  "message": "{{message}}",\n'
        '  "timestamp": "{{timestamp}}",\n'
        '  "title": "{{title}}",\n'
        '  "content": "{{content}}",\n'
        '  "details": {{details_json}}\n'
        '}'
    )

    def __init__(self, url: str, method: str = "POST", headers: dict = None,
                 body_template: str = None, timeout: int = 15):
        self.url = url
        self.method = method.upper()
        self.headers = headers or {}
        self.body_template = body_template
        self.timeout = min(max(5, timeout), 60)

    def send(self, title: str, content: str, **kwargs) -> bool:
        import json as _json

        variables = {
            "alert_id": str(kwargs.get("alert_id", "")),
            "alert_type": kwargs.get("alert_type", ""),
            "severity": kwargs.get("severity", ""),
            "hostname": kwargs.get("hostname", ""),
            "agent_id": kwargs.get("agent_id", ""),
            "message": kwargs.get("message", title),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "fingerprint": str(kwargs.get("fingerprint", "")),
            "details_json": _json.dumps(kwargs.get("details", {}), ensure_ascii=False) if kwargs.get("details") else "{}",
            "title": title,
            "content": content,
        }

        try:
            template = self.body_template or self.DEFAULT_BODY_TEMPLATE
            body_str = self._render_template(template, variables)
            # 尝试解析为 JSON；如果失败则作为纯文本发送
            try:
                payload = _json.loads(body_str)
            except _json.JSONDecodeError:
                payload = body_str

            with httpx.Client(timeout=self.timeout) as client:
                if self.method == "GET":
                    resp = client.get(self.url, params=payload if isinstance(payload, dict) else {}, headers=self.headers)
                elif self.method in ("POST", "PUT", "PATCH"):
                    method_fn = getattr(client, self.method.lower())
                    if isinstance(payload, dict):
                        resp = method_fn(self.url, json=payload, headers=self.headers)
                    else:
                        resp = method_fn(self.url, content=body_str.encode("utf-8"), headers=self.headers)
                else:
                    logger.error(f"不支持的 HTTP 方法: {self.method}")
                    return False

            if resp.status_code < 400:
                logger.info(f"自定义 HTTP 通知发送成功: {resp.status_code}")
                return True
            else:
                logger.error(f"自定义 HTTP 通知发送失败: {resp.status_code} {resp.text[:200]}")
                return False

        except Exception as e:
            logger.error(f"自定义 HTTP 通知异常: {e}")
            return False

    @staticmethod
    def _render_template(template: str, variables: dict) -> str:
        result = template
        for key, value in variables.items():
            result = result.replace("{{" + key + "}}", str(value))
        return result


def create_channel(channel_type: str, config: dict) -> Optional[NotificationChannel]:
    """
    根据配置创建通知渠道

    Args:
        channel_type: 渠道类型 (dingtalk/wecom/feishu/email/webhook)
        config: 渠道配置

    Returns:
        通知渠道实例
    """
    if channel_type == "dingtalk":
        return DingTalkChannel(
            webhook_url=config["webhook_url"],
            secret=config.get("secret")
        )
    elif channel_type == "wecom":
        return WeComChannel(webhook_url=config["webhook_url"])
    elif channel_type == "feishu":
        return FeishuChannel(webhook_url=config["webhook_url"])
    elif channel_type == "email":
        # to 字段支持字符串或列表
        to = config.get("to", "")
        to_addrs = [addr.strip() for addr in to.split(",")] if isinstance(to, str) else (to if isinstance(to, list) else [])
        return EmailChannel(
            smtp_host=config["smtp_host"],
            smtp_port=config.get("smtp_port", 587),
            username=config["username"],
            password=config["password"],
            use_tls=config.get("use_tls", True),
            from_addr=config.get("from_addr"),
            to_addrs=to_addrs,
        )
    elif channel_type == "webhook":
        return WebhookChannel(
            webhook_url=config["webhook_url"],
            method=config.get("method", "POST"),
            headers=config.get("headers"),
            template=config.get("template")
        )
    elif channel_type == "custom_http":
        return CustomHTTPChannel(
            url=config["url"],
            method=config.get("method", "POST"),
            headers=config.get("headers"),
            body_template=config.get("body_template"),
            timeout=config.get("timeout", 15),
        )
    else:
        logger.error(f"未知的通知渠道类型: {channel_type}")
        return None


def format_alert_message(alert_data: dict) -> tuple[str, str]:
    """
    格式化告警消息

    Args:
        alert_data: 告警数据

    Returns:
        (标题, 内容) 元组
    """
    severity = alert_data.get("severity", "warning")
    severity_map = {
        "critical": "紧急",
        "warning": "警告",
        "info": "信息"
    }
    severity_text = severity_map.get(severity, severity)

    title = f"[{severity_text}] {alert_data.get('type', '未知告警')}"

    content = f"""
**告警类型**: {alert_data.get('type', '-')}
**严重级别**: {severity_text}
**主机名**: {alert_data.get('hostname', '-')}
**Agent ID**: {alert_data.get('agent_id', '-')}
**告警信息**: {alert_data.get('message', '-')}
**触发时间**: {alert_data.get('created_at', datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S'))}
"""

    details = alert_data.get("details")
    if details:
        content += f"\n**详细信息**: {details}"

    return title, content
