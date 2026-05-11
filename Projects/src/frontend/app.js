const API = "";
/* chrome://extensions/ 에서 Tubify 익스텐션 ID를 복사해 여기에 붙여넣기 */
const EXTENSION_IDS = ["haagaoipcidfnhojkjdiajieiejocckk", "caaoacncggbohojcejagaijcpoigcpga"];

window.onload = () => {
  const params = new URLSearchParams(location.search);

  /* OAuth 콜백 후 JWT를 URL 파라미터로 받아 저장 후 home으로 이동 */
  const token = params.get("token");
  if (token) {
    localStorage.setItem("access_token", token);
    sessionStorage.setItem("loggedIn", "1");
    // 익스텐션에 토큰 전달
    if (typeof chrome !== "undefined" && chrome.runtime) {
      EXTENSION_IDS.forEach(id => {
        try { chrome.runtime.sendMessage(id, { type: "SET_TOKEN", token }, () => {}); } catch (_) {}
      });
    }
    // 익스텐션 팝업이 window.open()으로 열었을 경우 자동 닫기
    if (window.opener !== null) { setTimeout(() => window.close(), 400); return; }
    window.location.href = "/intro.html";
    return;
  }

  if (params.get("loggedIn") === "1") {
    sessionStorage.setItem("loggedIn", "1");
    history.replaceState({}, "", location.pathname);
  }
  /* 이미 로그인된 유저 → 마이페이지로 바로 이동 */
  if (sessionStorage.getItem("loggedIn") || localStorage.getItem("access_token")) {
    window.location.href = "/mypage.html";
  }
};

function getJwt() {
  return localStorage.getItem("access_token") || "";
}

function login() {
  window.location.href = `${API}/auth/login`;
}

function logout() {
  localStorage.removeItem("access_token");
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
    const jwt = getJwt();
    const res = await fetch(`${API}/ai_analyze/${videoId}?query=${encodeURIComponent(query)}`, {
      headers: jwt ? { "Authorization": `Bearer ${jwt}` } : {}
    });

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

// ── Pipeline A: 키워드 AI 분석 (analyze_search) ─────────────────────────────
async function doAnalyze() {
  const keyword = document.getElementById("search-input").value.trim();
  if (!keyword) { alert("키워드를 입력해주세요."); return; }
  const jwt = getJwt();
  if (!jwt) { alert("로그인이 필요합니다."); return; }

  const resultEl = document.getElementById("analyze-result");
  const btn = document.getElementById("analyze-btn");
  resultEl.style.display = "block";
  resultEl.innerHTML = `<div style="color:#aaa;text-align:center;padding:20px">
    <div style="font-size:1.2rem;margin-bottom:8px">⚙️</div>
    <div>"${escapeHtml(keyword)}" 분석 중...</div>
    <div style="font-size:0.78rem;color:#666;margin-top:6px">영상 선정 → 의도 분류 → AI 교차분석 순으로 진행됩니다</div>
  </div>`;
  btn.disabled = true;
  btn.textContent = "분석 중...";

  try {
    const res = await fetch(`${API}/analyze_search?keyword=${encodeURIComponent(keyword)}`, {
      headers: { "Authorization": `Bearer ${jwt}` }
    });
    if (res.status === 401) { alert("로그인이 필요합니다."); resultEl.style.display = "none"; return; }
    if (!res.ok) throw new Error("서버 오류");
    const d = await res.json();

    const esc = s => String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    const intentBadge = { "유희형": "🎉 유희형", "지식형": "📚 지식형", "구매형": "🛒 구매형" }[d.intent_type] || d.intent_type || "";
    const summaryHtml = (d.summary_lines || []).map(l => `<div style="margin:4px 0;color:#ccc">• ${esc(l)}</div>`).join("");
    const factsHtml = (d.common_facts || []).map(f => `<div style="margin:3px 0;color:#bbb;font-size:0.83rem">• ${esc(f)}</div>`).join("");
    const controversiesHtml = (d.controversies || []).map(c =>
      `<div style="margin:4px 0;background:#2a1a1a;padding:6px 10px;border-radius:6px;color:#f5a6a6;font-size:0.83rem">${esc(c)}</div>`
    ).join("");
    const prosHtml = (d.pros || []).map(p => `<div style="color:#8de0a0;font-size:0.83rem;margin:3px 0">✅ ${esc(p)}</div>`).join("");
    const consHtml = (d.cons || []).map(c => `<div style="color:#e08d8d;font-size:0.83rem;margin:3px 0">⚠️ ${esc(c)}</div>`).join("");
    const videosHtml = (d.recommended_videos || d.videos || []).slice(0, 3).map(v =>
      `<a href="${esc(v.url || "https://youtube.com/watch?v=" + v.video_id)}" target="_blank"
          style="display:flex;align-items:center;gap:10px;background:#1a1a1a;border-radius:8px;padding:8px;text-decoration:none;color:inherit;margin-bottom:6px">
        ${v.thumbnail ? `<img src="${esc(v.thumbnail)}" style="width:80px;height:45px;object-fit:cover;border-radius:4px;flex-shrink:0">` : ""}
        <div style="min-width:0">
          <div style="font-size:0.82rem;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(v.title)}</div>
          <div style="font-size:0.72rem;color:#666">${esc(v.channel_title)}</div>
          ${v.summary ? `<div style="font-size:0.72rem;color:#888;margin-top:2px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(v.summary)}</div>` : ""}
        </div>
      </a>`
    ).join("");

    resultEl.innerHTML = `
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px">
        <div style="font-size:1rem;font-weight:700;color:#fff">🔍 "${esc(d.keyword || keyword)}" 분석 결과</div>
        <div style="display:flex;gap:6px">
          <span style="font-size:0.72rem;background:#1a2a3a;color:#6ab4f5;padding:2px 8px;border-radius:10px">${esc(d.category || "")}</span>
          <span style="font-size:0.72rem;background:#1a2a1a;color:#6af596;padding:2px 8px;border-radius:10px">${intentBadge}</span>
        </div>
      </div>
      ${summaryHtml ? `<div style="margin-bottom:14px"><div style="font-size:0.75rem;color:#888;margin-bottom:6px">핵심 요약</div>${summaryHtml}</div>` : ""}
      ${factsHtml ? `<div style="margin-bottom:14px"><div style="font-size:0.75rem;color:#888;margin-bottom:6px">공통 결론</div>${factsHtml}</div>` : ""}
      ${controversiesHtml ? `<div style="margin-bottom:14px"><div style="font-size:0.75rem;color:#888;margin-bottom:6px">쟁점</div>${controversiesHtml}</div>` : ""}
      ${(prosHtml || consHtml) ? `<div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:14px">
        ${prosHtml ? `<div><div style="font-size:0.75rem;color:#888;margin-bottom:6px">장점</div>${prosHtml}</div>` : ""}
        ${consHtml ? `<div><div style="font-size:0.75rem;color:#888;margin-bottom:6px">단점</div>${consHtml}</div>` : ""}
      </div>` : ""}
      ${videosHtml ? `<div><div style="font-size:0.75rem;color:#888;margin-bottom:8px">관련 영상</div>${videosHtml}</div>` : ""}`;
  } catch (e) {
    resultEl.innerHTML = `<div style="color:#f5a6a6;text-align:center;padding:16px">분석 실패 — 잠시 후 다시 시도해주세요.</div>`;
  } finally {
    btn.disabled = false;
    btn.textContent = "AI 분석";
  }
}
