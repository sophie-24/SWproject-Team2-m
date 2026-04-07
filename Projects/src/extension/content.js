/**
 * content.js — TechVisibility 크롬 익스텐션
 *
 * 역할:
 * 1. 유튜브 검색어 실시간 감지 (SPA 네비게이션 포함)
 * 2. 백엔드 /analyze_search 호출
 * 3. 검색 결과 상단에 AI 요약 대시보드 오버레이 삽입
 */

const API = "http://localhost:8000";
const OVERLAY_ID = "techvisibility-overlay";
const DEBOUNCE_MS = 800;

let lastKeyword = "";
let debounceTimer = null;

// ── 유틸 ────────────────────────────────────────────────────────────────────

function escapeHtml(str) {
  return String(str ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function getSearchKeyword() {
  const params = new URLSearchParams(window.location.search);
  return (params.get("search_query") || "").trim();
}

// ── 스토리지에서 구독 채널 ID 목록 읽기 ─────────────────────────────────────

function getSubscribedChannelIds() {
  return new Promise((resolve) => {
    chrome.storage.local.get(["subscribedChannelIds"], (result) => {
      resolve(result.subscribedChannelIds || []);
    });
  });
}

// ── 오버레이 DOM 생성 ────────────────────────────────────────────────────────

function createOverlay() {
  const existing = document.getElementById(OVERLAY_ID);
  if (existing) return existing;

  const el = document.createElement("div");
  el.id = OVERLAY_ID;
  el.innerHTML = `
    <div id="tv-header">
      <span id="tv-title">✦ TechVisibility AI 분석</span>
      <button id="tv-close">✕</button>
    </div>
    <div id="tv-body">
      <div id="tv-loading" class="tv-loading">분석 중...</div>
      <div id="tv-content" style="display:none"></div>
    </div>
  `;

  // 스타일
  Object.assign(el.style, {
    position: "relative",
    width: "100%",
    background: "#0f0f0f",
    border: "1px solid #333",
    borderRadius: "12px",
    padding: "0",
    marginBottom: "16px",
    fontFamily: "'Segoe UI', sans-serif",
    color: "#f1f1f1",
    zIndex: "9999",
    overflow: "hidden",
  });

  injectStyles();

  el.querySelector("#tv-close").addEventListener("click", () => {
    el.style.display = "none";
  });

  return el;
}

function injectStyles() {
  if (document.getElementById("tv-styles")) return;
  const style = document.createElement("style");
  style.id = "tv-styles";
  style.textContent = `
    #techvisibility-overlay #tv-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 12px 16px;
      background: #1a1a1a;
      border-bottom: 1px solid #2a2a2a;
    }
    #techvisibility-overlay #tv-title {
      font-size: 0.9rem;
      font-weight: 700;
      color: #ff4444;
      letter-spacing: 0.02em;
    }
    #techvisibility-overlay #tv-close {
      background: none;
      border: none;
      color: #888;
      cursor: pointer;
      font-size: 1rem;
      line-height: 1;
    }
    #techvisibility-overlay #tv-close:hover { color: #f1f1f1; }
    #techvisibility-overlay #tv-body { padding: 16px; }
    #techvisibility-overlay .tv-loading {
      text-align: center;
      color: #888;
      padding: 24px 0;
      font-size: 0.9rem;
    }
    #techvisibility-overlay .tv-loading::after {
      content: '';
      animation: tv-dots 1.2s infinite;
    }
    @keyframes tv-dots {
      0%   { content: ''; }
      33%  { content: '.'; }
      66%  { content: '..'; }
      100% { content: '...'; }
    }
    #techvisibility-overlay .tv-section { margin-bottom: 16px; }
    #techvisibility-overlay .tv-section-title {
      font-size: 0.78rem;
      font-weight: 700;
      color: #888;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      margin-bottom: 8px;
    }
    #techvisibility-overlay .tv-summary-lines {
      display: flex;
      flex-direction: column;
      gap: 6px;
    }
    #techvisibility-overlay .tv-summary-line {
      font-size: 0.9rem;
      color: #f1f1f1;
      line-height: 1.5;
      padding-left: 10px;
      border-left: 2px solid #ff4444;
    }
    #techvisibility-overlay .tv-conclusion {
      font-size: 0.88rem;
      color: #ccc;
      line-height: 1.6;
      background: #1a1a1a;
      border-radius: 8px;
      padding: 10px 12px;
    }
    #techvisibility-overlay .tv-chips {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
    }
    #techvisibility-overlay .tv-chip {
      font-size: 0.8rem;
      background: #1e1e1e;
      border: 1px solid #333;
      border-radius: 20px;
      padding: 4px 10px;
      color: #ccc;
    }
    #techvisibility-overlay .tv-chip.controversy {
      border-color: #ff6633;
      color: #ff9966;
    }
    #techvisibility-overlay .tv-video-list {
      display: flex;
      flex-direction: column;
      gap: 8px;
    }
    #techvisibility-overlay .tv-video-card {
      display: flex;
      gap: 10px;
      align-items: flex-start;
      background: #1a1a1a;
      border-radius: 8px;
      padding: 10px;
    }
    #techvisibility-overlay .tv-rank {
      font-size: 1rem;
      font-weight: 700;
      color: #ff4444;
      min-width: 20px;
      text-align: center;
    }
    #techvisibility-overlay .tv-video-thumb {
      width: 80px;
      min-width: 80px;
      aspect-ratio: 16/9;
      object-fit: cover;
      border-radius: 4px;
      background: #333;
    }
    #techvisibility-overlay .tv-video-meta { flex: 1; overflow: hidden; }
    #techvisibility-overlay .tv-video-title {
      font-size: 0.85rem;
      font-weight: 600;
      color: #f1f1f1;
      margin-bottom: 4px;
      display: -webkit-box;
      -webkit-line-clamp: 2;
      -webkit-box-orient: vertical;
      overflow: hidden;
    }
    #techvisibility-overlay .tv-video-title a {
      color: inherit;
      text-decoration: none;
    }
    #techvisibility-overlay .tv-video-title a:hover { color: #ff4444; }
    #techvisibility-overlay .tv-video-info {
      font-size: 0.75rem;
      color: #888;
    }
    #techvisibility-overlay .tv-badge {
      display: inline-block;
      font-size: 0.7rem;
      padding: 2px 6px;
      border-radius: 4px;
      margin-left: 4px;
    }
    #techvisibility-overlay .tv-badge.subscribed {
      background: #1a3a1a;
      color: #44cc44;
      border: 1px solid #2a6a2a;
    }
    #techvisibility-overlay .tv-badge.ad {
      background: #3a1a1a;
      color: #cc4444;
      border: 1px solid #6a2a2a;
    }
    #techvisibility-overlay .tv-category-tag {
      display: inline-block;
      font-size: 0.75rem;
      padding: 3px 10px;
      border-radius: 12px;
      background: #1e2a3a;
      color: #6699ff;
      border: 1px solid #2a3a5a;
      margin-bottom: 12px;
    }
    #techvisibility-overlay .tv-divider {
      border: none;
      border-top: 1px solid #2a2a2a;
      margin: 14px 0;
    }
    #techvisibility-overlay .tv-error {
      color: #cc4444;
      font-size: 0.85rem;
      text-align: center;
      padding: 16px 0;
    }
  `;
  document.head.appendChild(style);
}

// ── 오버레이 삽입 위치 찾기 ──────────────────────────────────────────────────

function findInsertTarget() {
  // 검색 결과 컨테이너 후보
  const selectors = [
    "ytd-section-list-renderer",
    "#contents.ytd-section-list-renderer",
    "ytd-search ytd-item-section-renderer",
    "#page-manager",
  ];
  for (const sel of selectors) {
    const el = document.querySelector(sel);
    if (el) return el;
  }
  return null;
}

function mountOverlay(overlayEl) {
  if (overlayEl.parentElement) return; // 이미 마운트됨

  const target = findInsertTarget();
  if (!target) return;

  target.parentElement
    ? target.parentElement.insertBefore(overlayEl, target)
    : document.body.prepend(overlayEl);
}

// ── 결과 렌더 ────────────────────────────────────────────────────────────────

function renderDashboard(data) {
  const categoryTag = data.category
    ? `<span class="tv-category-tag">${escapeHtml(data.category)}</span>`
    : "";

  // 핵심 요약
  const summaryHtml = (data.summary_lines || [])
    .filter(Boolean)
    .map((line) => `<div class="tv-summary-line">${escapeHtml(line)}</div>`)
    .join("");

  // 공통 결론
  const conclusionHtml = data.common_conclusion
    ? `<div class="tv-section">
         <div class="tv-section-title">공통 결론</div>
         <div class="tv-conclusion">${escapeHtml(data.common_conclusion)}</div>
       </div><hr class="tv-divider">`
    : "";

  // 공통 사실
  const factsHtml =
    data.common_facts?.length > 0
      ? `<div class="tv-section">
           <div class="tv-section-title">공통 사실</div>
           <div class="tv-chips">
             ${data.common_facts
               .map((f) => `<span class="tv-chip">${escapeHtml(f)}</span>`)
               .join("")}
           </div>
         </div><hr class="tv-divider">`
      : "";

  // 쟁점
  const controversyHtml =
    data.controversies?.length > 0
      ? `<div class="tv-section">
           <div class="tv-section-title">쟁점</div>
           <div class="tv-chips">
             ${data.controversies
               .map((c) => `<span class="tv-chip controversy">${escapeHtml(c)}</span>`)
               .join("")}
           </div>
         </div><hr class="tv-divider">`
      : "";

  // 추천 영상
  const videoHtml =
    data.recommended_videos?.length > 0
      ? `<div class="tv-section">
           <div class="tv-section-title">추천 영상</div>
           <div class="tv-video-list">
             ${data.recommended_videos
               .slice(0, 5)
               .map((v, i) => renderVideoCard(v, i + 1))
               .join("")}
           </div>
         </div>`
      : "";

  return `
    ${categoryTag}
    <div class="tv-section">
      <div class="tv-section-title">핵심 요약</div>
      <div class="tv-summary-lines">${summaryHtml}</div>
    </div>
    <hr class="tv-divider">
    ${conclusionHtml}
    ${factsHtml}
    ${controversyHtml}
    ${videoHtml}
  `;
}

function renderVideoCard(v, rank) {
  const url = `https://www.youtube.com/watch?v=${escapeHtml(v.video_id)}`;
  const views = v.view_count
    ? `조회수 ${Number(v.view_count).toLocaleString()}`
    : "";
  const subscribedBadge = v.is_subscribed
    ? `<span class="tv-badge subscribed">구독중</span>`
    : "";
  const adBadge = v.ad_detected
    ? `<span class="tv-badge ad">광고포함</span>`
    : "";
  const score = v.final_score != null
    ? `점수 ${(v.final_score * 100).toFixed(0)}`
    : "";

  return `
    <div class="tv-video-card">
      <span class="tv-rank">${rank}</span>
      <img class="tv-video-thumb" src="${escapeHtml(v.thumbnail || "")}" alt="" loading="lazy">
      <div class="tv-video-meta">
        <div class="tv-video-title">
          <a href="${url}" target="_blank">${escapeHtml(v.title)}</a>
          ${subscribedBadge}${adBadge}
        </div>
        <div class="tv-video-info">${escapeHtml(v.channel_title)} · ${views} · ${score}</div>
        ${v.summary ? `<div style="font-size:0.78rem;color:#888;margin-top:4px;">${escapeHtml(v.summary)}</div>` : ""}
      </div>
    </div>
  `;
}

// ── 분석 실행 ────────────────────────────────────────────────────────────────

async function runAnalysis(keyword) {
  if (!keyword || keyword === lastKeyword) return;
  lastKeyword = keyword;

  const overlay = createOverlay();
  overlay.style.display = "";
  mountOverlay(overlay);

  const loadingEl = overlay.querySelector("#tv-loading");
  const contentEl = overlay.querySelector("#tv-content");
  loadingEl.style.display = "";
  contentEl.style.display = "none";

  try {
    const subscribedChannelIds = await getSubscribedChannelIds();

    const res = await fetch(`${API}/analyze_search`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        keyword,
        subscribed_channel_ids: subscribedChannelIds,
      }),
    });

    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();

    contentEl.innerHTML = renderDashboard(data);
    loadingEl.style.display = "none";
    contentEl.style.display = "";
  } catch (err) {
    loadingEl.style.display = "none";
    contentEl.innerHTML = `<div class="tv-error">분석 실패: 백엔드 서버(localhost:8000)를 확인하세요.</div>`;
    contentEl.style.display = "";
    console.error("[TechVisibility]", err);
  }
}

// ── 검색어 변화 감지 ─────────────────────────────────────────────────────────

function onUrlChange() {
  if (!window.location.pathname.startsWith("/results")) return;

  const keyword = getSearchKeyword();
  if (!keyword || keyword === lastKeyword) return;

  clearTimeout(debounceTimer);
  debounceTimer = setTimeout(() => runAnalysis(keyword), DEBOUNCE_MS);
}

// YouTube SPA 네비게이션 감지: yt-navigate-finish 이벤트 활용
window.addEventListener("yt-navigate-finish", onUrlChange);

// 첫 로드 시 즉시 실행
onUrlChange();
