// extension/background.js

// 웹사이트로부터 JWT 수신 → storage에 저장
chrome.runtime.onMessageExternal.addListener(
  (message, sender, sendResponse) => {
    if (message.type === "SET_TOKEN") {
      chrome.storage.local.set({ jwt: message.token }, () => {
        console.log("[TechVisibility] JWT 저장 완료");
        sendResponse({ success: true });
      });
      return true; // 비동기 응답을 위해 필수
    }

    if (message.type === "CLEAR_TOKEN") {
      chrome.storage.local.remove("jwt", () => {
        sendResponse({ success: true });
      });
      return true;
    }
  }
);