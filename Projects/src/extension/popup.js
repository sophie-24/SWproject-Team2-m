/**
 * popup.js — TechVisibility 팝업 로직
 *
 * 역할:
 * - 백엔드 서버 상태 확인
 * - Google OAuth 로그인 (localhost:8000/auth/login 리다이렉트)
 * - 구독 채널 목록 수집 → chrome.storage.local 저장
 * - 로그아웃 처리
 */

const API = "http://localhost:8000";

// ── DOM 참조 ─────────────────────────────────────────────────────────────────

const serverDot    = document.getElementById("server-dot");
const serverStatus = document.getElementById("server-status");
const sectionLogin    = document.getElementById("section-login");
const sectionLoggedIn = document.getElementById("section-loggedin");
const sectionLogout   = document.getElementById("section-logout");
const channelList  = document.getElementById("channel-list");
const channelCount = document.getElementById("channel-count");
const msgEl        = document.getElementById("msg");

// ── 헬퍼 ─────────────────────────────────────────────────────────────────────

function showMsg(text, isError = false) {
  msgEl.textContent = text;
  msgEl.className = isError ? "error" : "";
  if (text) setTimeout(() => { msgEl.textContent = ""; }, 4000);
}

function setServerStatus(online) {
  serverDot.className = `dot ${online ? "on" : "off"}`;
  serverStatus.textContent = online
    ? "서버 연결됨 (localhost:8000)"
    : "서버 오프라인 — 백엔드를 먼저 실행하세요";
}

async function checkServer() {
  try {
    const res = await fetch(`${API}/health`, { signal: AbortSignal.timeout(2000) });
    setServerStatus(res.ok);
  } catch {
    setServerStatus(false);
  }
}

// ── 로그인 상태 판별 ──────────────────────────────────────────────────────────

function getLoggedIn() {
  return new Promise((resolve) => {
    chrome.storage.local.get(["loggedIn"], (r) => resolve(!!r.loggedIn));
  });
}

function setLoggedIn(val) {
  return new Promise((resolve) => {
    chrome.storage.local.set({ loggedIn: val }, resolve);
  });
}

// ── 구독 채널 로드 ────────────────────────────────────────────────────────────

async function loadSubscriptions() {
  channelList.innerHTML = '<span style="color:#666;font-size:0.8rem;">불러오는 중...</span>';
  try {
    const res = await fetch(`${API}/subscriptions`);
    if (res.status === 401) {
      // 세션 만료 — 로그아웃 처리
      await setLoggedIn(false);
      chrome.storage.local.remove(["subscribedChannelIds", "subscribedChannels"]);
      renderLoggedOut();
      showMsg("세션이 만료되었습니다. 다시 로그인해주세요.", true);
      return;
    }
    if (!res.ok) throw new Error(`HTTP ${res.status}`);

    const data = await res.json();
    const channels = data.subscriptions || [];

    // 채널 ID 목록을 storage에 저장 (content.js에서 사용)
    const ids = channels.map((c) => c.channel_id);
    chrome.storage.local.set({
      subscribedChannelIds: ids,
      subscribedChannels: channels,
    });

    renderChannelList(channels);
  } catch (err) {
    channelList.innerHTML = '<span style="color:#cc4444;font-size:0.8rem;">채널 목록을 불러올 수 없습니다.</span>';
    console.error("[TechVisibility popup]", err);
  }
}

function renderChannelList(channels) {
  if (!channels.length) {
    channelList.innerHTML = '<span style="color:#666;font-size:0.8rem;">구독 채널 없음</span>';
    channelCount.textContent = "";
    return;
  }
  channelList.innerHTML = channels
    .slice(0, 50)
    .map((c) => `<div class="channel-item">${escapeHtml(c.channel_title)}</div>`)
    .join("");
  channelCount.textContent = `총 ${channels.length}개 채널 (최대 50개 표시)`;
}

function escapeHtml(str) {
  return String(str ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

// ── UI 상태 전환 ──────────────────────────────────────────────────────────────

function renderLoggedIn() {
  sectionLogin.classList.add("hidden");
  sectionLoggedIn.classList.remove("hidden");
  sectionLogout.classList.remove("hidden");
  loadSubscriptions();
}

function renderLoggedOut() {
  sectionLogin.classList.remove("hidden");
  sectionLoggedIn.classList.add("hidden");
  sectionLogout.classList.add("hidden");
  channelList.innerHTML = "";
  channelCount.textContent = "";
}

// ── 이벤트 핸들러 ─────────────────────────────────────────────────────────────

document.getElementById("btn-login").addEventListener("click", () => {
  // 백엔드 OAuth 흐름으로 이동 (새 탭)
  chrome.tabs.create({ url: `${API}/auth/login` });
  // 콜백 후 로그인 여부를 주기적으로 확인
  const poll = setInterval(async () => {
    try {
      const res = await fetch(`${API}/subscriptions`);
      if (res.ok) {
        clearInterval(poll);
        await setLoggedIn(true);
        renderLoggedIn();
        showMsg("로그인 완료!");
      }
    } catch { /* 서버 미응답 무시 */ }
  }, 2000);
  // 30초 후 polling 중단
  setTimeout(() => clearInterval(poll), 30000);
});

document.getElementById("btn-refresh").addEventListener("click", () => {
  loadSubscriptions();
  showMsg("채널 목록을 새로고침합니다.");
});

document.getElementById("btn-logout").addEventListener("click", async () => {
  await setLoggedIn(false);
  chrome.storage.local.remove(["subscribedChannelIds", "subscribedChannels"]);
  renderLoggedOut();
  showMsg("로그아웃되었습니다.");
});

// ── 초기화 ────────────────────────────────────────────────────────────────────

(async function init() {
  await checkServer();
  const loggedIn = await getLoggedIn();
  if (loggedIn) {
    renderLoggedIn();
  } else {
    renderLoggedOut();
  }
})();
