from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials


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
