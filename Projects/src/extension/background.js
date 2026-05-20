// ── 설치 시 사이드패널 동작 설정 ───────────────────────────────────────────────
chrome.runtime.onInstalled.addListener(() => {
  // 툴바 아이콘 클릭 시 사이드패널이 자동으로 열리도록 설정
  chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true }).catch(() => {});
  console.log("[Tubify] 익스텐션 설치/업데이트 완료");
});

// ── 웹사이트로부터 메시지 수신 (JWT 저장) ────────────────────────────────────────
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

// ── OAuth 콜백 URL 감시 → JWT 자동 저장 (SET_TOKEN 실패 fallback) ────────────
// app.js의 EXTENSION_ID가 실제 ID와 다를 경우 SET_TOKEN이 전달되지 않을 수 있다.
// chrome.tabs.onUpdated로 백엔드 URL의 token=... 파라미터를 직접 감지해 JWT를 저장한다.
const BACKEND_ORIGIN = "https://port-0-swproject-team2-m-mpdo8rl036709628.sel3.cloudtype.app";

function handleTabUrl(url) {
  if (!url) return;
  if (!url.startsWith(BACKEND_ORIGIN + "/")) return;
  try {
    const token = new URL(url).searchParams.get("token");
    if (!token) return;
    chrome.storage.local.get(["jwt", "loggedIn"], (stored) => {
      if (stored.jwt === token && stored.loggedIn) return;
      chrome.storage.local.set({ jwt: token, loggedIn: true }, () => {
        console.log("[Tubify] OAuth fallback: JWT 자동 저장 완료", url);
      });
    });
  } catch (e) {}
}

chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  // changeInfo.url은 navigation 시작 시 (loading 단계) 바로 제공됨
  // mypage.html?token=... 같이 즉시 다른 페이지로 리다이렉트되는 경우
  // "complete" 이벤트가 발생할 때는 이미 token이 없는 URL로 이동한 뒤라 여기서 먼저 잡아야 함
  if (changeInfo.url) {
    handleTabUrl(changeInfo.url);
    return;
  }
  if (changeInfo.status !== "complete") return;
  const url = tab.url || "";
  if (url) {
    handleTabUrl(url);
  } else {
    chrome.tabs.get(tabId, (t) => {
      if (chrome.runtime.lastError) return;
      handleTabUrl(t.url || "");
    });
  }
});

// ── 내부 메시지 처리 (content.js / side_panel.js 요청) ──────────────────────
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  // OPEN_SIDE_PANEL: content.js는 chrome.sidePanel에 직접 접근 불가 → background.js로 전달
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
