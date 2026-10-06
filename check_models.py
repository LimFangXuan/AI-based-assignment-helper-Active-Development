"""检查哪些模型现在能用：python check_models.py

会真的调用 AI（每个模型一次很短的请求）。可以在命令后面加模型名来检查指定的模型，
例如：python check_models.py gemini-3.8-flash gemini-3.5-flash-lite
"""
import logging
import sys

import ai_client

logging.disable(logging.CRITICAL)  # 只看结果，不刷屏

candidates = sys.argv[1:] or [ai_client.MODEL_NAME, ai_client.FALLBACK_MODEL]
print(f"每个模型最多等待 {ai_client.TIMEOUT_SECONDS:g} 秒\n")

for model in dict.fromkeys(candidates):  # 去重并保持顺序
    ai_client.MODEL_NAME, ai_client.FALLBACK_MODEL = model, ""  # 只测这个模型，不触发备用
    try:
        reply = ai_client.ask_gemini("用一个词回答：你好吗")
        print(f"{model}: 可用 -> {reply.strip()[:30]}", flush=True)
    except ai_client.AIServiceError as e:
        code = getattr(e.__cause__, "code", "?")
        print(f"{model}: 失败（错误码 {code}）-> {e.user_message}", flush=True)
