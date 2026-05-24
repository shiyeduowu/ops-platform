# -*- coding: utf-8 -*-
"""
功能测试脚本

测试所有新增功能是否正常工作
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ops_platform.models import (
    NotificationChannel, AuditLog, MetricHistory,
    Alert, Log, Agent, AgentConfig, Tenant, User, Base
)
from ops_platform.notifier import (
    DingTalkChannel, WeComChannel, FeishuChannel,
    EmailChannel, WebhookChannel, create_channel, format_alert_message
)
from ops_platform.core.utils import next_version


def test_models():
    """测试模型定义"""
    print("=" * 50)
    print("测试模型定义...")

    # 检查所有模型都有 __tablename__
    models = [NotificationChannel, AuditLog, MetricHistory, Alert, Log, Agent, AgentConfig, Tenant, User]
    for model in models:
        assert hasattr(model, '__tablename__'), f"{model.__name__} 缺少 __tablename__"
        print(f"  [OK] {model.__name__} -> {model.__tablename__}")

    print("模型定义测试通过!\n")


def test_notifier():
    """测试通知服务"""
    print("=" * 50)
    print("测试通知服务...")

    # 测试创建渠道
    channel = create_channel("dingtalk", {"webhook_url": "https://oapi.dingtalk.com/robot/send?access_token=test"})
    assert isinstance(channel, DingTalkChannel), "钉钉渠道创建失败"
    print("  [OK] 钉钉渠道创建成功")

    channel = create_channel("wecom", {"webhook_url": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=test"})
    assert isinstance(channel, WeComChannel), "企微渠道创建失败"
    print("  [OK] 企业微信渠道创建成功")

    channel = create_channel("feishu", {"webhook_url": "https://open.feishu.cn/open-apis/bot/v2/hook/test"})
    assert isinstance(channel, FeishuChannel), "飞书渠道创建失败"
    print("  [OK] 飞书渠道创建成功")

    channel = create_channel("email", {
        "smtp_host": "smtp.example.com",
        "username": "test@example.com",
        "password": "password"
    })
    assert isinstance(channel, EmailChannel), "邮件渠道创建失败"
    print("  [OK] 邮件渠道创建成功")

    channel = create_channel("webhook", {"webhook_url": "https://example.com/webhook"})
    assert isinstance(channel, WebhookChannel), "Webhook渠道创建失败"
    print("  [OK] Webhook渠道创建成功")

    # 测试消息格式化
    title, content = format_alert_message({
        "type": "CPU过高",
        "severity": "critical",
        "hostname": "server-01",
        "agent_id": "agent-001",
        "message": "CPU使用率超过90%",
    })
    assert "紧急" in title, "告警标题格式错误"
    assert "CPU过高" in content, "告警内容格式错误"
    print("  [OK] 告警消息格式化正确")

    print("通知服务测试通过!\n")


def test_utils():
    """测试工具函数"""
    print("=" * 50)
    print("测试工具函数...")

    assert next_version(None) == "v1", "next_version(None) 应返回 v1"
    assert next_version("v1") == "v2", "next_version('v1') 应返回 v2"
    assert next_version("v9") == "v10", "next_version('v9') 应返回 v10"
    assert next_version("v1.1") == "v1.1.1", "next_version('v1.1') 应返回 v1.1.1"
    print("  [OK] next_version 函数正确")

    print("工具函数测试通过!\n")


def test_config_validation():
    """测试配置验证"""
    print("=" * 50)
    print("测试配置验证...")

    from ops_platform.api.v1.routes.notifications import _validate_config

    # 测试钉钉配置验证
    try:
        _validate_config("dingtalk", {})
        assert False, "应该抛出异常"
    except Exception as e:
        assert "webhook_url" in str(e), "错误信息应包含 webhook_url"
    print("  [OK] 钉钉配置验证正确")

    # 测试邮件配置验证
    try:
        _validate_config("email", {"smtp_host": "smtp.example.com"})
        assert False, "应该抛出异常"
    except Exception as e:
        assert "username" in str(e), "错误信息应包含 username"
    print("  [OK] 邮件配置验证正确")

    # 测试有效配置
    _validate_config("dingtalk", {"webhook_url": "https://example.com"})
    print("  [OK] 有效配置验证通过")

    print("配置验证测试通过!\n")


def test_api_imports():
    """测试API路由导入"""
    print("=" * 50)
    print("测试API路由导入...")

    from ops_platform.api.v1.routes.notifications import router as nc_router
    assert nc_router.prefix == "/notifications", "通知路由前缀错误"
    print(f"  [OK] 通知渠道路由: {nc_router.prefix}")

    from ops_platform.api.v1.routes.audit import router as audit_router
    assert audit_router.prefix == "/audit", "审计路由前缀错误"
    print(f"  [OK] 审计日志路由: {audit_router.prefix}")

    from ops_platform.api.v1.routes.template import router as template_router
    assert template_router.prefix == "/template", "模板路由前缀错误"
    print(f"  [OK] 模板生成器路由: {template_router.prefix}")

    from ops_platform.api.v1.routes.logs import router as logs_router
    assert logs_router.prefix == "/logs", "日志路由前缀错误"
    print(f"  [OK] 日志管理路由: {logs_router.prefix}")

    print("API路由导入测试通过!\n")


def test_security():
    """测试安全策略"""
    print("=" * 50)
    print("测试安全策略...")

    from ops_platform.api.v1.routes.template import sanitize_filename

    # 测试路径遍历防护
    assert ".." not in sanitize_filename("../../etc/passwd"), "路径遍历防护失败"
    print("  [OK] 路径遍历防护正常")

    assert sanitize_filename("test.xlsx") == "test.xlsx", "正常文件名处理失败"
    print("  [OK] 正常文件名处理正确")

    assert sanitize_filename("test file (1).xlsx") == "test_file__1_.xlsx", "特殊字符处理失败"
    print("  [OK] 特殊字符处理正确")

    from ops_platform.core.config import settings
    print(f"  [OK] JWT密钥已配置: {'是' if settings.jwt_secret_key != 'change-me-before-production' else '否(开发模式)'}")
    print(f"  [OK] CORS白名单: {settings.cors_origins}")

    print("安全策略测试通过!\n")


def run_all_tests():
    """运行所有测试"""
    print("\n" + "=" * 60)
    print("  OPS-PLATFORM 功能测试")
    print("=" * 60 + "\n")

    tests = [
        test_models,
        test_notifier,
        test_utils,
        test_config_validation,
        test_api_imports,
        test_security,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"  [FAIL] 测试失败: {e}\n")
            failed += 1

    print("=" * 60)
    print(f"  测试结果: {passed} 通过, {failed} 失败")
    print("=" * 60)

    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
