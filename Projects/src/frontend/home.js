const API = "";

// ── 온보딩 / 마이페이지 컨텍스트 파악 ─────────────────────────────────────────
const _urlParams     = new URLSearchParams(window.location.search);
const _fromOnboarding = _urlParams.get("from") === "onboarding";

// ── pill 토글 (이벤트 위임) ───────────────────────────────────────────────────
document.getElementById("interest-grid").addEventListener("click", (e) => {
  const pill = e.target.closest(".interest-pill");
  if (pill) pill.classList.toggle("selected");
});

// ── 검색: 필터링 + Enter/추가버튼으로 새 관심사 생성 ─────────────────────────
const searchInput = document.querySelector(".search-input");
const addBtn      = document.querySelector(".search-add-btn");

if (searchInput) {
  /* 입력할 때마다 필터링 + "추가" 버튼 표시 */
  searchInput.addEventListener("input", () => {
    const q = searchInput.value.trim().toLowerCase();
    document.querySelectorAll(".interest-pill").forEach(pill => {
      pill.style.display = (!q || pill.dataset.value.toLowerCase().includes(q)) ? "" : "none";
    });
    if (addBtn) addBtn.style.display = q ? "inline-flex" : "none";
  });

  /* Enter 키로 새 관심사 추가 */
  searchInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      const val = searchInput.value.trim();
      if (val) { _addCustomPill(val, true); _resetSearch(); }
    }
  });
}

/* "추가" 버튼 클릭 */
function addFromSearch() {
  const val = searchInput ? searchInput.value.trim() : "";
  if (val) { _addCustomPill(val, true); _resetSearch(); }
}

/* 검색창 초기화 */
function _resetSearch() {
  if (searchInput) searchInput.value = "";
  document.querySelectorAll(".interest-pill").forEach(pill => { pill.style.display = ""; });
  if (addBtn) addBtn.style.display = "none";
}

/* 커스텀 pill 추가 (중복 방지) */
function _addCustomPill(value, selected) {
  const grid = document.getElementById("interest-grid");
  /* 이미 존재하면 선택 상태만 변경 */
  const existing = grid.querySelector(`[data-value="${CSS.escape(value)}"]`);
  if (existing) {
    if (selected) existing.classList.add("selected");
    return;
  }
  const pill = document.createElement("button");
  pill.className = "interest-pill" + (selected ? " selected" : "");
  pill.dataset.value = value;
  pill.innerHTML = `<span class="pill-icon">🏷️</span>${_escapeHtml(value)}`;
  pill.addEventListener("click", () => pill.classList.toggle("selected"));
  grid.appendChild(pill);
}

// ── 페이지 로드 시 기존 관심사 불러와 선택 표시 ──────────────────────────────
async function loadExistingInterests() {
  const jwt = localStorage.getItem("access_token") || "";
  if (!jwt) return;

  try {
    const res = await fetch(`${API}/my/profile`, {
      headers: { "Authorization": `Bearer ${jwt}` },
    });
    if (!res.ok) return;
    const data = await res.json();
    const existing = Array.isArray(data.interest_categories) ? data.interest_categories : [];

    /* 기존 하드코딩 selected 초기화 */
    document.querySelectorAll(".interest-pill").forEach(pill => pill.classList.remove("selected"));

    const presetValues = new Set(
      [...document.querySelectorAll(".interest-pill")].map(p => p.dataset.value)
    );

    existing.forEach(cat => {
      if (presetValues.has(cat)) {
        /* preset pill → 선택 상태로 변경 */
        const pill = document.querySelector(`[data-value="${CSS.escape(cat)}"]`);
        if (pill) pill.classList.add("selected");
      } else {
        /* preset에 없는 기존 관심사 → 커스텀 pill로 추가 */
        _addCustomPill(cat, true);
      }
    });
  } catch (e) {
    console.warn("[home] 기존 관심사 로드 실패:", e);
  }
}

// ── 저장 ─────────────────────────────────────────────────────────────────────
async function saveSettings() {
  const selected = [...document.querySelectorAll(".interest-pill.selected")]
    .map(el => el.dataset.value);

  const jwt = localStorage.getItem("access_token") || "";
  if (!jwt) { alert("로그인이 필요합니다."); window.location.href = "/"; return; }

  const btn = document.querySelector(".save-btn");
  btn.disabled = true;
  btn.textContent = "저장 중...";

  try {
    const res = await fetch(`${API}/my/profile`, {
      method: "PUT",
      headers: { "Authorization": `Bearer ${jwt}`, "Content-Type": "application/json" },
      body: JSON.stringify({ interest_categories: selected }),
    });
    if (res.status === 401) {
      alert("세션이 만료됐습니다. 다시 로그인해주세요.");
      window.location.href = "/";
      return;
    }
    if (!res.ok) throw new Error("저장 실패");

    /* 온보딩 완료 or 마이페이지 편집 → 항상 대시보드로 */
    window.location.href = "/dashboard.html";
  } catch (e) {
    alert("저장 실패 — 다시 시도해주세요.");
  } finally {
    btn.disabled = false;
    btn.textContent = "설정 저장하기";
  }
}

// ── 유틸 ─────────────────────────────────────────────────────────────────────
function _escapeHtml(str) {
  return String(str ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function logout() {
  localStorage.removeItem("access_token");
  sessionStorage.removeItem("loggedIn");
  window.location.href = "/";
}

// ── 초기화 ───────────────────────────────────────────────────────────────────
loadExistingInterests();
