// popup.js

// ─── Tab switching ─────────────────────────────────────────────────────────
document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
    document.querySelectorAll(".panel").forEach((p) => p.classList.remove("active"));
    tab.classList.add("active");
    document.getElementById(`tab-${tab.dataset.tab}`).classList.add("active");

    if (tab.dataset.tab === "saved") {
      loadSavedTab();
    }
  });
});

// ─── Patterns Tab ──────────────────────────────────────────────────────────
let patterns = [];

function renderPatterns() {
  const list = document.getElementById("pattern-list");
  list.innerHTML = "";

  if (patterns.length === 0) {
    list.innerHTML = `<div style="color:#333;font-size:11px;font-family:'DM Mono',monospace;padding:4px 0">No patterns yet.</div>`;
    return;
  }

  patterns.forEach((p, i) => {
    const row = document.createElement("div");
    row.className = "pattern-row";
    row.innerHTML = `
      <input type="text" value="${escapeAttr(p)}" data-idx="${i}" spellcheck="false" />
      <button class="pattern-del" data-idx="${i}" title="Remove">✕</button>
    `;
    list.appendChild(row);

    // Inline edit
    row.querySelector("input").addEventListener("blur", (e) => {
      const val = e.target.value.trim();
      if (val) {
        patterns[i] = val;
      } else {
        patterns.splice(i, 1);
      }
      savePatterns();
      renderPatterns();
    });

    row.querySelector("input").addEventListener("keydown", (e) => {
      if (e.key === "Enter") e.target.blur();
    });

    // Delete
    row.querySelector(".pattern-del").addEventListener("click", (e) => {
      const idx = parseInt(e.target.dataset.idx);
      patterns.splice(idx, 1);
      savePatterns();
      renderPatterns();
    });
  });
}

function savePatterns() {
  chrome.runtime.sendMessage({ type: "SET_PATTERNS", patterns });
}

// Add pattern
document.getElementById("btn-add").addEventListener("click", addPattern);
document.getElementById("new-pattern").addEventListener("keydown", (e) => {
  if (e.key === "Enter") addPattern();
});

function addPattern() {
  const input = document.getElementById("new-pattern");
  const val = input.value.trim();
  if (!val) return;
  if (!patterns.includes(val)) {
    patterns.push(val);
    savePatterns();
    renderPatterns();
  }
  input.value = "";
}

// Load patterns on open
chrome.runtime.sendMessage({ type: "GET_PATTERNS" }, (res) => {
  patterns = res?.patterns || [];
  renderPatterns();
});

// ─── Saved Tab ─────────────────────────────────────────────────────────────
function loadSavedTab() {
  // Current page status
  chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
    const url = tabs[0]?.url || "";
    chrome.runtime.sendMessage({ type: "GET_STATE", url }, (res) => {
      const dot = document.getElementById("status-dot");
      const text = document.getElementById("status-text");
      if (res?.matched) {
        dot.className = "status-dot matched";
        text.textContent = `matched: ${res.pattern}`;
      } else {
        dot.className = "status-dot unmatched";
        text.textContent = "current page not matched";
      }
    });
  });

  // Saved list
  chrome.runtime.sendMessage({ type: "GET_SAVED" }, (res) => {
    const saved = res?.saved || [];
    renderSaved(saved);
  });
}

function renderSaved(saved) {
  const list = document.getElementById("saved-list");
  const countEl = document.getElementById("saved-count");
  countEl.textContent = saved.length;
  list.innerHTML = "";

  if (saved.length === 0) {
    list.innerHTML = `
      <div class="empty-state">
        <div class="empty-icon">🔖</div>
        No URLs saved yet.<br/>Visit a matched page and clip it.
      </div>`;
    return;
  }

  // Newest first
  const sorted = [...saved].sort((a, b) => b.savedAt - a.savedAt);

  sorted.forEach((item) => {
    const el = document.createElement("div");
    el.className = "saved-item";

    const date = new Date(item.savedAt);
    const dateStr = date.toLocaleDateString(undefined, { month: "short", day: "numeric" }) +
                    " " + date.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });

    el.innerHTML = `
      <div class="saved-item-body">
        <a class="saved-url" href="${escapeAttr(item.url)}" target="_blank" title="${escapeAttr(item.url)}">${truncateUrl(item.url)}</a>
        <div class="saved-meta">${dateStr}<span class="pattern-chip">${escapeHtml(item.pattern || "")}</span></div>
      </div>
      <button class="saved-del" title="Remove">✕</button>
    `;

    el.querySelector(".saved-del").addEventListener("click", () => {
      chrome.runtime.sendMessage({ type: "DELETE_SAVED", url: item.url }, () => {
        loadSavedTab();
      });
    });

    list.appendChild(el);
  });
}

// Clear all
document.getElementById("btn-clear-all").addEventListener("click", () => {
  if (!confirm("Remove all saved URLs?")) return;
  chrome.storage.local.set({ saved: [] }, () => loadSavedTab());
});

// Export JSON
document.getElementById("btn-export").addEventListener("click", () => {
  chrome.runtime.sendMessage({ type: "GET_SAVED" }, (res) => {
    const data = JSON.stringify(res?.saved || [], null, 2);
    const blob = new Blob([data], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `research-clipper-${Date.now()}.json`;
    a.click();
    URL.revokeObjectURL(url);
  });
});

// ─── Helpers ───────────────────────────────────────────────────────────────
function escapeHtml(str) {
  return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
function escapeAttr(str) {
  return str.replace(/"/g, "&quot;");
}
function truncateUrl(url, max = 52) {
  return url.length > max ? url.slice(0, max) + "…" : url;
}
