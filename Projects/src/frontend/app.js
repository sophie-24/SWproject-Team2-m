const API = "";

window.onload = () => {
  const params = new URLSearchParams(location.search);
  if (params.get("loggedIn") === "1") {
    sessionStorage.setItem("loggedIn", "1");
    history.replaceState({}, "", location.pathname);
  }
  if (sessionStorage.getItem("loggedIn")) showMain();
};

function login() {
  window.location.href = `${API}/auth/login`;
}

function logout() {
  sessionStorage.removeItem("loggedIn");
  document.getElementById("login-screen").style.display = "flex";
  document.getElementById("main-screen").style.display = "none";
}

function showMain() {
  document.getElementById("login-screen").style.display = "none";
  document.getElementById("main-screen").style.display = "block";
}

document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("search-input").addEventListener("keydown", (e) => {
    if (e.key === "Enter") doSearch();
  });
});

async function doSearch() {
  const keyword = document.getElementById("search-input").value.trim();
  if (!keyword) return;

  const el = document.getElementById("results");
  el.innerHTML = '<div class="loading">검색 중...</div>';

  try {
    const res = await fetch(`${API}/search?keyword=${encodeURIComponent(keyword)}&max_results=5`);
    const data = await res.json();

    if (!data.videos?.length) {
      el.innerHTML = '<div class="empty">검색 결과가 없습니다.</div>';
      return;
    }

    el.innerHTML = `
      <p class="status-msg">상위 ${data.videos.length}개 · 영상 클릭하면 자막 펼쳐짐</p>
      ${data.videos.map(videoItem).join("")}
    `;
  } catch {
    el.innerHTML = '<div class="empty">오류 발생. 서버가 실행 중인지 확인하세요.</div>';
  }
}

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function videoItem(v) {
  const views = v.view_count ? `조회수 ${Number(v.view_count).toLocaleString()} · ` : "";
  return `
    <div class="video-item">
      <div class="video-header" onclick="toggleTranscript('${v.video_id}', this)">
        <img src="${v.thumbnail}" alt="" loading="lazy" />
        <div class="video-info">
          <h3>${escapeHtml(v.title)}</h3>
          <button onclick="runOrchestrator('${v.video_id}', event)"
            style="background:#007bff; border:none; color:white; padding:4px 8px; border-radius:4px; font-size:0.8rem; cursor:pointer; margin-top:5px; margin-bottom:5px;">
            AI 쟁점 분석
          </button>
          <div class="meta">${escapeHtml(v.channel_title)} · ${views}${escapeHtml(v.duration)}</div>
          <span class="toggle-hint" id="hint-${v.video_id}">▼ 자막 보기</span>
        </div>
      </div>
      <div class="transcript-area" id="transcript-${v.video_id}">
        <div class="loading">자막 불러오는 중...</div>
      </div>
    </div>`;
}

const loaded = {};

async function toggleTranscript(videoId) {
  const area = document.getElementById(`transcript-${videoId}`);
  const hint = document.getElementById(`hint-${videoId}`);
  const isOpen = area.classList.contains("open");

  if (isOpen) {
    area.classList.remove("open");
    hint.textContent = "▼ 자막 보기";
    return;
  }

  area.classList.add("open");
  hint.textContent = "▲ 닫기";

  if (loaded[videoId]) return;
  loaded[videoId] = true;

  try {
    const res = await fetch(`${API}/transcript/${videoId}`, { redirect: "error" });
    if (!res.ok) {
      area.innerHTML = '<div class="empty">자막 없음</div>';
      return;
    }
    const data = await res.json();
    if (!data.transcript) {
      area.innerHTML = '<div class="empty">자막 없음</div>';
      return;
    }
    const entries = data.transcript.slice(0, 150);
    area.innerHTML = `
      <p class="status-msg">총 ${data.count}개 항목 (앞 150개 표시)</p>
      ${entries.map(t => `
        <div class="transcript-entry">
          <span class="ts">${formatTime(t.start)}</span>
          <span class="txt">${escapeHtml(t.text)}</span>
        </div>`).join("")}
    `;
  } catch {
    area.innerHTML = '<div class="empty">자막 없음</div>';
  }
}

async function runOrchestrator(videoId, event) {
  event.stopPropagation();

  const area = document.getElementById(`transcript-${videoId}`);
  const hint = document.getElementById(`hint-${videoId}`);

  area.classList.add("open");
  hint.textContent = "▲ 분석 중";
  area.innerHTML = '<div class="loading">AI 오케스트레이터 가동 중... (광고 탐지 및 RAG 분석)</div>';

  try {
    const query = document.getElementById("search-input").value;
    const res = await fetch(`${API}/ai_analyze/${videoId}?query=${encodeURIComponent(query)}`);

    if (!res.ok) throw new Error();

    const data = await res.json();
    area.innerHTML = `
      <div style="background:#2a2a2a; padding:15px; border-radius:8px; border-left:4px solid #007bff; margin-bottom:10px;">
        <h4 style="color:#007bff; margin-bottom:10px;">🤖 AI 분석 리포트</h4>
        <p style="font-size:0.85rem; color:#aaa;">⚠️ 광고 의심 점수: <span style="color:#ff6666;">${data.ad_score}점</span></p>
        <hr style="border:0.5px solid #444; margin:10px 0;">
        <div class="txt" style="white-space:pre-wrap; font-size:0.9rem; line-height:1.6;">${data.final_analysis}</div>
      </div>
    `;
  } catch {
    area.innerHTML = '<div class="empty">분석 중 오류가 발생했습니다. 백엔드 서버를 확인하세요.</div>';
  }
}

function formatTime(sec) {
  const m = Math.floor(sec / 60).toString().padStart(2, "0");
  const s = Math.floor(sec % 60).toString().padStart(2, "0");
  return `${m}:${s}`;
}
