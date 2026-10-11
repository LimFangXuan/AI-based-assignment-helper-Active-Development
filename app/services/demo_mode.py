"""作品集演示模式（环境变量 DEMO_MODE=1）。

打开后：不能注册、没有 Google 登入、不发邮件、不推送；AI 和论文检索都用内置的样本回答，
任何人在页面上输入的内容都不会发到外部服务。数据是示例数据，启动时和点“Reset demo data”时恢复。
"""
import os


def enabled():
    return os.getenv("DEMO_MODE", "").strip() == "1"
