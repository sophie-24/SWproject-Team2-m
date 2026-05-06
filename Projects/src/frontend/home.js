const API = "";

document.getElementById("interest-grid").addEventListener("click", (e) => {
  const pill = e.target.closest(".interest-pill");
  if (pill) pill.classList.toggle("selected");
});

// 검색창으로 관심사 키워드 필터링
const searchInput = document.querySelector(".search-input");
if (searchInput) {
  searchInput.addEventListener("input", () => {
    const q = searchInput.value.trim().toLowerCase();
    document.querySelectorAll(".interest-pill").forEach(pill => {
      pill.style.display = (!q || pill.dataset.value.toLowerCase().includes(q)) ? "" : "none";
    });
  });
}

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
    if (res.status === 401) { alert("세션이 만료됐습니다. 다시 로그인해주세요."); window.location.href = "/"; return; }
    if (!res.ok) throw new Error("저장 실패");
    alert("관심사 설정이 저장되었습니다!");
    window.location.href = "/dashboard.html";
  } catch (e) {
    alert("저장 실패 — 다시 시도해주세요.");
  } finally {
    btn.disabled = false;
    btn.textContent = "설정 저장하기";
  }
}

function logout() {
  localStorage.removeItem("access_token");
  sessionStorage.removeItem("loggedIn");
  window.location.href = "/";
}
