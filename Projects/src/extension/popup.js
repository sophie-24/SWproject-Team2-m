const API = "http://localhost:8000";

// ── DOM ───────────────────────────────────────────────────────────────────────

const serverDot      = document.getElementById("server-dot");
const serverStatus   = document.getElementById("server-status");
const sectionSearch  = document.getElementById("section-search");
const sectionIdle    = document.getElementById("section-youtube-idle");
const sectionNotYT   = document.getElementById("section-not-youtube");
const sectionLogin   = document.getElementById("section-login");
const sectionLoggedIn= document.getElementById("section-loggedin");
const sectionLogout  = document.getElementById("section-logout");
const keywordText    = document.getElementById("keyword-text");
const videoPreview   = document.getElementById("video-preview");
const msgEl          = document.getElementById("msg");

// ── 헬퍼 ─────────────────────────────────────────────────────────────────────

function showMsg(text, isError = false) {
  msgEl.textContent = text;
  msgEl.className = isError ? "error" : "";
  if (text) setTimeout(() => { msgEl.textContent = ""; }, 3500);
}

function esc(str) {
  return String(str ?? "")
    .replace(/&/g, "&amp;").replace(/</g, "&lt;")
    .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

function get(keys) {
  return new Promise(resolve => chrome.storage.local.get(keys, resolve));
}

// ── 서버 상태 확인 ────────────────────────────────────────────────────────────

async function checkServer() {
  try {
    const res = await fetch(`${API}/health`, { signal: AbortSignal.timeout(2000) });
    const ok = res.ok;
    serverDot.className = `dot ${ok ? "on" : "off"}`;
    serverStatus.textContent = ok
      ? "서버 연결됨 (localhost:8000)"
      : "서버 오프라인 — 백엔드를 먼저 실행하세요";
    return ok;
  } catch {
    serverDot.className = "dot off";
    serverStatus.textContent = "서버 오프라인 — 백엔드를 먼저 실행하세요";
    return false;
  }
}

// ── 현재 탭 정보 ───────────────────────────────────────────────────────────────

function getCurrentTab() {
  return new Promise(resolve =>
    chrome.tabs.query({ active: true, currentWindow: true }, tabs => resolve(tabs[0]))
  );
}

function extractKeyword(url) {
  try {
    const u = new URL(url);
    if (!u.hostname.includes("youtube.com")) return null;
    if (u.pathname !== "/results") return null;
    return u.searchParams.get("search_query") || null;
  } catch {
    return null;
  }
}

function isYouTube(url) {
  try { return new URL(url).hostname.includes("youtube.com"); }
  catch { return false; }
}

// ── 검색 요약 섹션 ────────────────────────────────────────────────────────────

async function loadVideoPreview(keyword) {
  videoPreview.innerHTML = `<div style="font-size:0.78rem;color:#444;padding:4px 0;"><span class="spinner"></span>영상 목록 로딩 중...</div>`;
  try {
    const res = await fetch(`${API}/search?keyword=${encodeURIComponent(keyword)}&max_results=5`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    const videos = data.videos || [];

    if (!videos.length) {
      videoPreview.innerHTML = `<div style="font-size:0.78rem;color:#555;padding:4px 0;">영상을 찾을 수 없습니다.</div>`;
      return;
    }

    videoPreview.innerHTML = videos.slice(0, 5).map((v, i) => `
      <div class="video-row">
        <span class="video-num">${i + 1}</span>
        <span class="video-name" title="${esc(v.title)}">${esc(v.title)}</span>
      </div>
    `).join("");
  } catch (e) {
    videoPreview.innerHTML = `<div style="font-size:0.78rem;color:#555;padding:4px 0;">목록 로드 실패</div>`;
  }
}

function showSearchSection(keyword, jwt) {
  sectionSearch.classList.remove("hidden");
  keywordText.textContent = keyword;
  loadVideoPreview(keyword);

  document.getElementById("btn-dashboard").onclick = async () => {
    // 사이드 패널로 열기 (background.js가 chrome.sidePanel.open 호출)
    const tab = await getCurrentTab();
    chrome.runtime.sendMessage({ type: "OPEN_SIDE_PANEL", tabId: tab?.id });
    window.close();
  };
}

// ── 로그인 상태 ───────────────────────────────────────────────────────────────

async function loadSubscriptions(jwt) {
  const channelList  = document.getElementById("channel-list");
  const channelCount = document.getElementById("channel-count");
  channelList.innerHTML = `<span style="color:#555;font-size:0.78rem;"><span class="spinner"></span>불러오는 중...</span>`;
  try {
    const res = await fetch(`${API}/subscriptions`, {
      headers: { "Authorization": `Bearer ${jwt}` },
    });
    if (res.status === 401) {
      await chrome.storage.local.remove(["jwt", "loggedIn"]);
      renderLoggedOut();
      showMsg("세션 만료 — 다시 로그인해주세요.", true);
      return;
    }
    const data = await res.json();
    const channels = data.subscriptions || [];
    const ids = channels.map(c => c.channel_id);
    chrome.storage.local.set({ subscribedChannelIds: ids, subscribedChannels: channels });

    channelList.innerHTML = channels.length
      ? channels.slice(0, 50).map(c => `<div class="channel-item">${esc(c.channel_title)}</div>`).join("")
      : `<span style="color:#555;font-size:0.78rem;">구독 채널 없음</span>`;
    channelCount.textContent = channels.length ? `총 ${channels.length}개 채널` : "";
  } catch {
    channelList.innerHTML = `<span style="color:#cc4444;font-size:0.78rem;">채널 목록 로드 실패</span>`;
  }
}

function renderLoggedIn(jwt) {
  sectionLogin.classList.add("hidden");
  sectionLoggedIn.classList.remove("hidden");
  sectionLogout.classList.remove("hidden");
  loadSubscriptions(jwt);
}

function renderLoggedOut() {
  sectionLogin.classList.remove("hidden");
  sectionLoggedIn.classList.add("hidden");
  sectionLogout.classList.add("hidden");
}

// ── 이벤트 ───────────────────────────────────────────────────────────────────

document.getElementById("btn-login").addEventListener("click", () => {
  chrome.tabs.create({ url: `${API}/auth/login` });
  // 로그인 완료 후 JWT 저장 확인 polling
  const poll = setInterval(async () => {
    const { jwt } = await get(["jwt"]);
    if (jwt) {
      clearInterval(poll);
      chrome.storage.local.set({ loggedIn: true });
      renderLoggedIn(jwt);
      showMsg("로그인 완료!");
    }
  }, 2000);
  setTimeout(() => clearInterval(poll), 30000);
});

document.getElementById("btn-refresh").addEventListener("click", async () => {
  const { jwt } = await get(["jwt"]);
  if (jwt) loadSubscriptions(jwt);
});

document.getElementById("btn-logout").addEventListener("click", async () => {
  await chrome.storage.local.remove(["jwt", "loggedIn", "subscribedChannelIds", "subscribedChannels"]);
  renderLoggedOut();
  showMsg("로그아웃됐습니다.");
});

// ── 초기화 ────────────────────────────────────────────────────────────────────

(async function init() {
  const serverOk = await checkServer();

  // JWT 확인
  const { jwt, loggedIn } = await get(["jwt", "loggedIn"]);
  const isLoggedIn = !!(jwt && loggedIn);

  if (isLoggedIn) {
    renderLoggedIn(jwt);
  } else {
    renderLoggedOut();
  }

  if (!serverOk) return;

  // 현재 탭 분석
  const tab = await getCurrentTab();
  const tabUrl = tab?.url || "";
  const keyword = extractKeyword(tabUrl);

  if (keyword && isLoggedIn) {
    showSearchSection(keyword, jwt);
  } else if (keyword && !isLoggedIn) {
    // 검색어는 있지만 미로그인 → 로그인 유도 메시지
    sectionSearch.classList.remove("hidden");
    keywordText.textContent = keyword;
    videoPreview.innerHTML = `<div style="font-size:0.78rem;color:#555;padding:4px 0;">로그인하면 요약을 볼 수 있습니다.</div>`;
    document.getElementById("btn-dashboard").disabled = true;
    document.getElementById("btn-dashboard").textContent = "로그인 후 이용 가능";
  } else if (isYouTube(tabUrl)) {
    sectionIdle.classList.remove("hidden");
  } else {
    sectionNotYT.classList.remove("hidden");
  }
})();
