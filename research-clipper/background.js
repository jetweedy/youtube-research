// background.js — Research Clipper service worker

// Listen for messages from content scripts and popup
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.type === "GET_STATE") {
    // Content script asking: does current URL match a pattern, and is it saved?
    getState(msg.url).then(sendResponse);
    return true; // async
  }

  if (msg.type === "TOGGLE_SAVE") {
    toggleSave(msg.url, msg.pattern).then(sendResponse);
    return true;
  }

  if (msg.type === "GET_PATTERNS") {
    chrome.storage.local.get("patterns", (res) => {
      sendResponse({ patterns: res.patterns || [] });
    });
    return true;
  }

  if (msg.type === "SET_PATTERNS") {
    chrome.storage.local.set({ patterns: msg.patterns }, () => {
      // Notify all tabs to re-evaluate
      chrome.tabs.query({}, (tabs) => {
        tabs.forEach((tab) => {
          chrome.tabs.sendMessage(tab.id, { type: "PATTERNS_UPDATED" }).catch(() => {});
        });
      });
      sendResponse({ ok: true });
    });
    return true;
  }

  if (msg.type === "GET_SAVED") {
    chrome.storage.local.get("saved", (res) => {
      sendResponse({ saved: res.saved || [] });
    });
    return true;
  }

  if (msg.type === "DELETE_SAVED") {
    chrome.storage.local.get("saved", (res) => {
      const saved = (res.saved || []).filter((s) => s.url !== msg.url);
      chrome.storage.local.set({ saved }, () => sendResponse({ ok: true }));
    });
    return true;
  }
});

async function getState(url) {
  return new Promise((resolve) => {
    chrome.storage.local.get(["patterns", "saved"], (res) => {
      const patterns = res.patterns || [];
      const saved = res.saved || [];

      const matchedPattern = patterns.find((p) => p.trim() && url.includes(p.trim()));
      const isSaved = saved.some((s) => s.url === url);

      resolve({
        matched: !!matchedPattern,
        pattern: matchedPattern || null,
        isSaved,
      });
    });
  });
}

async function toggleSave(url, pattern) {
  return new Promise((resolve) => {
    chrome.storage.local.get("saved", (res) => {
      let saved = res.saved || [];
      const idx = saved.findIndex((s) => s.url === url);

      if (idx >= 0) {
        // Unsave
        saved.splice(idx, 1);
      } else {
        // Save
        saved.push({
          url,
          pattern,
          title: "", // populated by content script if available
          savedAt: Date.now(),
        });
      }

      chrome.storage.local.set({ saved }, () => resolve({ isSaved: idx < 0, saved }));
    });
  });
}
