# YouTube Data API — 영상 검색·메타데이터 조회, 단일 영상 fetch, OAuth 구독 채널 목록
import os
from typing import List
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from dotenv import load_dotenv

load_dotenv()

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")


def search_videos(keyword: str, max_results: int = 10) -> List[dict]:
    """
    키워드로 YouTube 영상 검색 후 메타데이터 반환.
    반환 필드: video_id, title, channel_id, channel_title, published_at, description, thumbnail
    """
    youtube = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)

    search_response = (
        youtube.search()
        .list(
            q=keyword,
            part="snippet",
            type="video",
            maxResults=max_results,
            order="relevance",
        )
        .execute()
    )

    video_ids = [item["id"]["videoId"] for item in search_response.get("items", [])]

    if not video_ids:
        return []

    # 조회수, 좋아요수 등 상세 통계 추가 조회
    stats_response = (
        youtube.videos()
        .list(
            part="statistics,contentDetails,status",
            id=",".join(video_ids),
        )
        .execute()
    )

    stats_map = {
        item["id"]: item for item in stats_response.get("items", [])
    }

    results = []
    for item in search_response.get("items", []):
        video_id = item["id"]["videoId"]
        snippet = item["snippet"]
        stats = stats_map.get(video_id, {})
        statistics = stats.get("statistics", {})
        content_details = stats.get("contentDetails", {})

        results.append(
            {
                "video_id": video_id,
                "title": snippet["title"],
                "channel_id": snippet["channelId"],
                "channel_title": snippet["channelTitle"],
                "published_at": snippet["publishedAt"],
                "description": snippet.get("description", ""),
                "thumbnail": snippet["thumbnails"].get("medium", {}).get("url", ""),
                "view_count": int(statistics.get("viewCount", 0)),
                "like_count": int(statistics.get("likeCount", 0)),
                "duration": content_details.get("duration", ""),
                # YouTube Studio "유료 프로모션 포함" 체크박스 여부
                # 크리에이터 본인 OAuth 없이는 대부분 null 반환
                "has_paid_placement": stats.get("status", {}).get(
                    "hasPaidProductPlacement", None
                ),
            }
        )

    return results


def fetch_video_by_id(video_id: str) -> dict:
    """
    단일 video_id로 YouTube Data API를 호출해 전체 메타데이터 반환.
    /ai_analyze 엔드포인트처럼 video_id만 아는 경우에 사용.

    반환 필드: search_videos()와 동일 (video_id, title, channel_id,
               channel_title, published_at, description, thumbnail,
               view_count, like_count, duration, has_paid_placement)
    API 오류 또는 영상 없음 시 video_id만 포함한 최소 dict 반환.
    """
    if not YOUTUBE_API_KEY:
        return {"video_id": video_id, "title": "", "channel_id": "",
                "channel_title": "", "published_at": "", "description": "",
                "thumbnail": "", "view_count": 0, "like_count": 0,
                "duration": "", "has_paid_placement": None}

    try:
        youtube = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)
        resp = (
            youtube.videos()
            .list(
                part="snippet,statistics,contentDetails,status",
                id=video_id,
            )
            .execute()
        )
        items = resp.get("items", [])
        if not items:
            return {"video_id": video_id, "title": "", "channel_id": "",
                    "channel_title": "", "published_at": "", "description": "",
                    "thumbnail": "", "view_count": 0, "like_count": 0,
                    "duration": "", "has_paid_placement": None}

        item = items[0]
        snippet    = item.get("snippet", {})
        statistics = item.get("statistics", {})
        details    = item.get("contentDetails", {})
        status     = item.get("status", {})

        return {
            "video_id":          video_id,
            "title":             snippet.get("title", ""),
            "channel_id":        snippet.get("channelId", ""),
            "channel_title":     snippet.get("channelTitle", ""),
            "published_at":      snippet.get("publishedAt", ""),
            "description":       snippet.get("description", ""),
            "thumbnail":         snippet.get("thumbnails", {}).get("medium", {}).get("url", ""),
            "view_count":        int(statistics.get("viewCount", 0)),
            "like_count":        int(statistics.get("likeCount", 0)),
            "duration":          details.get("duration", ""),
            "has_paid_placement": status.get("hasPaidProductPlacement", None),
        }
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"[youtube] fetch_video_by_id 실패 {video_id}: {e}")
        return {"video_id": video_id, "title": "", "channel_id": "",
                "channel_title": "", "published_at": "", "description": "",
                "thumbnail": "", "view_count": 0, "like_count": 0,
                "duration": "", "has_paid_placement": None}


def get_subscriptions(credentials: Credentials) -> list[dict]:
    """
    인증된 사용자의 YouTube 구독 채널 목록을 반환.
    - channel_id, channel_title, thumbnail, subscriber_count 포함
    """
    youtube = build("youtube", "v3", credentials=credentials)

    subscriptions = []
    next_page_token = None

    while True:
        response = (
            youtube.subscriptions()
            .list(
                part="snippet,contentDetails",
                mine=True,
                maxResults=50,
                pageToken=next_page_token,
            )
            .execute()
        )

        for item in response.get("items", []):
            snippet = item["snippet"]
            subscriptions.append(
                {
                    "channel_id": snippet["resourceId"]["channelId"],
                    "channel_title": snippet["title"],
                    "description": snippet.get("description", ""),
                    "thumbnail": snippet["thumbnails"].get("default", {}).get("url", ""),
                    "subscribed_at": snippet.get("publishedAt", ""),
                }
            )

        next_page_token = response.get("nextPageToken")
        if not next_page_token:
            break

    return subscriptions
