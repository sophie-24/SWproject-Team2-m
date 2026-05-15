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
  var item = document.getElementById("s" + n);
  var ind  = document.getElementById("s" + n + "-icon");
  if (!item || !ind) return;
  item.classList.remove("active", "done");
  if (state) item.classList.add(state);
  if (state === "active") {
    ind.innerHTML = '<div class="step-ring"></div>';
  } else if (state === "done") {
    ind.innerHTML = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#16a34a" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>';
  } else {
    ind.innerHTML = '<span class="step-num">' + n + '</span>';
  }
}

// ── 탭 전환 ───────────────────────────────────────────────────────────────────

function switchTab(tabName) {
  document.querySelectorAll(".tab-btn").forEach(function (b) { b.classList.remove("active"); });
  document.querySelectorAll(".tab-panel").forEach(function (p) { p.classList.remove("active"); });
  var btn = document.querySelector('[data-tab="' + tabName + '"]');
  var panel = document.getElementById("tab-" + tabName);
  if (btn) btn.classList.add("active");
  if (panel) panel.classList.add("active");
}

document.querySelectorAll(".tab-btn[data-tab]").forEach(function (btn) {
  btn.addEventListener("click", function () {
    if (btn.dataset.tab) switchTab(btn.dataset.tab);
  });
});

/* 설정 버튼 — 대시보드로 이동 */
var btnSettings = document.getElementById("btn-settings");
if (btnSettings) {
  btnSettings.addEventListener("click", function () {
    chrome.tabs.create({ url: API_BASE + "/dashboard.html" });
  });
}

/* VIEW ALL — SOURCES 탭으로 전환 */
document.addEventListener("click", function (e) {
  if (e.target && e.target.id === "btn-view-all") {
    switchTab("sources");
  }
});

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

  document.getElementById("kw-title-s").textContent = keyword;

  /* 캐시 히트 안내 배너 */
  var cacheNotice = "";
  if (cached) {
    cacheNotice = '<div class="cache-notice">⚡ 기존 분석 결과입니다</div>';
  }

  var SUMMARY_TITLE = {
    "정보탐색형": "핵심 인사이트",
    "유희탐색형": "화제 포인트",
    "구매탐색형": "장점 요약",
  };
  var FACTS_TITLE = {
    "정보탐색형": "전문가 분석",
    "유희탐색형": "반응 및 의견",
    "구매탐색형": "전문가 평가",
  };

  var summaryHTML = cacheNotice;
  if (summaryLines.length) {
    var bullets = summaryLines.map(function (l) {
      return '<div class="bullet-item"><span class="bullet-dot dot-red"></span><span>' + esc(l) + '</span></div>';
    }).join("");
    var summaryTitle = SUMMARY_TITLE[category] || "주요 요약";
    summaryHTML += '<div class="section-block border-red"><div class="section-header"><div class="section-icon-box icon-red">⚡</div><div class="section-title-text">' + summaryTitle + '</div></div><div class="bullet-list">' + bullets + '</div></div>';
  }
  if (commonFacts.length) {
    var factBullets = commonFacts.map(function (f) {
      return '<div class="bullet-item"><span class="bullet-dot dot-blue"></span><span>' + esc(f) + '</span></div>';
    }).join("");
    var factsTitle = FACTS_TITLE[category] || "공통 사실";
    summaryHTML += '<div class="section-block border-gray"><div class="section-header"><div class="section-icon-box icon-gray">📊</div><div class="section-title-text">' + factsTitle + '</div></div><div class="bullet-list">' + factBullets + '</div></div>';
  }
  document.getElementById("summary-sections").innerHTML = summaryHTML || '<div style="color:#555;font-size:0.82rem;padding:10px 0;">요약 정보가 없습니다.</div>';

  /* 쟁점 섹션 (INSIGHTS 탭 내) */
  var controversyHTML = "";
  if (controversies.length) {
    var cBullets = controversies.map(function (c) {
      return '<div class="bullet-item"><span class="bullet-dot dot-yellow"></span><span>' + esc(c) + '</span></div>';
    }).join("");
    controversyHTML = '<div class="section-block" style="border-left-color:#f59e0b"><div class="section-header"><div class="section-icon-box icon-yellow">⚡</div><div class="section-title-text">주요 쟁점</div></div><div class="bullet-list">' + cBullets + '</div></div>';
  }
  document.getElementById("controversy-section").innerHTML = controversyHTML;

  /* 소스 프리뷰 (INSIGHTS 탭 하단, 최대 3개) */
  function buildVideoCard(v, compact) {
    var vid = v.video_id || v.id || "";
    var url = "https://youtube.com/watch?v=" + esc(vid);
    var thumbSrc = v.thumbnail_url || ("https://img.youtube.com/vi/" + esc(vid) + "/mqdefault.jpg");
    if (compact) {
      var thumbEl = vid
        ? '<div class="source-thumb-compact"><a href="' + url + '" target="_blank"><img src="' + esc(thumbSrc) + '" alt="" loading="lazy"></a></div>'
        : '<div class="source-thumb-placeholder-compact">▶</div>';
      var ch = v.channel_title ? '<div class="source-channel-compact">' + esc(v.channel_title).toUpperCase() + '</div>' : "";
      return '<div class="source-card-compact">' + thumbEl + '<div class="source-info-compact"><a class="source-title-compact" href="' + url + '" target="_blank">' + esc(v.title) + '</a>' + ch + '</div></div>';
    } else {
      var thumb = thumbSrc
        ? '<div class="video-thumb-wrap"><a href="' + url + '" target="_blank"><img class="video-thumb" src="' + esc(thumbSrc) + '" alt="" loading="lazy"></a></div>'
        : '<div class="video-thumb-placeholder">▶</div>';
      var adBadge   = v.ad_detected ? '<span class="badge badge-ad">광고 포함</span>' : '<span class="badge badge-noad">광고 없음</span>';
      var credBadge = v.credibility_score != null ? '<span class="badge badge-cred">신뢰도 ' + Math.round(v.credibility_score * 100) + '%</span>' : "";
      var chBadge   = v.channel_title ? '<span class="channel-badge">' + esc(v.channel_title).toUpperCase() + '</span>' : "";
      return '<div class="video-card"><div class="video-card-inner">' + thumb + '<div class="video-info"><a class="video-title-text" href="' + url + '" target="_blank">' + esc(v.title) + '</a>' + (v.summary ? '<div class="video-subtitle">' + esc(v.summary) + '</div>' : "") + '<div class="video-meta-row">' + chBadge + adBadge + credBadge + '</div></div></div></div>';
    }
  }

  if (videos.length) {
    document.getElementById("sources-in-insights").classList.remove("hidden");
    document.getElementById("sources-preview").innerHTML = videos.slice(0, 3).map(function(v) { return buildVideoCard(v, true); }).join("");
    document.getElementById("sources-list").innerHTML = videos.map(function(v) { return buildVideoCard(v, false); }).join("");
  } else {
    document.getElementById("sources-in-insights").classList.add("hidden");
    document.getElementById("sources-list").innerHTML = '<div style="color:#555;font-size:0.82rem;padding:10px 0;">영상 정보가 없습니다.</div>';
  }

  showScreen("screen-results");
}

// ── 분석 요청 ─────────────────────────────────────────────────────────────────

async function analyze(keyword, jwt) {
  currentKeyword = keyword;
  currentJwt = jwt;
  var loadingKw = document.getElementById("loading-kw");
  if (loadingKw) loadingKw.textContent = keyword;
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
      /* JWT 만료 → storage 정리 후 로그인 화면으로 자동 전환
         재로그인 완료 시 btn-login 핸들러가 현재 탭 키워드로 분석을 자동 재시작함 */
      chrome.storage.local.remove(["jwt", "loggedIn"]);
      currentJwt = "";
      showScreen("screen-login");
      return;
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
  /* 팝업 창으로 OAuth 진행 → /auth/extension-done이 window.close() 처리
     JWT 저장은 background.js tabs.onUpdated → storage.onChanged로 감지 (polling 불필요) */
  window.open(
    API_BASE + "/auth/login?ext=1",
    "tubify_auth",
    "width=520,height=660,left=300,top=80,toolbar=no,menubar=no,scrollbars=yes"
  );
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
  if (!jwt) { showScreen("screen-login"); return; }
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
  } else {
    analyze(keyword.trim(), jwt);
  }
})();

// ── storage 변화 감지 — 로그인 완료 + 플로팅 버튼 키워드 ────────────────────
chrome.storage.onChanged.addListener(function (changes, area) {
  if (area !== "local") return;

  // 로그인 완료 감지 — polling 없이 즉시 반응
  // /auth/extension-done → background.js tabs.onUpdated → storage.jwt 저장 → 여기서 캐치
  if (changes.jwt && changes.jwt.newValue && !currentJwt) {
    var jwt = changes.jwt.newValue;
    currentJwt = jwt;
    chrome.storage.local.get(["pendingKeyword"], function (stored) {
      var keyword = stored.pendingKeyword || "";
      if (stored.pendingKeyword) chrome.storage.local.remove("pendingKeyword");
      if (keyword.trim()) {
        analyze(keyword.trim(), jwt);
      } else {
        chrome.tabs.query({ active: true, currentWindow: true }, function (tabs) {
          var tab = tabs[0];
          try {
            var u = new URL(tab && tab.url);
            if (u.hostname.includes("youtube.com") && u.pathname === "/results") {
              keyword = u.searchParams.get("search_query") || "";
            }
          } catch (e) {}
          if (keyword.trim()) analyze(keyword.trim(), jwt);
          else showScreen("screen-empty");
        });
      }
    });
  }

  // 검색 키워드 변화 감지 — 플로팅 버튼 클릭 시 트리거
  if (changes.pendingKeyword) {
    var keyword = changes.pendingKeyword.newValue;
    if (!keyword || !currentJwt) return;
    chrome.storage.local.remove("pendingKeyword");
    analyze(keyword.trim(), currentJwt);
  }
});
