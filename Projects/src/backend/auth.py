# Google OAuth2 PKCE 인증 흐름 + JWT 발급/검증
from __future__ import annotations
import os
import jwt
import datetime
import hashlib
import base64
import secrets
from dotenv import load_dotenv
from google_auth_oauthlib.flow import Flow
from google.oauth2 import id_token
from google.auth.transport import requests as grequests

load_dotenv()

CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
REDIRECT_URI = os.getenv("REDIRECT_URI", "http://localhost:8000/auth/callback")

# 기본 프로필 정보만 요청 (youtube.readonly 제거 — Google 심사 불필요)
SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
]

CLIENT_CONFIG = {
    "web": {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "redirect_uris": [REDIRECT_URI],
    }
}

JWT_SECRET    = os.getenv("JWT_SECRET")
if not JWT_SECRET:
    raise ValueError("JWT_SECRET이 .env에 없습니다")
JWT_ALGORITHM    = "HS256"
JWT_EXPIRE_HOURS = 24 * 7

def _generate_pkce() -> tuple[str, str]:
    """
    PKCE code_verifier + code_challenge 생성
    code_verifier: 랜덤 문자열
    code_challenge: SHA256(code_verifier) → base64url 인코딩
    """
    code_verifier = base64.urlsafe_b64encode(
        secrets.token_bytes(32)
    ).rstrip(b"=").decode("utf-8")

    code_challenge = base64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode("utf-8")).digest()
    ).rstrip(b"=").decode("utf-8")

    return code_verifier, code_challenge

def create_flow() -> Flow:
    flow = Flow.from_client_config(
        CLIENT_CONFIG,
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI,
    )
    return flow

def create_auth_url() -> tuple[str, str, str]:
    """
    구글 OAuth 로그인 URL 생성
    Returns: (auth_url, state, code_verifier)
    """
    code_verifier, code_challenge = _generate_pkce()

    flow = create_flow()
    auth_url, state = flow.authorization_url(
        access_type="offline",
        prompt="consent",
        code_challenge=code_challenge,
        code_challenge_method="S256",
    )
    return auth_url, state, code_verifier

def exchange_code_for_tokens(code: str, code_verifier: str) -> dict:
    """
    구글이 준 code → access_token + id_token 교환
    PKCE code_verifier 포함
    """
    import requests
    token_response = requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "code":          code,
            "client_id":     CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "redirect_uri":  REDIRECT_URI,
            "grant_type":    "authorization_code",
            "code_verifier": code_verifier,
        }
    )
    token_data = token_response.json()

    if "error" in token_data:
        raise ValueError(f"토큰 교환 실패: {token_data}")

    # id_token에서 사용자 정보 추출
    id_info = id_token.verify_oauth2_token(
        token_data["id_token"],
        grequests.Request(),
        CLIENT_ID,
    )
    return {
        "google_id": id_info["sub"],
        "email":     id_info["email"],
        "name":      id_info.get("name", ""),
        "credentials": {
            "token":         token_data.get("access_token"),
            "refresh_token": token_data.get("refresh_token"),
            "token_uri":     "https://oauth2.googleapis.com/token",
            "client_id":     CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "scopes":        SCOPES,
        }
    }


def create_jwt(user_id: str, email: str) -> str:
    """
    우리 서버용 JWT 발급
    이 토큰을 익스텐션이 /collect 호출 시 사용
    """
    payload = {
        "user_id": user_id,
        "email":   email,
        "exp":     datetime.datetime.utcnow() + datetime.timedelta(hours=JWT_EXPIRE_HOURS),
        "iat":     datetime.datetime.utcnow(),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def verify_jwt(token: str) -> dict | None:
    """
    JWT 검증 → user_id 반환
    main.py의 Depends(get_current_user) 에서 호출
    """
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return {"user_id": payload["user_id"], "email": payload["email"]}
    except jwt.ExpiredSignatureError:
        return None  # 만료
    except jwt.InvalidTokenError:
        return None  # 위조
