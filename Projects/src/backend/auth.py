# 추가한 내용
# 1. OAuth 콜백 처리 → access_token 교환
# 2. JWT 발급 (우리 서버용 세션 토큰)
# 3. JWT 검증 함수

import os
import jwt
import datetime
from dotenv import load_dotenv
from google_auth_oauthlib.flow import Flow
from google.oauth2 import id_token
from google.auth.transport import requests as grequests

load_dotenv()

CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
REDIRECT_URI = os.getenv("REDIRECT_URI", "http://localhost:8000/auth/callback")

# YouTube 구독 목록 읽기 + 기본 프로필 정보
SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/youtube.readonly",
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


def create_flow() -> Flow:
    flow = Flow.from_client_config(
        CLIENT_CONFIG,
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI,
    )
    return flow

#수정필요
JWT_SECRET = os.getenv("JWT_SECRET", "your-secret-key-change-this")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = 24 * 7 

def exchange_code_for_tokens(code: str):
    """
    구글이 준 code → access_token + id_token 교환
    main.py의 /auth/callback 에서 호출
    """
    flow = create_flow()
    flow.fetch_token(code=code)
    credentials = flow.credentials

    # 구글 id_token에서 사용자 정보 추출
    id_info = id_token.verify_oauth2_token(
        credentials.id_token,
        grequests.Request(),
        CLIENT_ID,
    )

    return {
        "google_id": id_info["sub"],
        "email":     id_info["email"],
        "name":      id_info.get("name", ""),
        "credentials": {
            "token":         credentials.token,
            "refresh_token": credentials.refresh_token,
            "token_uri":     credentials.token_uri,
            "client_id":     credentials.client_id,
            "client_secret": credentials.client_secret,
            "scopes":        list(credentials.scopes or []),
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
