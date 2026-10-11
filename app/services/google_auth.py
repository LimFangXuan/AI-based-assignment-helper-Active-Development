"""只负责和 Google 的 OAuth 通信（用 Google 账号登录 / 注册）。不碰数据库，也不碰 Flask 的 session。

流程（OAuth 2.0 授权码 + PKCE，OpenID Connect）：
  1. authorization_url：把用户送到 Google 的登录页，带上随机的 state（防 CSRF）和 PKCE 的 code_challenge
  2. 用户在 Google 同意后，Google 带着 code 和 state 回到我们的 /auth/google/callback
  3. fetch_profile：用 code + code_verifier 向 Google 换 access_token，再读取用户资料
     access_token 是服务器直接从 Google 的 HTTPS 接口拿到的，所以资料可信；浏览器从头到尾看不到 client secret。
只接受 Google 已验证过的邮箱（email_verified），并以 Google 账号的固定 ID（sub）识别用户，不依赖邮箱。
"""
import base64
import hashlib
import logging
import os
import secrets
from urllib.parse import urlencode

import httpx

logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)  # 请求日志会带上完整网址

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
TIMEOUT_SECONDS = 15


class GoogleAuthError(Exception):
    """Google 登录失败。user_message 可以直接显示给用户。"""

    def __init__(self, user_message):
        super().__init__(user_message)
        self.user_message = user_message


def client_id():
    return os.getenv("GOOGLE_CLIENT_ID", "").strip()


def client_secret():
    return os.getenv("GOOGLE_CLIENT_SECRET", "").strip()


def configured():
    return bool(client_id() and client_secret())


def new_state_and_verifier():
    """state：回调时核对，防止别人把他自己的登录结果塞给你。verifier：PKCE 的一次性秘密，只存在服务器的 session 里。"""
    return secrets.token_urlsafe(32), secrets.token_urlsafe(64)


def code_challenge(verifier):
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def authorization_url(redirect_uri, state, verifier):
    params = {
        "client_id": client_id(), "redirect_uri": redirect_uri, "response_type": "code",
        "scope": "openid email profile", "state": state,
        "code_challenge": code_challenge(verifier), "code_challenge_method": "S256",
        "prompt": "select_account",  # 每次都让用户选账号，避免在共用电脑上悄悄登入上一个人
    }
    return f"{AUTH_URL}?{urlencode(params)}"


def _http_client():
    """单独成函数：测试时替换成 httpx.MockTransport，就不会发出真实请求。"""
    return httpx.Client(timeout=TIMEOUT_SECONDS)


def fetch_profile(code, verifier, redirect_uri):
    """用授权码换用户资料。返回 {"sub", "email", "name"}；任何问题都抛出 GoogleAuthError。"""
    if not configured():
        raise GoogleAuthError("Google sign-in is not set up yet.")
    try:
        with _http_client() as http:
            token = http.post(TOKEN_URL, data={
                "code": code, "client_id": client_id(), "client_secret": client_secret(),
                "redirect_uri": redirect_uri, "grant_type": "authorization_code", "code_verifier": verifier})
            if token.status_code != 200:
                logger.warning("Google 换取 token 失败：%s %s", token.status_code, token.text[:200])
                raise GoogleAuthError("Google did not accept the sign-in. Please try again.")
            access_token = token.json().get("access_token")
            if not access_token:
                raise GoogleAuthError("Google did not accept the sign-in. Please try again.")
            info = http.get(USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"})
            if info.status_code != 200:
                logger.warning("Google 读取用户资料失败：%s", info.status_code)
                raise GoogleAuthError("Could not read your Google profile. Please try again.")
            data = info.json()
    except httpx.TimeoutException as e:
        raise GoogleAuthError("Google took too long to respond. Please try again.") from e
    except httpx.HTTPError as e:
        raise GoogleAuthError("Could not reach Google. Check your network connection and try again.") from e
    except ValueError as e:  # 返回的不是 JSON
        raise GoogleAuthError("Google returned something unexpected. Please try again.") from e

    sub, email = str(data.get("sub") or ""), str(data.get("email") or "").strip().lower()
    if not sub or not email:
        raise GoogleAuthError("Your Google account did not share an email address.")
    if data.get("email_verified") is not True:
        raise GoogleAuthError("Your Google email address is not verified, so it can't be used to sign in.")
    return {"sub": sub, "email": email, "name": str(data.get("name") or "").strip()}
