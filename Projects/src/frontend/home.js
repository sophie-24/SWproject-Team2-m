document.getElementById("interest-grid").addEventListener("click", (e) => {
  const pill = e.target.closest(".interest-pill");
  if (pill) pill.classList.toggle("selected");
});

function saveSettings() {
  const selected = [...document.querySelectorAll(".interest-pill.selected")]
    .map(el => el.dataset.value);
  console.log("선택된 관심사:", selected);
  // TODO: API 연동
  alert("설정이 저장되었습니다!");
}

function logout() {
  sessionStorage.removeItem("loggedIn");
  window.location.href = "login.html";
}
