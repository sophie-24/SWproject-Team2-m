// content.js — Tubify 크롬 익스텐션
// 유튜브 우측에 플로팅 버튼을 표시. 클릭 시 사이드 패널(side_panel.html)을 오픈.
// 유튜브 검색/시청 이벤트를 /collect 엔드포인트로 백엔드에 전송 (Pipeline B 행동 수집).

// API 주소는 config.js의 API_BASE를 사용합니다 (manifest.json content_scripts에 선행 로드됨)
const BTN_ID = "tv-float-btn";
const DEBOUNCE_MS = 500;  // YouTube SPA 연속 이벤트 디바운스 간격

// ── 행동 로그 수집 ────────────────────────────────────────────────────────────

let _lastCollectedSearch  = "";
let _lastCollectedVideoId = "";
let _searchDebounceTimer  = null;  // 디바운스 타이머 — search
let _watchDebounceTimer   = null;  // 디바운스 타이머 — watch

async function collectEvent(event_type, keyword, video_id = null) {
  if (!isContextValid()) return;
  const jwt = await getJwt();
  if (!jwt) return;

  try {
    await fetch(`${API_BASE}/collect`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${jwt}`,
      },
      body: JSON.stringify({ event_type, keyword, video_id }),
    });
    console.log(`[Tubify] collect → ${event_type}: ${keyword}`);
  } catch (e) {
    // 백엔드 미실행 시 조용히 무시
  }
}

function maybeCollectSearch() {
  const keyword = getKeyword();
  if (!keyword || keyword === _lastCollectedSearch) return;
  _lastCollectedSearch = keyword;
  collectEvent("search", keyword, null);
}

function maybeCollectWatch() {
  const p = new URLSearchParams(window.location.search);
  const videoId = p.get("v") || "";
  if (!videoId || videoId === _lastCollectedVideoId) return;

  // 영상 제목 추출 (YouTube DOM)
  const titleEl = document.querySelector("h1.ytd-video-primary-info-renderer, h1.style-scope.ytd-video-primary-info-renderer");
  const title = titleEl ? titleEl.textContent.trim() : videoId;

  _lastCollectedVideoId = videoId;
  collectEvent("watch", title, videoId);
}

// ── 디바운스 래퍼 (500ms) ─────────────────────────────────────────────────────
// YouTube SPA는 yt-navigate-finish를 짧은 간격으로 연속 발화할 수 있다.
// 타이머를 매번 리셋해 마지막 이벤트 기준 500ms 후 한 번만 /collect를 전송한다.
// ※ init() 최초 호출은 디바운스 없이 즉시 실행 (초기 페이지 로드는 연속 이벤트 없음).

function debouncedCollectSearch() {
  clearTimeout(_searchDebounceTimer);
  _searchDebounceTimer = setTimeout(maybeCollectSearch, DEBOUNCE_MS);
}

function debouncedCollectWatch() {
  clearTimeout(_watchDebounceTimer);
  _watchDebounceTimer = setTimeout(maybeCollectWatch, DEBOUNCE_MS);
}

// ── 유틸 ─────────────────────────────────────────────────────────────────────

function getKeyword() {
  const p = new URLSearchParams(window.location.search);
  return (p.get("search_query") || "").trim();
}

function getJwt() {
  return new Promise(resolve => {
    try {
      chrome.storage.local.get(["jwt"], r => {
        if (chrome.runtime.lastError) { resolve(""); return; }
        resolve(r.jwt || "");
      });
    } catch (e) {
      resolve("");
    }
  });
}

function isContextValid() {
  try { return !!chrome.runtime.id; } catch (e) { return false; }
}

// ── 플로팅 버튼 생성 ──────────────────────────────────────────────────────────

function createFloatBtn() {
  if (document.getElementById(BTN_ID)) return;

  const btn = document.createElement("div");
  btn.id = BTN_ID;

  Object.assign(btn.style, {
    position:        "fixed",
    bottom:          "24px",
    right:           "24px",
    zIndex:          "99999",
    width:           "56px",
    height:          "56px",
    background:      "#ff0000",
    borderRadius:    "50%",
    display:         "flex",
    alignItems:      "center",
    justifyContent:  "center",
    cursor:          "pointer",
    boxShadow:       "0 4px 16px rgba(0,0,0,0.35)",
    transition:      "transform 0.2s ease, box-shadow 0.2s ease",
    userSelect:      "none",
    flexShrink:      "0",
  });

  btn.innerHTML = `
    <svg width="21" height="21" viewBox="0 0 24 24" fill="white" xmlns="http://www.w3.org/2000/svg">
      <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
    </svg>
  `;

  btn.addEventListener("mouseenter", () => {
    btn.style.transform = "scale(1.1)";
    btn.style.boxShadow = "0 6px 24px rgba(0,0,0,0.45)";
  });

  btn.addEventListener("mouseleave", () => {
    btn.style.transform = "scale(1)";
    btn.style.boxShadow = "0 4px 16px rgba(0,0,0,0.35)";
  });

  btn.addEventListener("click", async () => {
    const keyword = getKeyword();

    if (!keyword) {
      btn.style.background = "#cc0000";
      setTimeout(() => { btn.style.background = "#ff0000"; }, 300);
      return;
    }

    try {
      chrome.runtime.sendMessage({
        type:    "OPEN_SIDE_PANEL",
        tabId:   null,
        keyword: keyword,
      });
    } catch (e) {
      console.warn("[Tubify] 익스텐션이 재로드됐습니다. 페이지를 새로고침(F5)해주세요.");
    }
  });

  document.body.appendChild(btn);
}

// ── 페이지 타입 판별 ──────────────────────────────────────────────────────────

function isSearchPage() {
  return window.location.pathname === "/results";
}

function isWatchPage() {
  return window.location.pathname === "/watch";
}

// ── 초기화 ────────────────────────────────────────────────────────────────────

function init() {
  if (isSearchPage()) {
    createFloatBtn();
    maybeCollectSearch();
  } else if (isWatchPage()) {
    createFloatBtn();
    maybeCollectWatch();
  } else {
    /* 검색/시청 페이지 아니면 버튼 제거 */
    const existing = document.getElementById(BTN_ID);
    if (existing) existing.remove();
  }
}

// ── YouTube SPA 네비게이션 감지 ───────────────────────────────────────────────

window.addEventListener("yt-navigate-finish", () => {
  if (!isContextValid()) return;
  init();
  if (isSearchPage())  debouncedCollectSearch();
  if (isWatchPage())   debouncedCollectWatch();
});

/* 최초 페이지 로드 */
init();