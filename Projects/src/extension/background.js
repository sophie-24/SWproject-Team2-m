// ── 과거 YouTube 검색 기록 수집 ─────────────────────────────────────────────────
// 호출: onboarding.html에서 chrome.runtime.sendMessage({ type: "GET_HISTORY" })
// 반환: { success: true, keywords: ["검색어1", "검색어2", ...] }
// 권한: manifest.json에 "history" 이미 포함됨

// ── 설치 시 사이드패널 동작 설정 ───────────────────────────────────────────────
chrome.runtime.onInstalled.addListener(() => {
  // 툴바 아이콘 클릭 시 사이드패널이 자동으로 열리도록 설정
  chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true }).catch(() => {});
  console.log("[Tubify] 익스텐션 설치/업데이트 완료");
});

// ── 웹사이트로부터 메시지 수신 (JWT 저장 / 검색 기록 요청) ──────────────────────
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

    // loading.html(웹페이지)에서 검색 기록 요청 — onMessage는 내부 전용이라 여기서도 처리
    if (message.type === "GET_HISTORY") {
      const oneMonthAgo = Date.now() - 30 * 24 * 60 * 60 * 1000;
      chrome.history.search(
        { text: "youtube.com/results", maxResults: 500, startTime: oneMonthAgo },
        (historyItems) => {
          const keywords = [];
          const seen = new Set();
          for (const item of historyItems || []) {
            try {
              const url = new URL(item.url);
              if (url.hostname.includes("youtube.com") && url.pathname === "/results") {
                const kw = url.searchParams.get("search_query") || "";
                if (kw && !seen.has(kw.toLowerCase())) {
                  seen.add(kw.toLowerCase());
                  keywords.push(kw);
                }
              }
            } catch (e) {}
          }
          sendResponse({ success: true, keywords });
        }
      );
      return true;
    }
  }
);

// ── OAuth 콜백 URL 감시 → JWT 자동 저장 (SET_TOKEN 실패 fallback) ────────────
// app.js의 EXTENSION_ID가 실제 ID와 다를 경우 SET_TOKEN이 전달되지 않을 수 있다.
// chrome.tabs.onUpdated로 localhost:8000/?token=... URL을 직접 감지해 JWT를 저장한다.
chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (changeInfo.status !== "complete") return;
  const url = tab.url || "";
  console.log("[Tubify] tab updated:", url);
  if (!url.startsWith("http://localhost:8000/") && !url.startsWith("http://127.0.0.1:8000/")) return;

  try {
    const token = new URL(url).searchParams.get("token");
    console.log("[Tubify] token found:", !!token);
    if (!token) return;

    chrome.storage.local.get(["jwt", "loggedIn"], (stored) => {
      if (stored.jwt === token && stored.loggedIn) {
        console.log("[Tubify] 동일 토큰 이미 저장됨, 생략");
        return;
      }
      chrome.storage.local.set({ jwt: token, loggedIn: true }, () => {
        console.log("[Tubify] OAuth fallback: JWT 자동 저장 완료");
      });
    });
  } catch (e) { console.log("[Tubify] URL 파싱 오류:", e); }
});

// ── 내부 메시지 처리 (content.js / popup.js / onboarding.html 요청) ─────────
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {

  // GET_HISTORY: 최근 1개월 YouTube 검색 기록 수집 → 키워드 리스트 반환
  if (message.type === "GET_HISTORY") {
    const oneMonthAgo = Date.now() - 30 * 24 * 60 * 60 * 1000;
    chrome.history.search(
      { text: "youtube.com/results", maxResults: 500, startTime: oneMonthAgo },
      (historyItems) => {
        const keywords = [];
        const seen = new Set();
        for (const item of historyItems || []) {
          try {
            const url = new URL(item.url);
            if (url.hostname.includes("youtube.com") && url.pathname === "/results") {
              const kw = url.searchParams.get("search_query") || "";
              if (kw && !seen.has(kw.toLowerCase())) {
                seen.add(kw.toLowerCase());
                keywords.push(kw);
              }
            }
          } catch (e) { /* URL 파싱 실패 무시 */ }
        }
        sendResponse({ success: true, keywords });
      }
    );
    return true; // 비동기 sendResponse 유지
  }

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
