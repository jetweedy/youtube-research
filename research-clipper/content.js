// content.js — Research Clipper widget injected into pages

(function () {
  // Avoid double-injection
  if (window.__researchClipperLoaded) return;
  window.__researchClipperLoaded = true;

  let widget = null;
  let currentState = { matched: false, pattern: null, isSaved: false };
  let isDragging = false;
  let dragOffsetX = 0;
  let dragOffsetY = 0;

  // ─── Styles ────────────────────────────────────────────────────────────────
  const style = document.createElement("style");
  style.textContent = `
    #rc-widget {
      position: fixed;
      top: 18px;
      right: 18px;
      z-index: 2147483647;
      font-family: 'DM Mono', 'Fira Mono', 'Courier New', monospace;
      font-size: 12px;
      user-select: none;
      transition: opacity 0.2s ease;
    }
    #rc-widget.rc-hidden { opacity: 0; pointer-events: none; }
    #rc-inner {
      background: #0f0f0f;
      border: 1.5px solid #2a2a2a;
      border-radius: 10px;
      box-shadow: 0 4px 24px rgba(0,0,0,0.55), 0 0 0 0.5px #111;
      overflow: hidden;
      min-width: 180px;
      max-width: 260px;
    }
    #rc-handle {
      display: flex;
      align-items: center;
      gap: 6px;
      padding: 7px 10px 6px;
      background: #161616;
      border-bottom: 1px solid #222;
      cursor: grab;
    }
    #rc-handle:active { cursor: grabbing; }
    #rc-handle-dots {
      display: flex;
      flex-direction: column;
      gap: 2.5px;
      opacity: 0.35;
    }
    #rc-handle-dots span {
      display: block;
      width: 12px;
      height: 1.5px;
      background: #fff;
      border-radius: 2px;
    }
    #rc-label {
      color: #555;
      font-size: 10px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      flex: 1;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    #rc-close {
      background: none;
      border: none;
      color: #444;
      cursor: pointer;
      font-size: 14px;
      line-height: 1;
      padding: 0 2px;
      transition: color 0.15s;
    }
    #rc-close:hover { color: #888; }
    #rc-body {
      padding: 10px 12px 11px;
    }
    #rc-pattern-tag {
      font-size: 10px;
      color: #3a3a3a;
      background: #1a1a1a;
      border: 1px solid #252525;
      border-radius: 4px;
      padding: 2px 6px;
      margin-bottom: 8px;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      display: block;
    }
    #rc-btn {
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 7px;
      width: 100%;
      padding: 8px 0;
      border-radius: 6px;
      border: none;
      font-family: inherit;
      font-size: 12px;
      font-weight: 600;
      letter-spacing: 0.03em;
      cursor: pointer;
      transition: background 0.15s, color 0.15s, transform 0.1s;
    }
    #rc-btn:active { transform: scale(0.97); }
    #rc-btn.rc-save {
      background: #1a1a1a;
      color: #e0e0e0;
      border: 1.5px solid #2e2e2e;
    }
    #rc-btn.rc-save:hover {
      background: #222;
      border-color: #3a8aff;
      color: #fff;
    }
    #rc-btn.rc-saved {
      background: #0e2a14;
      color: #4ade80;
      border: 1.5px solid #1a4a24;
    }
    #rc-btn.rc-saved:hover {
      background: #0a1e10;
      border-color: #22c55e;
    }
    #rc-btn svg {
      flex-shrink: 0;
    }
  `;
  document.head.appendChild(style);

  // ─── Build Widget DOM ───────────────────────────────────────────────────────
  function buildWidget() {
    if (widget) widget.remove();

    widget = document.createElement("div");
    widget.id = "rc-widget";

    widget.innerHTML = `
      <div id="rc-inner">
        <div id="rc-handle">
          <div id="rc-handle-dots"><span></span><span></span><span></span></div>
          <span id="rc-label">Research Clipper</span>
          <button id="rc-close" title="Dismiss">✕</button>
        </div>
        <div id="rc-body">
          <span id="rc-pattern-tag"></span>
          <button id="rc-btn" class="rc-save">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
              <path d="M19 21l-7-5-7 5V5a2 2 0 012-2h10a2 2 0 012 2z"/>
            </svg>
            Save URL
          </button>
        </div>
      </div>
    `;

    document.body.appendChild(widget);

    // Close button
    widget.querySelector("#rc-close").addEventListener("click", () => {
      widget.classList.add("rc-hidden");
    });

    // Save/Unsave button
    widget.querySelector("#rc-btn").addEventListener("click", () => {
      chrome.runtime.sendMessage(
        { type: "TOGGLE_SAVE", url: location.href, pattern: currentState.pattern },
        (res) => {
          if (res) updateWidgetState(res.isSaved);
        }
      );
    });

    // Drag support
    const handle = widget.querySelector("#rc-handle");
    handle.addEventListener("mousedown", onDragStart);

    updateWidgetState(currentState.isSaved);
    updatePatternTag(currentState.pattern);
  }

  function updateWidgetState(isSaved) {
    currentState.isSaved = isSaved;
    if (!widget) return;
    const btn = widget.querySelector("#rc-btn");
    if (isSaved) {
      btn.className = "rc-save rc-saved";
      btn.innerHTML = `
        <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor" stroke="none">
          <path d="M19 21l-7-5-7 5V5a2 2 0 012-2h10a2 2 0 012 2z"/>
        </svg>
        Saved ✓`;
    } else {
      btn.className = "rc-save";
      btn.innerHTML = `
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
          <path d="M19 21l-7-5-7 5V5a2 2 0 012-2h10a2 2 0 012 2z"/>
        </svg>
        Save URL`;
    }
  }

  function updatePatternTag(pattern) {
    if (!widget) return;
    const tag = widget.querySelector("#rc-pattern-tag");
    tag.textContent = pattern ? `pattern: ${pattern}` : "";
  }

  // ─── Drag Logic ────────────────────────────────────────────────────────────
  function onDragStart(e) {
    if (e.button !== 0) return;
    isDragging = true;
    const rect = widget.getBoundingClientRect();
    dragOffsetX = e.clientX - rect.left;
    dragOffsetY = e.clientY - rect.top;
    document.addEventListener("mousemove", onDragMove);
    document.addEventListener("mouseup", onDragEnd);
    e.preventDefault();
  }

  function onDragMove(e) {
    if (!isDragging) return;
    const x = e.clientX - dragOffsetX;
    const y = e.clientY - dragOffsetY;
    widget.style.left = Math.max(0, Math.min(window.innerWidth - widget.offsetWidth, x)) + "px";
    widget.style.top = Math.max(0, Math.min(window.innerHeight - widget.offsetHeight, y)) + "px";
    widget.style.right = "auto";
  }

  function onDragEnd() {
    isDragging = false;
    document.removeEventListener("mousemove", onDragMove);
    document.removeEventListener("mouseup", onDragEnd);
  }

  // ─── Check & Show/Hide ─────────────────────────────────────────────────────
  function checkAndRender() {
    chrome.runtime.sendMessage({ type: "GET_STATE", url: location.href }, (res) => {
      if (chrome.runtime.lastError) return;
      currentState = res;
      if (res.matched) {
        if (!widget) {
          buildWidget();
        } else {
          widget.classList.remove("rc-hidden");
          updateWidgetState(res.isSaved);
          updatePatternTag(res.pattern);
        }
      } else {
        if (widget) widget.classList.add("rc-hidden");
      }
    });
  }

  // ─── Listen for pattern updates from background ────────────────────────────
  chrome.runtime.onMessage.addListener((msg) => {
    if (msg.type === "PATTERNS_UPDATED") {
      checkAndRender();
    }
  });

  // Initial check
  checkAndRender();

  // Re-check on SPA navigation (YouTube, etc.)
  let lastUrl = location.href;
  const urlObserver = new MutationObserver(() => {
    if (location.href !== lastUrl) {
      lastUrl = location.href;
      // Reset widget position on navigation
      if (widget) {
        widget.style.left = "";
        widget.style.top = "";
        widget.style.right = "18px";
      }
      checkAndRender();
    }
  });
  urlObserver.observe(document.body, { childList: true, subtree: true });
})();
