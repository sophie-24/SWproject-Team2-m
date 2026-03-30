import sys
print("현재 파이썬 경로:", sys.executable)
print("라이브러리 검색 경로:", sys.path)

import os
import yt_dlp
import whisper
from dotenv import load_dotenv
from googleapiclient.discovery import build
from fastapi import FastAPI
from datetime import datetime
from fastapi.middleware.cors import CORSMiddleware
from googleapiclient.discovery import build

load_dotenv()
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")

app = FastAPI(title="YouTube Cross Summary API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 모든 곳에서 오는 요청을 허용 (테스트용)
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_youtube_client():
    return build("youtube", "v3", developerKey=YOUTUBE_API_KEY)

#w자막 추출
import youtube_transcript_api
from youtube_transcript_api import YouTubeTranscriptApi
print("라이브러리 위치:", youtube_transcript_api.__file__)
def get_video_transcript(video_id: str):
    try:
        # 
        # 1. 클래스에서 직접 list_transcripts 메서드를 호출합니다.
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
        
        try:
            # 2. 한국어 자막(ko)을 먼저 찾습니다.
            transcript = transcript_list.find_transcript(['ko'])
        except:
            # 3. 한국어 자막이 없으면 영어(en)를 가져와서 한국어로 '자동 번역'합니다.
            # 이 기능 덕분에 대부분의 영상에서 자막을 가져올 수 있습니다.
            transcript = transcript_list.find_transcript(['en']).translate('ko')
            
        data = transcript.fetch()
        # 모든 자막 텍스트 조각을 하나의 문자열로 합칩니다.
        full_text = " ".join([item['text'] for item in data])
        return full_text
        
    except Exception as e:
        print(f"[자막 실패 → Whisper 시도] {video_id}")
        
        # 🔥 여기 핵심
        whisper_text = get_transcript_with_whisper(video_id)
        return whisper_text

whisper_model = whisper.load_model("base")  
# tiny (빠름) / base (적당) / small (정확) -> 속도 따라서 조정하기

def get_transcript_with_whisper(video_id: str):
    try:
        url = f"https://www.youtube.com/watch?v={video_id}"
        
        # 1. 오디오 다운로드
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': f'temp/{video_id}.%(ext)s',
            'quiet': True,
        }
        
        os.makedirs("temp", exist_ok=True)
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)

        # 2. Whisper로 변환
        result = whisper_model.transcribe(filename)
        
        # 3. 파일 삭제 (중요)
        os.remove(filename)
        
        return result["text"]

    except Exception as e:
        return f"Whisper 실패: {str(e)}"
                
#서버 확인용
@app.get("/")
def read_root():
    return {"message": "YouTube Cross Summary Dashboard Backend is Running!"}

@app.get("/health")
def health_check():
    "서버 상태 확인용 엔드포인트"
    return {"status": "ok"}

#유튜브에서 영상 찾아오기
@app.get("/search")
def search_videos(keyword: str):
    youtube = get_youtube_client()
    
    request = youtube.search().list(
        q=keyword,
        part="snippet",
        type="video",
        maxResults=10  #추후 조정 -> 현재는 10개임.
    )
    response = request.execute()
    
    return response

#view rate 계산 로직 추가
@app.get("/analyze")
def analyze_videos(keyword: str):
    youtube = get_youtube_client()
    
    # 1. 키워드로 영상 ID들 검색 (최근 영상 위주로 10개)
    search_response = youtube.search().list(
        q=keyword,
        part="snippet",
        type="video",
        maxResults=10,
        order="relevance" # 또는 "date"
    ).execute()
    
    video_ids = [item["id"]["videoId"] for item in search_response["items"]]
    
    if not video_ids:
        return {"top_videos": [], "message" : "검색 결과가 없습니다"}  
    
    # 2. 검색된 영상들의 상세 정보(조회수, 날짜) 가져오기
    video_response = youtube.videos().list(
        id=",".join(video_ids),
        part="statistics,snippet"
    ).execute()
    
    results = []
    now = datetime.now()
    
    for video in video_response["items"]:
        v_id = video["id"]
        print(f"--- 분석 중인 영상 ID: {v_id} ---")
        transcript = get_video_transcript(v_id)
    
    # 만약 실패했다면 터미널에 에러 이유를 출력하게 함
        if "자막 없음" in transcript:
            print(f"실패 원인: {transcript}")
        title = video["snippet"]["title"]
        pub_date_str = video["snippet"]["publishedAt"].replace("Z", "+00:00")
        published_at = datetime.fromisoformat(pub_date_str).replace(tzinfo=None)
        
        view_count = int(video["statistics"].get("viewCount", 0))
        # 3. View Rate 계산 (조회수 / 경과일수)
        days_diff = (now - published_at).days
        if days_diff < 1: days_diff = 1 # 오늘 올린 건 1일로 계산하기로..
        
        view_rate = view_count / days_diff

        results.append({
            "title": title,
            "view_count": view_count,
            "days_old": days_diff,
            "view_rate": round(view_rate, 2),
            "video_id": video["id"],
            "transcript_preview": transcript[:200] + "..." #자막 길이 조정
        })
    
    # 4. View Rate 기준으로 내림차순 정렬하여 상위 5개 선정
    top_5 = sorted(results, key=lambda x: x["view_rate"], reverse=True)[:5]
    
    return {"top_videos": top_5}