"""所有和 Gemini 的通信都集中在这个文件。

好处：换 AI 供应商或换模型，只需要改这一个文件；
错误也在这里统一翻译成"给用户看的友好提示"，页面不会因为 AI 出问题而崩溃。

可靠性策略：
  1. 每次请求都有超时，对方迟迟不回应时不会让页面一直转圈；
  2. 主模型临时故障（5xx）时重试；
  3. 主模型不可用、超时、额度用完或模型名不存在时，自动改用备用模型；
  4. key 无效、请求本身有问题时不换模型（换了结果也一样）。
"""
import json
import logging
import os
import time

import httpx
from dotenv import load_dotenv
from google import genai
from google.genai import errors, types

load_dotenv()

logger = logging.getLogger(__name__)

# 模型名放在 .env 里，没设置时用默认值
MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
# 备用模型：主模型挂了就换它。设为空字符串表示不使用备用模型
FALLBACK_MODEL = os.getenv("GEMINI_FALLBACK_MODEL", "gemini-3.5-flash-lite")
# 单次请求最长等待几秒，超过就放弃（并尝试备用模型）
TIMEOUT_SECONDS = float(os.getenv("GEMINI_TIMEOUT_SECONDS", "45"))

RETRYABLE_CODES = (500, 502, 503, 504)       # 服务器端临时故障，值得原地重试
FALLBACK_CODES = (404, 408, 429) + RETRYABLE_CODES  # 换一个模型有可能成功（429 的额度是按模型计算的）

# 只有一个模型可用时，最多试几次、每次等几秒
MAX_ATTEMPTS = 2
RETRY_WAIT_SECONDS = 2

_client = None


class RequestTimeout(Exception):
    """请求超时。带有 code 属性，这样可以和 APIError 用同一套逻辑处理（408 = 请求超时）。"""

    code = 408


class AIServiceError(Exception):
    """AI 调用失败。user_message 是可以直接显示给用户的英文提示。"""

    def __init__(self, user_message):
        super().__init__(user_message)
        self.user_message = user_message


def _build_client(api_key, base_url=None):
    """创建客户端。SDK 的超时单位是毫秒；不设置超时的话，对方不回应时会一直等下去。"""
    http_options = types.HttpOptions(timeout=int(TIMEOUT_SECONDS * 1000), base_url=base_url)
    return genai.Client(api_key=api_key, http_options=http_options)


def _get_client():
    """第一次用到时才创建客户端：即使 .env 里没有 key，网站其他功能也能正常打开。"""
    global _client
    if _client is None:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise AIServiceError("AI features are not set up yet. Please contact the administrator.")
        _client = _build_client(api_key)
    return _client


def _friendly_message(error):
    """把各种技术错误翻译成用户看得懂的一句话。"""
    code = getattr(error, "code", None)
    if code == 429:
        return "Too many requests, or today's free quota is used up. Please try again later."
    if code == 408:
        return "The AI took too long to respond and the request timed out. Please try again later."
    if code in RETRYABLE_CODES:
        return "The AI service is busy right now. Please try again in a minute or two."
    if code in (401, 403):
        return "AI service authentication failed. Please ask the administrator to check the configuration."
    if code == 404:
        return "The configured AI model is unavailable. Please ask the administrator to change the model."
    return "The AI service is temporarily unavailable. Please try again later."


def _models_to_try():
    models = [MODEL_NAME]
    if FALLBACK_MODEL and FALLBACK_MODEL != MODEL_NAME:
        models.append(FALLBACK_MODEL)
    return models


def _call_model(client, model, prompt, config, attempts):
    """对同一个模型尝试若干次。成功返回文字；失败抛出最后一个 APIError。"""
    for attempt in range(1, attempts + 1):
        try:
            response = client.models.generate_content(model=model, contents=prompt, config=config)
        except httpx.TimeoutException as e:
            # 超时不在原地重试（再等一个完整的超时时间太久），交给上层换备用模型
            logger.warning("Gemini 请求超时（模型 %s，第 %s 次，超过 %s 秒）", model, attempt, TIMEOUT_SECONDS)
            raise RequestTimeout() from e
        except errors.APIError as e:
            # 真实错误写进终端日志方便调试；用户只会看到友好提示
            logger.warning("Gemini API 错误（模型 %s，第 %s 次）：%s", model, attempt, e)
            if getattr(e, "code", None) in RETRYABLE_CODES and attempt < attempts:
                time.sleep(RETRY_WAIT_SECONDS)
                continue
            raise
        if not response.text:
            raise AIServiceError("The AI returned nothing. Try rephrasing and try again.")
        return response.text


def _generate(prompt, json_mode=False):
    """真正发请求的函数（含重试和备用模型）。测试时可以替换掉它，不会消耗额度。"""
    client = _get_client()
    config = None
    if json_mode:
        # 要求模型直接返回 JSON，减少格式出错
        config = types.GenerateContentConfig(response_mime_type="application/json")

    models = _models_to_try()
    first_error = None  # 给用户看的提示以"主模型"的失败原因为准
    try:
        for index, model in enumerate(models):
            has_next = index < len(models) - 1
            # 后面还有备用模型时，不在已经很忙的模型上反复等待
            attempts = 1 if has_next else MAX_ATTEMPTS
            try:
                text = _call_model(client, model, prompt, config, attempts)
            except (errors.APIError, RequestTimeout) as e:
                first_error = first_error or e
                if getattr(e, "code", None) not in FALLBACK_CODES:
                    break  # key 无效、请求本身有问题：换模型也一样
                continue
            if index > 0:
                logger.warning("主模型 %s 不可用，本次改用备用模型 %s", MODEL_NAME, model)
            return text
    except AIServiceError:
        raise
    except Exception as e:  # 网络断开等其他问题
        logger.exception("调用 Gemini 时出现未知错误")
        raise AIServiceError("Could not reach the AI service. Check your network connection and try again.") from e

    raise AIServiceError(_friendly_message(first_error)) from first_error


def ask_gemini(prompt):
    """发送 prompt，返回回复文字。"""
    return _generate(prompt, json_mode=False)


def ask_gemini_json(prompt):
    """发送 prompt，要求 JSON 回复，返回解析后的 Python 对象。"""
    text = _generate(prompt, json_mode=True).strip()
    # 有时模型会把 JSON 包在 ```json ... ``` 里，先去掉
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        logger.warning("AI 返回的不是合法 JSON：%s", text[:200])
        raise AIServiceError("The AI response was in the wrong format. Please try again.") from e
