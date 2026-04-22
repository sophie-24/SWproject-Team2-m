// ── 웹사이트로부터 JWT 수신 → storage에 저장 ─────────────────────────────────
chrome.runtime.onMessageExternal.addListener(
  (message, sender, sendResponse) => {
    if (message.type === "SET_TOKEN") {
      chrome.storage.local.set({ jwt: message.token, loggedIn: true }, () => {
        console.log("[TechVisibility] JWT 저장 완료");
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
    chrome.sidePanel
      .open({ tabId })
      .then(() => sendResponse({ success: true }))
      .catch(e => sendResponse({ success: false, error: e.message }));
    return true; // 비동기 응답
  }
});
