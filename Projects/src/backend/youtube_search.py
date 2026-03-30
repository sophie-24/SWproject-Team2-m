import os
from typing import List
from googleapiclient.discovery import build
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
            part="statistics,contentDetails",
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
            }
        )

    return results
