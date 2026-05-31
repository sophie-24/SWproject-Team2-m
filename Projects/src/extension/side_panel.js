// side_panel.js — Tubify 사이드패널 스크립트
// API 주소는 config.js의 API_BASE를 사용합니다

// ── 상태 변수 ──────────────────────────────────────────────────────────────────

let currentKeyword = "";
let currentJwt = "";
let currentVideoId = "";
let heartedTopic = "";
let currentMode = "search"; // "search" | "watch"
let _abortController = null; // 진행 중인 분석 요청 취소용

// 패널 닫힐 때 진행 중인 요청 abort
window.addEventListener("unload", function () {
  if (_abortController) _abortController.abort();
});

// ── 유틸 ──────────────────────────────────────────────────────────────────────

function showToast(msg) {
  var t = document.getElementById("toast");
  if (!t) return;
  t.textContent = msg;
  t.classList.add("show");
  setTimeout(function () { t.classList.remove("show"); }, 2800);
}

function setHeartState(isHearted) {
  document.querySelectorAll(".btn-heart").forEach(function (btn) {
    btn.classList.toggle("hearted", isHearted);
  });
}

async function checkHeartState(keyword) {
  if (!currentJwt || !keyword) return;
  try {
    var res = await fetch(API_BASE + "/interests", {
      headers: { "Authorization": "Bearer " + currentJwt }
    });
    if (!res.ok) return;
    var data = await res.json();
    var interests = data.interests || [];
    var kw = keyword.toLowerCase().replace(/\s+/g, " ").trim();
    var matched = interests.find(function (i) {
      return (i.normalized_topic || "").toLowerCase().replace(/\s+/g, " ").trim() === kw
        || (i.topic || i.category || "").toLowerCase().replace(/\s+/g, " ").trim() === kw;
    });
    if (matched) {
      heartedTopic = matched.topic || matched.category || keyword;
      setHeartState(true);
    } else {
      heartedTopic = "";
      setHeartState(false);
    }
  } catch (e) {}
}

async function toggleHeart() {
  if (!currentJwt) { showToast("로그인 후 이용할 수 있습니다."); return; }
  var isHearted = document.querySelectorAll(".btn-heart.hearted").length > 0;

  if (isHearted) {
    var topic = heartedTopic || currentKeyword;
    try {
      var res = await fetch(API_BASE + "/interests/" + encodeURIComponent(topic), {
        method: "DELETE",
        headers: { "Authorization": "Bearer " + currentJwt }
      });
      if (res.ok) {
        heartedTopic = "";
        setHeartState(false);
        showToast("관심 토픽에서 제거됐어요. 더 이상 메일을 받지 않아요.");
      } else {
        showToast("오류가 발생했어요. 다시 시도해주세요.");
      }
    } catch (e) { showToast("서버에 연결할 수 없어요."); }
  } else {
    try {
      var payload = { title: currentKeyword };
      if (currentVideoId) payload.video_id = currentVideoId;
      var res = await fetch(API_BASE + "/interests", {
        method: "POST",
        headers: { "Authorization": "Bearer " + currentJwt, "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      if (res.status === 409) {
        showToast("관심 토픽은 최대 5개까지 저장할 수 있어요.");
        return;
      }
      if (res.ok) {
        var data = await res.json();
        heartedTopic = data.topic || currentKeyword;
        setHeartState(true);
        showToast("'" + heartedTopic + "' 관련 뉴스레터를 보내드릴게요! 💌");
      } else {
        var errBody = await res.json().catch(function () { return {}; });
        var errMsg = (errBody.detail && typeof errBody.detail === "string") ? errBody.detail : ("서버 오류 " + res.status);
        showToast(errMsg);
      }
    } catch (e) { showToast("서버에 연결할 수 없어요."); }
  }
}

function stripMd(str) {
  if (!str) return str;
  return str
    .replace(/\*{1,3}([^*\n]+?)\*{1,3}/g, '$1')
    .replace(/\*+/g, '')
    .replace(/^#{1,6}\s*/gm, '')
    .trim();
}

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

var btnSettings = document.getElementById("btn-settings");
if (btnSettings) {
  btnSettings.addEventListener("click", function () {
    chrome.tabs.create({ url: API_BASE + "/mypage.html" });
  });
}

document.addEventListener("click", function (e) {
  if (e.target && e.target.id === "btn-view-all") switchTab("sources");
});

// ── 신뢰도 토글 헬퍼 ─────────────────────────────────────────────────────────

function toggleCredDetail(id) {
  var detail = document.getElementById("cred-detail-" + id);
  var btn    = document.getElementById("cred-btn-" + id);
  if (!detail || !btn) return;
  var isOpen = detail.style.display !== "none";
  detail.style.display = isOpen ? "none" : "block";
  btn.textContent = isOpen ? "더 보기 ▾" : "접기 ▴";
}

function buildAdBanner(adScore, adSignals) {
  function layerLabel(layer) {
    if (!layer) return "";
    if (layer === "paid_flag")   return "Layer 3";
    if (layer === "gemini")      return "Layer 4";
    if (layer === "transcript")  return "Layer 2";
    if (layer === "description") return "Layer 1";
    return "";
  }
  var signals = Array.isArray(adSignals) ? adSignals.filter(function(s) { return s.score > 0; }).slice(0, 3) : [];
  var signalRows = signals.map(function(s, idx) {
    var lbl = layerLabel(s.layer);
    var prefix = idx === signals.length - 1 ? '└' : '├';
    return '<div style="font-size:10px;color:#c2410c;margin-top:3px;font-family:monospace;">'
      + '<span style="color:#f97316;">' + prefix + ' </span>'
      + (lbl ? '<span style="font-weight:700;">' + lbl + '</span>: ' : '')
      + esc(s.evidence || s.rule)
      + '</div>';
  }).join('');
  return '<div class="cache-notice" style="background:#fff7ed;border-color:#fed7aa;color:#ea580c;margin-bottom:12px;">'
    + '<div style="font-weight:600;">⚠️ 광고 의심 ' + adScore + '점</div>'
    + signalRows
    + '</div>';
}

function buildCredibilityCard(credScore, components, uniqId) {
  var pct      = Math.round(credScore * 100);
  var label    = pct >= 70 ? "높음" : pct >= 40 ? "보통" : "낮음";
  var color    = pct >= 70 ? "#16a34a" : pct >= 40 ? "#d97706" : "#dc2626";
  var compMap  = [
    { key: "transcript_quality",  label: "자막 품질" },
    { key: "ad_free",             label: "광고 없음" },
    { key: "channel_credibility", label: "채널 신뢰도" },
  ];
  // 단일 영상(watch)이 아닐 때만 정보 일관성 표시 (단일 영상은 교차 비교 없어 항상 0)
  if (uniqId !== "watch") {
    compMap.push({ key: "consistency", label: "정보 일관성" });
  }
  var hasComponents = components && Object.keys(components).length > 0;
  var summaryHtml =
    '<div style="display:flex;align-items:center;gap:8px;">'
    + '<div style="flex:1;height:6px;background:#e6e8ea;border-radius:3px;overflow:hidden;">'
    + '<div style="width:' + pct + '%;height:100%;background:' + color + ';border-radius:3px;"></div>'
    + '</div>'
    + '<span style="font-size:12px;font-weight:700;color:' + color + ';">' + pct + '% ' + label + '</span>'
    + (hasComponents
      ? '<button id="cred-btn-' + uniqId + '" onclick="toggleCredDetail(\'' + uniqId + '\')" '
        + 'style="font-size:10px;color:#888;background:none;border:none;cursor:pointer;padding:0;white-space:nowrap;">'
        + '더 보기 ▾</button>'
      : '')
    + '</div>';
  var detailRows = hasComponents ? compMap.map(function(c, idx) {
    var v = components[c.key] || 0;
    var vPct = Math.round(v * 100);
    var vColor = vPct >= 70 ? "#16a34a" : vPct >= 40 ? "#d97706" : "#dc2626";
    var prefix = idx === compMap.length - 1 ? '└' : '├';
    var filledCount = Math.round(vPct / 100 * 6);
    var bar = '█'.repeat(filledCount) + '░'.repeat(6 - filledCount);
    var annotation = (c.key === 'ad_free' && vPct < 60)
      ? ' <span style="font-size:9px;color:#94a3b8;">← 광고 의심 반영</span>' : '';
    return '<div style="display:flex;align-items:center;gap:4px;margin-bottom:3px;font-family:monospace;font-size:11px;">'
      + '<span style="color:#94a3b8;">' + prefix + '</span>'
      + '<span style="color:#888;min-width:56px;flex-shrink:0;font-family:\'Noto Sans KR\',sans-serif;font-size:10px;">' + c.label + '</span>'
      + '<span style="color:' + vColor + ';letter-spacing:-0.5px;">' + bar + '</span>'
      + '<span style="color:#666;margin-left:4px;white-space:nowrap;">' + vPct + '%</span>'
      + annotation
      + '</div>';
  }).join('') : '';
  var detailHtml = hasComponents
    ? '<div id="cred-detail-' + uniqId + '" style="display:none;margin-top:8px;padding-top:8px;border-top:1px solid #e6e8ea;">'
      + detailRows + '</div>'
    : '';
  return summaryHtml + detailHtml;
}

// ── 단일 영상 요약 파싱 ──────────────────────────────────────────────────────

function parseAnalysisToSections(text) {
  if (!text) return [];
  text = text.trim();

  // 문단 분리
  var chunks = text.split(/\n\s*\n/).map(function(c) { return c.trim(); }).filter(Boolean);

  if (chunks.length === 0) return [{ title: "AI 요약", body: text }];
  if (chunks.length === 1) return [{ title: "AI 요약", body: text }];

  return chunks.slice(0, 4).map(function (chunk, i) {
    var lines = chunk.split('\n').map(function(l) { return l.trim(); }).filter(Boolean);
    var first = (lines[0] || '').replace(/^[#*•\-\d.]+\s*/, '').replace(/\*+/g, '').trim();

    if (first.length <= 50 && lines.length > 1) {
      return { title: first, body: lines.slice(1).join(' ') };
    }
    return { title: "포인트 " + (i + 1), body: chunk };
  });
}

var SECTION_ICONS = [
  // ⚡ 번개
  '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/></svg>',
  // 🔍 분석
  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>',
  // 📋 메모
  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>',
  // 💡 아이디어
  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="2" x2="12" y2="6"/><line x1="12" y1="18" x2="12" y2="22"/><line x1="4.93" y1="4.93" x2="7.76" y2="7.76"/><line x1="16.24" y1="16.24" x2="19.07" y2="19.07"/><line x1="2" y1="12" x2="6" y2="12"/><line x1="18" y1="12" x2="22" y2="12"/><line x1="4.93" y1="19.07" x2="7.76" y2="16.24"/><line x1="16.24" y1="7.76" x2="19.07" y2="4.93"/></svg>'
];

// ── 단일 영상 요약 렌더링 ──────────────────────────────────────────────────────
// TODO [디자인 개선 포인트]
// 1. 영상 요약 본문 폰트: font-size 13px → 13.5px, line-height 1.6 → 1.75 (가독성↑)
// 2. section-block 카드 배경: 흰색(#fff) + box-shadow: 0 1px 4px rgba(0,0,0,0.07) 추가 (입체감)
// 3. 핵심 주장 bullet: <li> 앞에 빨간 점(•) 대신 체크 아이콘(✓) 또는 컬러 dot으로 교체
// 4. 신뢰도 바: 높이 6px → 8px, border-radius 키워서 pill 형태로 (더 세련됨)
// 5. 광고 의심 배너: 현재 inline style → 전용 CSS class로 분리
// 6. 카드 간격(margin-bottom): 12px → 16px으로 여유 확보

function renderVideoSummary(videoTitle, aiData) {
  // SUMMARY 탭 헤더 설정
  document.getElementById("kw-title-s").textContent = videoTitle;
  document.getElementById("kw-header-row").style.display = "";
  document.getElementById("kw-underline").style.display = "";

  var html = "";

  if (aiData) {
    var adScore = aiData.ad_score || 0;
    if (adScore > 5) {
      html += buildAdBanner(adScore, aiData.ad_signals);
    }

    var cards = [];

    // summary 문자열 → 첫 번째 카드
    var summaryText = (aiData.summary || "").trim();
    if (summaryText && summaryText !== "분석 실패") {
      var summaryBody = (summaryText === "자막 없음")
        ? "이 영상은 자막 정보를 가져올 수 없어 AI 요약을 제공하기 어렵습니다."
        : stripMd(summaryText);
      cards.push({ title: "영상 요약", body: summaryBody, icon: 0 });
    }

    // key_claims 배열 → 카드 추가 (최대 2개)
    var claims = Array.isArray(aiData.key_claims) ? aiData.key_claims : [];
    if (claims.length > 0) {
      var claimBullets = claims.slice(0, 5).map(function(c) { return '<li>' + esc(c) + '</li>'; }).join('');
      cards.push({ title: "핵심 주장", bodyHtml: '<ul class="bullet-list">' + claimBullets + '</ul>', icon: 1 });
    }

    // 신뢰도 점수 → 세 번째 카드 (더 보기 토글 포함)
    if (typeof aiData.credibility_score === "number") {
      cards.push({
        title: "신뢰도",
        bodyHtml: buildCredibilityCard(aiData.credibility_score, aiData.credibility_components, "watch"),
        icon: 2
      });
    }

    if (cards.length > 0) {
      cards.forEach(function(card) {
        var bodyContent = card.bodyHtml
          ? card.bodyHtml
          : '<p class="section-body-text">' + esc(card.body || "").replace(/\n/g, '<br>') + '</p>';
        html += '<div class="section-block border-red">'
          + '<div class="section-header">'
          + '<div class="section-icon-box icon-red">' + SECTION_ICONS[card.icon] + '</div>'
          + '<div class="section-title-text">' + esc(card.title) + '</div>'
          + '</div>'
          + bodyContent
          + '</div>';
      });
    } else {
      html = '<div style="color:#515f74;font-size:13px;line-height:1.65;">자막 정보가 없어 분석할 수 없습니다.</div>';
    }
  } else {
    html = '<div style="color:#515f74;font-size:13px;line-height:1.65;">영상 분석을 가져올 수 없습니다.</div>';
  }

  document.getElementById("summary-content").innerHTML = html;
}

// ── 결과 렌더링 ───────────────────────────────────────────────────────────────

function renderResults(data, watchMode) {
  var keyword       = data.keyword || currentKeyword;
  var videos        = data.recommended_videos || data.videos || [];
  var commonFacts   = data.common_facts || [];
  var commonFactsCitations   = data.common_facts_citations || [];
  var controversies = data.controversies || [];
  var controversiesCitations = data.controversies_citations || [];
  var summaryLines  = data.summary_lines || [];
  var summaryCitations       = data.summary_citations || [];
  var category      = data.category || "";
  var layout        = data.layout || "summary_focus";
  var pros          = data.pros || [];
  var cons          = data.cons || [];
  var cached        = data.cached || false;

  var SUMMARY_TITLE = { "정보탐색형": "핵심 인사이트", "유희탐색형": "화제 포인트", "구매탐색형": "핵심 요약" };
  var FACTS_TITLE   = { "정보탐색형": "전문가 분석", "유희탐색형": "반응 및 의견", "구매탐색형": "전문가 평가" };

  // ── 출처 뱃지 렌더링 헬퍼 ──────────────────────────────────────────────────
  function _citationBadges(cites) {
    if (!Array.isArray(cites) || cites.length === 0) return "";
    // 채널명 중복 제거
    var seen = {};
    var unique = cites.filter(function(c) {
      if (!c.channel_title || seen[c.channel_title]) return false;
      seen[c.channel_title] = true;
      return true;
    });
    return unique.map(function(c, idx) {
      var url = c.video_id ? "https://youtube.com/watch?v=" + esc(c.video_id) : "#";
      var label = esc(c.channel_title || "출처");
      var extra = unique.length > 1 && idx === 0 ? ' +' + (unique.length - 1) : '';
      // 첫 번째만 표시, 나머지는 +N 으로 표기
      if (idx > 0) return "";
      return '<a href="' + url + '" target="_blank" class="citation-badge" '
        + 'title="' + esc(c.title || c.channel_title) + '">'
        + label + extra
        + '</a>';
    }).join("");
  }

  // ── 레이아웃별 인사이트 섹션 조립 ─────────────────────────────────────────
  function _makeBullets(items, dotColor, citations) {
    return items.map(function(item, idx) {
      var cites = (citations && citations[idx]) ? citations[idx] : [];
      var badges = _citationBadges(cites);
      return '<div class="bullet-item"><span class="bullet-dot ' + dotColor + '"></span>'
        + '<span>' + esc(item) + (badges ? '&nbsp;' + badges : '') + '</span></div>';
    }).join("");
  }
  function _makeSection(borderCls, iconCls, iconIdx, title, bulletsHTML) {
    return '<div class="section-block ' + borderCls + '"><div class="section-header">'
      + '<div class="section-icon-box ' + iconCls + '">' + SECTION_ICONS[iconIdx] + '</div>'
      + '<div class="section-title-text">' + title + '</div></div>'
      + '<div class="bullet-list">' + bulletsHTML + '</div></div>';
  }

  function buildInsightsSections() {
    var html = cached ? '<div class="cache-notice">⚡ 기존 분석 결과입니다</div>' : "";

    if (layout === "comparison") {
      // 구매형: 장점 → 단점 → 요약 → 공통사실 순
      if (pros.length)
        html += _makeSection("border-green", "icon-green", 1, "장점", _makeBullets(pros, "dot-blue"));
      if (cons.length)
        html += _makeSection("border-yellow", "icon-yellow", 2, "단점 / 주의사항", _makeBullets(cons, "dot-yellow"));
      if (summaryLines.length)
        html += _makeSection("border-red", "icon-red", 0, SUMMARY_TITLE[category] || "핵심 요약", _makeBullets(summaryLines, "dot-red", summaryCitations));
      if (commonFacts.length)
        html += _makeSection("border-gray", "icon-gray", 1, FACTS_TITLE[category] || "공통 사실", _makeBullets(commonFacts, "dot-blue", commonFactsCitations));

    } else if (layout === "card_highlight") {
      // 유희형: 요약 → 쟁점 인라인 (공통사실 생략)
      if (summaryLines.length)
        html += _makeSection("border-red", "icon-red", 0, SUMMARY_TITLE[category] || "화제 포인트", _makeBullets(summaryLines, "dot-red", summaryCitations));
      if (controversies.length)
        html += _makeSection("border-yellow", "icon-yellow", 2, "반응이 갈리는 부분", _makeBullets(controversies, "dot-yellow", controversiesCitations));

    } else {
      // summary_focus (지식형, 기본): 요약 → 공통사실
      if (summaryLines.length)
        html += _makeSection("border-red", "icon-red", 0, SUMMARY_TITLE[category] || "주요 요약", _makeBullets(summaryLines, "dot-red", summaryCitations));
      if (commonFacts.length)
        html += _makeSection("border-gray", "icon-gray", 1, FACTS_TITLE[category] || "공통 사실", _makeBullets(commonFacts, "dot-blue", commonFactsCitations));
    }
    return html;
  }

  // SUMMARY 탭 버튼: watch=보임, search=숨김
  var summaryTabBtn = document.querySelector('[data-tab="summary"]');
  if (summaryTabBtn) summaryTabBtn.style.display = watchMode ? "" : "none";
  // INSIGHTS 내 검색 헤더: watch=키워드 표시(하트 없음), search=키워드+하트
  if (watchMode) {
    document.getElementById("kw-title-insights").textContent = keyword || "";
    document.getElementById("btn-heart-insights").style.display = "none";
    document.getElementById("insights-kw-header").style.display = keyword ? "" : "none";
    document.getElementById("insights-kw-underline").style.display = keyword ? "" : "none";
  }

  if (watchMode) {
    // watch 모드: SUMMARY 탭은 renderVideoSummary가 처리 → 여기선 INSIGHTS 탭만 채움
    document.getElementById("insights-sections").innerHTML =
      buildInsightsSections() || '<div style="color:#555;font-size:0.82rem;padding:10px 0;">관련 영상 분석 정보가 없습니다.</div>';
  } else {
    // search 모드: INSIGHTS 탭에 내용, SUMMARY 탭은 비움
    document.getElementById("kw-title-insights").textContent = keyword;
    document.getElementById("insights-kw-header").style.display = "";
    document.getElementById("insights-kw-underline").style.display = "";
    document.getElementById("kw-header-row").style.display = "none";
    document.getElementById("kw-underline").style.display = "none";
    document.getElementById("summary-content").innerHTML = "";

    var repVideo = videos.find(function (v) { return !v.ad_detected && v.video_id; }) || videos[0];
    currentVideoId = (repVideo && repVideo.video_id) || "";
    setHeartState(false);
    heartedTopic = "";
    checkHeartState(keyword);

    document.getElementById("insights-sections").innerHTML =
      buildInsightsSections() || '<div style="color:#555;font-size:0.82rem;padding:10px 0;">요약 정보가 없습니다.</div>';

    switchTab("insights");
  }

  // 쟁점: card_highlight는 인라인에 포함했으므로 별도 섹션 비움
  var controversyHTML = "";
  if (controversies.length && layout !== "card_highlight") {
    controversyHTML = '<div class="section-block border-yellow"><div class="section-header">'
      + '<div class="section-icon-box icon-yellow">' + SECTION_ICONS[2] + '</div>'
      + '<div class="section-title-text">주요 쟁점</div></div>'
      + '<div class="bullet-list">' + _makeBullets(controversies, "dot-yellow", controversiesCitations) + '</div></div>';
  }
  document.getElementById("controversy-section").innerHTML = controversyHTML;

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
      var adBadge = v.ad_detected ? '<span class="badge badge-ad">광고 포함</span>' : '<span class="badge badge-noad">광고 없음</span>';
      var chBadge = v.channel_title ? '<span class="channel-badge">' + esc(v.channel_title).toUpperCase() + '</span>' : "";
      // 신뢰도 + selection_tags를 "신뢰도 85% · ViewRate 기반 선정 · 구독 채널" 형태로 합치기
      var credParts = [];
      if (v.credibility_score != null) credParts.push('신뢰도 ' + Math.round(v.credibility_score * 100) + '%');
      (v.selection_tags || []).forEach(function(t) { credParts.push(esc(t)); });
      var credLine = credParts.length
        ? '<div style="font-size:10px;color:#2563eb;margin-top:2px;">' + credParts.join(' · ') + '</div>'
        : "";
      return '<div class="video-card"><div class="video-card-inner">' + thumb + '<div class="video-info"><a class="video-title-text" href="' + url + '" target="_blank">' + esc(v.title) + '</a>' + (v.summary ? '<div class="video-subtitle">' + esc(v.summary) + '</div>' : "") + '<div class="video-meta-row">' + chBadge + adBadge + '</div>' + credLine + '</div></div></div>';
    }
  }

  if (videos.length) {
    document.getElementById("sources-in-insights").classList.remove("hidden");
    document.getElementById("sources-preview").innerHTML = videos.map(function(v) { return buildVideoCard(v, true); }).join("");
    document.getElementById("sources-list").innerHTML = videos.map(function(v) { return buildVideoCard(v, false); }).join("");
  } else {
    document.getElementById("sources-in-insights").classList.add("hidden");
    document.getElementById("sources-list").innerHTML = '<div style="color:#555;font-size:0.82rem;padding:10px 0;">영상 정보가 없습니다.</div>';
  }

  showScreen("screen-results");
}

// ── 키워드 검색 분석 ──────────────────────────────────────────────────────────

async function analyze(keyword, jwt) {
  currentKeyword = keyword;
  currentJwt = jwt;
  currentMode = "search";

  var loadingKw = document.getElementById("loading-kw");
  if (loadingKw) loadingKw.textContent = keyword;

  // 로딩 스텝 레이블 (검색 모드)
  setStepLabel(1, "영상 검색", "관련 유튜브 영상 수집 중");
  setStepLabel(2, "자막 분석", "각 영상의 자막 처리 중");
  setStepLabel(3, "AI 교차 분석", "영상 간 핵심 내용 비교 중");

  showScreen("screen-loading");
  setStep(1, "active"); setStep(2, ""); setStep(3, "");

  // search 모드 진입: summary-content 초기화
  document.getElementById("summary-content").innerHTML = "";

  try {
    await new Promise(function (r) { setTimeout(r, 500); });
    setStep(1, "done"); setStep(2, "active");
    await new Promise(function (r) { setTimeout(r, 500); });
    setStep(2, "done"); setStep(3, "active");

    _abortController = new AbortController();
    var res = await fetch(API_BASE + "/analyze_search?keyword=" + encodeURIComponent(keyword), {
      headers: { "Authorization": "Bearer " + jwt },
      signal: _abortController.signal,
    });
    if (res.status === 401) {
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
    renderResults(data, false);
  } catch (e) {
    if (e && e.name === "AbortError") return; // 패널 닫혀서 취소된 경우 무시
    document.getElementById("err-msg").textContent = "백엔드에 연결할 수 없습니다.";
    document.getElementById("err-sub").textContent = "서버가 실행 중인지 확인하세요.";
    showScreen("screen-error");
  }
}

// ── 단일 영상 분석 (watch 페이지) ─────────────────────────────────────────────

async function analyzeWatch(videoId, videoTitle, jwt) {
  currentJwt = jwt;
  currentVideoId = videoId;
  currentMode = "watch";

  // 제목에서 키워드 추출 (YouTube 탭 제목 suffix 제거)
  var keyword = videoTitle.replace(/\s*[-|]\s*YouTube\s*$/, '').trim();
  currentKeyword = keyword;

  var loadingKw = document.getElementById("loading-kw");
  if (loadingKw) loadingKw.textContent = videoTitle;

  setStepLabel(1, "영상 요약", "현재 영상 자막 분석 중");
  setStepLabel(2, "관련 영상 검색", "주제 관련 영상 수집 중");
  setStepLabel(3, "AI 교차 분석", "영상 간 핵심 내용 비교 중");

  showScreen("screen-loading");
  setStep(1, "active"); setStep(2, ""); setStep(3, "");

  try {
    // /analyze_video 단일 호출 (영상 요약 + 관련 영상 인사이트 통합)
    setStep(1, "active");
    _abortController = new AbortController();
    var res = await fetch(API_BASE + "/analyze_video", {
      method: "POST",
      headers: {
        "Authorization": "Bearer " + jwt,
        "Content-Type": "application/json"
      },
      body: JSON.stringify({ video_id: videoId, title: videoTitle }),
      signal: _abortController.signal,
    });

    if (res.status === 401) {
      chrome.storage.local.remove(["jwt", "loggedIn"]);
      currentJwt = "";
      showScreen("screen-login");
      return;
    }
    if (!res.ok) {
      var err = await res.json().catch(function () { return {}; });
      document.getElementById("err-msg").textContent = err.detail || ("서버 오류 " + res.status);
      document.getElementById("err-sub").textContent = "잠시 후 다시 시도해주세요.";
      showScreen("screen-error");
      return;
    }

    var data = await res.json();
    setStep(1, "done"); setStep(2, "active");
    await new Promise(function (r) { setTimeout(r, 300); });
    setStep(2, "done"); setStep(3, "active");
    await new Promise(function (r) { setTimeout(r, 300); });
    setStep(3, "done");
    await new Promise(function (r) { setTimeout(r, 200); });

    // 키워드: extracted_topic 우선, 없으면 제목
    currentKeyword = data.extracted_topic || keyword;
    setHeartState(false);
    heartedTopic = "";
    checkHeartState(currentKeyword);

    // SUMMARY 탭: 단일 영상 전체 분석 (single_video 중첩 또는 flat 구조 모두 대응)
    var sv = data.single_video || data;
    renderVideoSummary(videoTitle, {
      summary:                sv.summary || sv.video_summary || "",
      key_claims:             sv.key_claims || [],
      credibility_score:      sv.credibility_score,
      credibility_components: sv.credibility_components || {},
      ad_score:               sv.ad_score,
      ad_detected:            sv.ad_detected,
      ad_signals:             sv.ad_signals || [],
    });

    // INSIGHTS + SOURCES 탭
    var ka = data.keyword_analysis || {};
    renderResults({
      keyword:             currentKeyword,
      summary_lines:       ka.summary_lines || [],
      common_facts:        ka.common_facts || [],
      controversies:       ka.controversies || [],
      recommended_videos:  ka.recommended_videos || data.sources || [],
      category:            ka.category || "",
      cached:              data.cached || false,
    }, true);

    switchTab("summary");

  } catch (e) {
    if (e && e.name === "AbortError") return; // 패널 닫혀서 취소된 경우 무시
    document.getElementById("err-msg").textContent = "백엔드에 연결할 수 없습니다.";
    document.getElementById("err-sub").textContent = "서버가 실행 중인지 확인하세요.";
    showScreen("screen-error");
  }
}

function setStepLabel(n, label, desc) {
  var lEl = document.getElementById("s" + n + "-label");
  var dEl = document.getElementById("s" + n + "-desc");
  if (lEl) lEl.textContent = label;
  if (dEl) dEl.textContent = desc;
}

// ── 버튼 이벤트 ───────────────────────────────────────────────────────────────

document.addEventListener("click", function (e) {
  if (e.target.closest(".btn-heart")) toggleHeart();
});

document.getElementById("btn-retry").addEventListener("click", function () {
  if (currentMode === "watch" && currentVideoId) {
    chrome.tabs.query({ active: true, currentWindow: true }, function (tabs) {
      var tab = tabs && tabs[0];
      var title = (tab && tab.title) || currentKeyword;
      analyzeWatch(currentVideoId, title, currentJwt);
    });
  } else if (currentKeyword && currentJwt) {
    analyze(currentKeyword, currentJwt);
  }
});

document.getElementById("btn-refresh").addEventListener("click", function () {
  chrome.tabs.query({ active: true, currentWindow: true }, function (tabs) {
    var tab = tabs && tabs[0];
    if (!tab || !currentJwt) return;
    try {
      var u = new URL(tab.url);
      if (u.hostname.includes("youtube.com") && u.pathname === "/watch") {
        var vid = u.searchParams.get("v");
        if (vid) { analyzeWatch(vid, tab.title, currentJwt); return; }
      }
      if (u.hostname.includes("youtube.com") && u.pathname === "/results") {
        var kw = u.searchParams.get("search_query") || "";
        if (kw) { analyze(kw, currentJwt); return; }
      }
    } catch (e) {}
    if (currentKeyword) analyze(currentKeyword, currentJwt);
  });
});

document.getElementById("btn-login").addEventListener("click", function () {
  chrome.tabs.create({ url: API_BASE + "/auth/login" });

  var poll = setInterval(async function () {
    var stored = await new Promise(function (r) {
      chrome.storage.local.get(["jwt", "loggedIn"], r);
    });
    if (!stored.jwt) return;
    clearInterval(poll);
    currentJwt = stored.jwt;

    var tabs = await new Promise(function (r) {
      chrome.tabs.query({ active: true, currentWindow: true }, r);
    });
    var tab = tabs[0];
    try {
      var u = new URL(tab && tab.url);
      if (u.hostname.includes("youtube.com") && u.pathname === "/watch") {
        var vid = u.searchParams.get("v");
        if (vid) { analyzeWatch(vid, tab.title, stored.jwt); return; }
      }
      if (u.hostname.includes("youtube.com") && u.pathname === "/results") {
        var kw = u.searchParams.get("search_query") || "";
        if (kw) { analyze(kw.trim(), stored.jwt); return; }
      }
    } catch (e) {}
    showScreen("screen-empty");
  }, 1000);

  setTimeout(function () { clearInterval(poll); }, 60000);
});

// ── 초기화 ────────────────────────────────────────────────────────────────────

(async function init() {
  var stored = await new Promise(function (r) {
    chrome.storage.local.get(["jwt", "loggedIn", "pendingKeyword"], r);
  });
  var jwt            = stored.jwt;
  var pendingKeyword = stored.pendingKeyword;

  if (pendingKeyword) chrome.storage.local.remove("pendingKeyword");
  if (!jwt) { showScreen("screen-login"); return; }
  currentJwt = jwt;

  var keyword = pendingKeyword || "";

  var tabs = await new Promise(function (r) {
    chrome.tabs.query({ active: true, currentWindow: true }, r);
  });
  var tab = tabs[0];

  try {
    var u = new URL(tab && tab.url);

    // YouTube 영상 시청 중
    if (u.hostname.includes("youtube.com") && u.pathname === "/watch") {
      var videoId = u.searchParams.get("v");
      var videoTitle = (tab.title || "").replace(/\s*[-|]\s*YouTube\s*$/, '').trim() || "영상 분석";
      if (videoId) {
        analyzeWatch(videoId, videoTitle, jwt);
        return;
      }
    }

    // YouTube 검색 결과 페이지
    if (u.hostname.includes("youtube.com") && u.pathname === "/results") {
      keyword = u.searchParams.get("search_query") || keyword;
    }
  } catch (e) {}

  if (!keyword.trim()) {
    showScreen("screen-empty");
  } else {
    analyze(keyword.trim(), jwt);
  }
})();

// ── storage 변화 감지 ──────────────────────────────────────────────────────────
chrome.storage.onChanged.addListener(function (changes, area) {
  if (area !== "local") return;

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
            if (u.hostname.includes("youtube.com") && u.pathname === "/watch") {
              var vid = u.searchParams.get("v");
              if (vid) { analyzeWatch(vid, tab.title, jwt); return; }
            }
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

  if (changes.pendingKeyword) {
    var keyword = changes.pendingKeyword.newValue;
    if (!keyword || !currentJwt) return;
    chrome.storage.local.remove("pendingKeyword");
    // 현재 탭 URL 확인 → watch 페이지면 analyzeWatch, 아니면 analyze
    chrome.tabs.query({ active: true, currentWindow: true }, function (tabs) {
      var tab = tabs && tabs[0];
      if (tab && tab.url) {
        try {
          var u = new URL(tab.url);
          if (u.hostname.includes("youtube.com") && u.pathname === "/watch") {
            var vid = u.searchParams.get("v");
            if (vid) { analyzeWatch(vid, tab.title, currentJwt); return; }
          }
        } catch (e) {}
      }
      analyze(keyword.trim(), currentJwt);
    });
  }
});
