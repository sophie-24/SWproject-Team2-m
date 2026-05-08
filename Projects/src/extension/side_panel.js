// side_panel.js — Tubify 사이드패널 스크립트
// API 주소는 config.js의 API_BASE를 사용합니다 (side_panel.html에서 config.js 선행 로드됨)

// ── 상태 변수 ──────────────────────────────────────────────────────────────────

let currentKeyword = "";
let currentJwt = "";

// ── 유틸 ──────────────────────────────────────────────────────────────────────

function esc(s) {
  return String(s || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

function showScreen(id) {
  ["screen-login", "screen-empty", "screen-loading", "screen-error", "screen-results"].forEach(function (s) {
    var el = document.getElementById(s);
    if (el) el.classList.toggle("hidden", s !== id);
  });
}

function setStep(n, state) {
  var row = document.getElementById("s" + n);
  var icon = document.getElementById("s" + n + "-icon");
  if (!row || !icon) return;
  row.classList.remove("active", "done");
  if (state) row.classList.add(state);
  if (state === "active") { icon.innerHTML = '<span class="spinner"></span>'; }
  else if (state === "done") { icon.textContent = "OK"; }
  else { icon.textContent = ["", "?", "?", "?"][n]; }
}

// ── 탭 전환 ───────────────────────────────────────────────────────────────────

document.querySelectorAll(".tab-btn").forEach(function (btn) {
  btn.addEventListener("click", function () {
    document.querySelectorAll(".tab-btn").forEach(function (b) { b.classList.remove("active"); });
    document.querySelectorAll(".tab-panel").forEach(function (p) { p.classList.remove("active"); });
    btn.classList.add("active");
    document.getElementById("tab-" + btn.dataset.tab).classList.add("active");
  });
});

// ── 카테고리별 색상 테마 ───────────────────────────────────────────────────────

var CATEGORY_THEME = {
  "정보탐색형":    { color: "#6699ff", border: "#1e2d4a", bg: "#111827" },
  "비교구매형":    { color: "#ff9944", border: "#3d2210", bg: "#1a1207" },
  "학습튜토리얼형": { color: "#44cc88", border: "#0d3322", bg: "#071a12" },
};

// ── 결과 렌더링 ───────────────────────────────────────────────────────────────

function renderResults(data) {
  var keyword      = data.keyword || currentKeyword;
  var videos       = data.recommended_videos || data.videos || [];
  var commonFacts  = data.common_facts || [];
  var controversies = data.controversies || [];
  var summaryLines = data.summary_lines || [];
  var conclusion   = data.common_conclusion || "";
  var category     = data.category || "";
  var cached       = data.cached || false;
  var theme        = CATEGORY_THEME[category] || CATEGORY_THEME["정보탐색형"];

  document.getElementById("kw-title-s").textContent = keyword;
  document.getElementById("kw-title-i").textContent = keyword;

  /* 캐시 히트 안내 배너 */
  var cacheNotice = "";
  if (cached) {
    cacheNotice = '<div class="cache-notice">⚡ 기존 분석 결과입니다</div>';
  }

  var summaryHTML = cacheNotice;
  if (category) {
    summaryHTML += '<div class="category-badge" style="background:' + theme.bg + ';color:' + theme.color + ';border:1px solid ' + theme.border + '">' + esc(category) + '</div>';
  }
  if (summaryLines.length) {
    var bullets = summaryLines.map(function (l) {
      return '<div class="bullet-item"><span class="bullet-dot dot-red"></span><span>' + esc(l) + '</span></div>';
    }).join("");
    summaryHTML += '<div class="section-block border-red"><div class="section-header"><div class="section-icon-box icon-red">⚡</div><div class="section-title-text">주요 혁신 및 스펙 요약</div></div><div class="bullet-list">' + bullets + '</div></div>';
  }
  if (commonFacts.length) {
    var factBullets = commonFacts.map(function (f) {
      return '<div class="bullet-item"><span class="bullet-dot dot-blue"></span><span>' + esc(f) + '</span></div>';
    }).join("");
    summaryHTML += '<div class="section-block border-gray"><div class="section-header"><div class="section-icon-box icon-gray">📊</div><div class="section-title-text">시장 기대 및 전문가 분석</div></div><div class="bullet-list">' + factBullets + '</div></div>';
  }
  document.getElementById("summary-sections").innerHTML = summaryHTML || '<div style="color:#555;font-size:0.82rem;padding:10px 0;">요약 정보가 없습니다.</div>';

  var insightsHTML = "";
  if (conclusion) {
    insightsHTML += '<div class="conclusion-box"><div style="font-size:0.68rem;font-weight:700;color:#ff4444;letter-spacing:.5px;text-transform:uppercase;margin-bottom:6px;">&#128161; AI 결론</div>' + esc(conclusion) + '</div>';
  }
  if (controversies.length) {
    var cBullets = controversies.map(function (c) {
      return '<div class="bullet-item"><span class="bullet-dot dot-yellow"></span><span>' + esc(c) + '</span></div>';
    }).join("");
    insightsHTML += '<div class="section-block"><div class="section-header"><div class="section-icon-box icon-yellow">&#9889;</div><div class="section-title-text">쟁점 및 논란</div></div><div class="bullet-list">' + cBullets + '</div></div>';
  }
  document.getElementById("insights-sections").innerHTML = insightsHTML || '<div style="color:#555;font-size:0.82rem;padding:10px 0;">인사이트 정보가 없습니다.</div>';

  if (videos.length) {
    document.getElementById("sources-list").innerHTML = videos.map(function (v) {
      var vid = v.video_id || v.id || "";
      var thumb = v.thumbnail_url
        ? '<div class="video-thumb-wrap"><a href="https://youtube.com/watch?v=' + esc(vid) + '" target="_blank"><img class="video-thumb" src="' + esc(v.thumbnail_url) + '" alt="" loading="lazy"></a></div>'
        : '<div class="video-thumb-placeholder">▶</div>';
      var adBadge   = v.ad_detected ? '<span class="badge badge-ad">광고 포함</span>' : '<span class="badge badge-noad">광고 없음</span>';
      var credBadge = v.credibility_score != null ? '<span class="badge badge-cred">신뢰도 ' + Math.round(v.credibility_score * 100) + '%</span>' : "";
      var chBadge   = v.channel_title ? '<span class="channel-badge">' + esc(v.channel_title).toUpperCase() + '</span>' : "";
      var url = "https://youtube.com/watch?v=" + esc(vid);
      return '<div class="video-card"><div class="video-card-inner">' + thumb + '<div class="video-info"><a class="video-title-text" href="' + url + '" target="_blank">' + esc(v.title) + '</a>' + (v.summary ? '<div class="video-subtitle">' + esc(v.summary) + '</div>' : "") + '<div class="video-meta-row">' + chBadge + adBadge + credBadge + '</div></div></div></div>';
    }).join("");
  } else {
    document.getElementById("sources-list").innerHTML = '<div style="color:#555;font-size:0.82rem;padding:10px 0;">영상 정보가 없습니다.</div>';
  }

  showScreen("screen-results");
}

// ── 분석 요청 ─────────────────────────────────────────────────────────────────

async function analyze(keyword, jwt) {
  currentKeyword = keyword;
  currentJwt = jwt;
  showScreen("screen-loading");
  setStep(1, "active"); setStep(2, ""); setStep(3, "");
  try {
    await new Promise(function (r) { setTimeout(r, 500); });
    setStep(1, "done"); setStep(2, "active");
    await new Promise(function (r) { setTimeout(r, 500); });
    setStep(2, "done"); setStep(3, "active");

    var res = await fetch(API_BASE + "/analyze_search?keyword=" + encodeURIComponent(keyword), {
      headers: { "Authorization": "Bearer " + jwt }
    });
    if (res.status === 401) {
      document.getElementById("err-msg").textContent = "세션이 만료됐습니다.";
      document.getElementById("err-sub").textContent = "팝업에서 다시 로그인해주세요.";
      showScreen("screen-error"); return;
    }
    if (!res.ok) {
      var err = await res.json().catch(function () { return {}; });
      document.getElementById("err-msg").textContent = err.detail || ("서버 오류 " + res.status);
      document.getElementById("err-sub").textContent = "잠시 후 다시 시도해주세요.";
      showScreen("screen-error"); return;
    }
    var data = await res.json();
    setStep(3, "done");
    await new Promise(function (r) { setTimeout(r, 300); });
    renderResults(data);
  } catch (e) {
    document.getElementById("err-msg").textContent = "백엔드에 연결할 수 없습니다.";
    document.getElementById("err-sub").textContent = "서버가 실행 중인지 확인하세요.";
    showScreen("screen-error");
  }
}

// ── 버튼 이벤트 ───────────────────────────────────────────────────────────────

document.getElementById("btn-retry").addEventListener("click", function () {
  if (currentKeyword && currentJwt) analyze(currentKeyword, currentJwt);
});
document.getElementById("btn-refresh").addEventListener("click", function () {
  if (currentKeyword && currentJwt) analyze(currentKeyword, currentJwt);
});
document.getElementById("btn-login").addEventListener("click", function () {
  /* 팝업 창으로 OAuth 진행 → window.opener 존재 → app.js가 자동 닫기 + SET_TOKEN 전송 */
  var authWin = window.open(
    API_BASE + "/auth/login",
    "tubify_auth",
    "width=520,height=660,left=300,top=80,toolbar=no,menubar=no,scrollbars=yes"
  );

  /* JWT가 storage에 저장될 때까지 1초마다 확인 */
  var poll = setInterval(async function () {
    var stored = await new Promise(function (r) {
      chrome.storage.local.get(["jwt", "loggedIn"], r);
    });
    if (!stored.jwt) return;

    clearInterval(poll);
    try { authWin && authWin.close(); } catch (e) {}

    currentJwt = stored.jwt;

    /* 로그인 완료 후 현재 탭 키워드로 바로 분석 시작 */
    var tabs = await new Promise(function (r) {
      chrome.tabs.query({ active: true, currentWindow: true }, r);
    });
    var tab = tabs[0];
    var keyword = "";
    try {
      var u = new URL(tab && tab.url);
      if (u.hostname.includes("youtube.com") && u.pathname === "/results") {
        keyword = u.searchParams.get("search_query") || "";
      }
    } catch (e) {}

    if (keyword.trim()) {
      analyze(keyword.trim(), stored.jwt);
    } else {
      showScreen("screen-empty");
    }
  }, 1000);

  /* 60초 후 polling 자동 종료 */
  setTimeout(function () { clearInterval(poll); }, 60000);
});

// ── 초기화 ────────────────────────────────────────────────────────────────────

(async function init() {
  var stored = await new Promise(function (r) {
    chrome.storage.local.get(["jwt", "loggedIn", "pendingKeyword"], r);
  });
  var jwt            = stored.jwt;
  var loggedIn       = stored.loggedIn;
  var pendingKeyword = stored.pendingKeyword;

  if (pendingKeyword) chrome.storage.local.remove("pendingKeyword");
  if (!jwt || !loggedIn) { showScreen("screen-login"); return; }
  currentJwt = jwt;

  /* 키워드 우선순위: pendingKeyword(storage) → 현재 탭 URL */
  var keyword = pendingKeyword || "";

  if (!keyword) {
    var tabs = await new Promise(function (r) {
      chrome.tabs.query({ active: true, currentWindow: true }, r);
    });
    var tab = tabs[0];
    try {
      var u = new URL(tab && tab.url);
      /* YouTube 검색 결과 페이지: /results?search_query=... */
      if (u.hostname.includes("youtube.com") && u.pathname === "/results") {
        keyword = u.searchParams.get("search_query") || "";
      }
    } catch (e) { }
  }

  if (!keyword.trim()) {
    showScreen("screen-empty");
    return;
  }

  analyze(keyword.trim(), jwt);
})();
