// content.js — TechVisibility 크롬 익스텐션
// 유튜브 우측에 플로팅 버튼을 표시. 클릭 시 사이드 패널(side_panel.html)을 오픈.
// 유튜브 검색/시청 이벤트를 /collect 엔드포인트로 백엔드에 전송 (Pipeline B 행동 수집).

const API = "http://localhost:8000";
const BTN_ID = "tv-float-btn";

// ── 행동 로그 수집 ────────────────────────────────────────────────────────────

let _lastCollectedSearch = "";
let _lastCollectedVideoId = "";

async function collectEvent(event_type, keyword, video_id = null) {
  const jwt = await getJwt();
  if (!jwt) return; // 로그인 안 된 경우 무시

  try {
    await fetch(`${API}/collect`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${jwt}`,
      },
      body: JSON.stringify({ event_type, keyword, video_id }),
    });
    console.log(`[TechVisibility] collect → ${event_type}: ${keyword}`);
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

// ── 유틸 ─────────────────────────────────────────────────────────────────────

function getKeyword() {
  const p = new URLSearchParams(window.location.search);
  return (p.get("search_query") || "").trim();
}

function getJwt() {
  return new Promise(resolve =>
    chrome.storage.local.get(["jwt"], r => resolve(r.jwt || ""))
  );
}

// ── 플로팅 버튼 생성 ──────────────────────────────────────────────────────────

function createFloatBtn() {
  if (document.getElementById(BTN_ID)) return;

  const btn = document.createElement("div");
  btn.id = BTN_ID;

  // 기본 스타일 (접힌 상태: 아이콘만 보임)
  Object.assign(btn.style, {
    position:     "fixed",
    top:          "50%",
    right:        "0",
    transform:    "translateY(-50%)",
    zIndex:       "99999",
    display:      "flex",
    alignItems:   "center",
    gap:          "0px",
    background:   "#ff4444",
    color:        "#fff",
    borderRadius: "8px 0 0 8px",
    padding:      "10px 8px",
    cursor:       "pointer",
    boxShadow:    "-2px 0 12px rgba(0,0,0,0.4)",
    transition:   "all 0.25s cubic-bezier(0.4, 0, 0.2, 1)",
    overflow:     "hidden",
    maxWidth:     "36px",  // 접힌 상태 너비
    userSelect:   "none",
  });

  btn.innerHTML = `
    <span id="tv-icon" style="font-size:1rem;flex-shrink:0;line-height:1;">✦</span>
    <span id="tv-label" style="
      font-family:'Segoe UI',sans-serif;
      font-size:0.8rem;
      font-weight:700;
      white-space:nowrap;
      overflow:hidden;
      max-width:0;
      opacity:0;
      transition:max-width 0.25s ease, opacity 0.2s ease, margin 0.25s ease;
      margin-left:0;
    ">유튜브 검색 요약보기</span>
  `;

  const label = btn.querySelector("#tv-label");

  // 호버: 펼쳐짐
  btn.addEventListener("mouseenter", () => {
    btn.style.maxWidth = "190px";
    btn.style.padding = "10px 14px 10px 10px";
    label.style.maxWidth = "160px";
    label.style.opacity = "1";
    label.style.marginLeft = "8px";
  });

  // 호버 아웃: 접힘
  btn.addEventListener("mouseleave", () => {
    btn.style.maxWidth = "36px";
    btn.style.padding = "10px 8px";
    label.style.maxWidth = "0";
    label.style.opacity = "0";
    label.style.marginLeft = "0";
  });

  // 클릭: 사이드 패널 오픈 (background.js를 통해 chrome.sidePanel.open 호출)
  btn.addEventListener("click", async () => {
    const keyword = getKeyword();

    if (!keyword) {
      label.textContent = "검색어가 없습니다";
      btn.style.maxWidth = "190px";
      btn.style.padding = "10px 14px 10px 10px";
      label.style.maxWidth = "160px";
      label.style.opacity = "1";
      label.style.marginLeft = "8px";
      setTimeout(() => {
        label.textContent = "유튜브 검색 요약보기";
        btn.style.maxWidth = "36px";
        btn.style.padding = "10px 8px";
        label.style.maxWidth = "0";
        label.style.opacity = "0";
        label.style.marginLeft = "0";
      }, 2000);
      return;
    }

    // background.js에 사이드 패널 오픈 요청
    chrome.runtime.sendMessage({ type: "OPEN_SIDE_PANEL" });
  });

  document.body.appendChild(btn);
  updateBtnState();
}

// ── 버튼 활성/비활성 상태 업데이트 ───────────────────────────────────────────

function updateBtnState() {
  const btn = document.getElementById(BTN_ID);
  if (!btn) return;

  const keyword = getKeyword();
  if (keyword) {
    btn.style.opacity = "1";
    btn.title = `"${keyword}" 검색 요약 보기`;
  } else {
    btn.style.opacity = "0.45";
    btn.title = "유튜브에서 검색하면 요약이 활성화됩니다";
  }
}

// ── 초기화 + YouTube SPA 네비게이션 감지 ──────────────────────────────────────

function init() {
  createFloatBtn();
  maybeCollectSearch();
  maybeCollectWatch();
}

// YouTube는 SPA — URL 변경마다 재처리
window.addEventListener("yt-navigate-finish", () => {
  updateBtnState();
  maybeCollectSearch();
  maybeCollectWatch();
});

init();
