// ── 과거 YouTube 검색 기록 수집 및 분석 ─────────────────────────────────────────
// TODO: chrome.history API로 과거 YouTube 검색 기록 수집 후 /profile/analyze-history로 전송
//   흐름: chrome.history.search({ text: "youtube.com/results", maxResults: 500 })
//         → URL 파싱으로 'search_query' 파라미터 추출 (키워드 목록 생성)
//         → POST /profile/analyze-history { keywords: [...] }
//         → 응답으로 받은 categories / intent_type을 온보딩 페이지에 전달
//   호출 시점: onboarding.html Step2에서 chrome.runtime.sendMessage({ type: "GET_HISTORY" }) 로 요청
//   권한: manifest.json에 "history" 이미 포함됨

// ── 설치 시 사이드패널 동작 설정 ───────────────────────────────────────────────
chrome.runtime.onInstalled.addListener(() => {
  // 툴바 아이콘 클릭 시 사이드패널이 자동으로 열리지 않도록 설정
  // (플로팅 버튼으로만 열림)
  chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: false }).catch(() => {});
  console.log("[Tubify] 익스텐션 설치/업데이트 완료");
});

// ── 웹사이트로부터 JWT 수신 → storage에 저장 ─────────────────────────────────
chrome.runtime.onMessageExternal.addListener(
  (message, sender, sendResponse) => {
    if (message.type === "SET_TOKEN") {
      chrome.storage.local.set({ jwt: message.token, loggedIn: true }, () => {
        console.log("[Tubify] JWT 저장 완료");
        sendResponse({ success: true });
      });
      return true;
    }

    if (message.type === "CLEAR_TOKEN") {
      chrome.storage.local.remove(["jwt", "loggedIn"], () => {
        sendResponse({ success: true });
      });
      return true;
    }
  }
);

// ── 사이드 패널 오픈 (content.js / popup.js 요청) ────────────────────────────
// content.js는 chrome.sidePanel에 직접 접근 불가 → background.js로 메시지 전달
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type === "OPEN_SIDE_PANEL") {
    const tabId = message.tabId || sender.tab?.id;
    if (!tabId) {
      sendResponse({ success: false, error: "tabId 없음" });
      return;
    }

    // keyword를 storage에 미리 저장 → side_panel이 init() 시 읽어감
    const storeAndOpen = () =>
      chrome.sidePanel
        .open({ tabId })
        .then(() => sendResponse({ success: true }))
        .catch(e => {
          console.error("[Tubify] sidePanel.open 실패:", e.message);
          sendResponse({ success: false, error: e.message });
        });

    if (message.keyword) {
      chrome.storage.local.set({ pendingKeyword: message.keyword }, storeAndOpen);
    } else {
      storeAndOpen();
    }

    return true; // 비동기 sendResponse 유지
  }
});
