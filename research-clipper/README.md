# Research Clipper

A Chrome extension for saving URLs that match patterns you care about. When you visit a page whose URL contains one of your defined patterns, a small floating widget appears on the page — click it to clip or unclip that URL. All saved URLs are viewable and exportable from the popup.

---

## Installation

1. Download and unzip `research-clipper.zip`
2. In Chrome, navigate to `chrome://extensions`
3. Enable **Developer mode** (toggle in the top-right corner)
4. Click **Load unpacked** and select the `research-clipper` folder
5. The 🔖 icon will appear in your Chrome toolbar

---

## Usage

### 1. Define URL patterns

Click the toolbar icon to open the popup, then use the **Patterns** tab to add substring patterns. Any URL containing the pattern as a substring will trigger the page widget.

**Examples:**

| Pattern | Matches |
|---|---|
| `youtube.com/watch?v=` | Any YouTube video page |
| `github.com` | Any GitHub page |
| `arxiv.org/abs/` | Any arXiv paper abstract |
| `news.ycombinator.com/item` | Any HN comment thread |

Patterns can be edited inline by clicking them, or deleted with the ✕ button. Changes take effect immediately on all open tabs.

### 2. Clip URLs on matched pages

When you visit a page whose URL contains one of your patterns, a small widget appears in the upper-right corner of the page.

- **Drag** it anywhere on the page by the handle bar
- Click **Save URL** to clip the current page — the button turns green to confirm
- Click **Saved ✓** again to unclip it
- Click **✕** to dismiss the widget for the current visit (it will reappear on next navigation)

The widget also works on single-page applications (YouTube, GitHub, etc.) and re-evaluates automatically when the URL changes without a full page reload.

### 3. Review and manage saved URLs

Open the popup and switch to the **Saved URLs** tab to:

- See whether the current page is matched and by which pattern
- Browse all clipped URLs, sorted newest-first
- View the pattern that was active when each URL was saved
- Click any URL to open it in a new tab
- Delete individual entries with ✕
- **Clear all** saved URLs at once
- **Export as JSON** to download your full clip list

---

## Exported data format

Each entry in the exported JSON contains:

```json
{
  "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
  "pattern": "youtube.com/watch?v=",
  "savedAt": 1716000000000
}
```

`savedAt` is a Unix timestamp in milliseconds.

---

## Files

```
research-clipper/
├── manifest.json    Extension config (Manifest V3)
├── background.js    Service worker — storage and messaging hub
├── content.js       Injected into all pages — renders the floating widget
├── popup.html       Toolbar popup UI
├── popup.js         Popup logic (pattern management, saved URL list)
└── icons/
    ├── icon16.png
    ├── icon48.png
    └── icon128.png
```

---

## Permissions used

| Permission | Reason |
|---|---|
| `storage` | Persist patterns and saved URLs via `chrome.storage.local` |
| `tabs` | Read the active tab's URL for match status in the popup |
| `activeTab` | Access the current tab when the popup is open |
| `scripting` | Reserved for future programmatic injection if needed |

---

## Notes

- All data is stored locally in your browser via `chrome.storage.local`. Nothing is sent to any server.
- The floating widget is scoped with a unique element ID (`#rc-widget`) and prefixed CSS to avoid conflicts with page styles.
- Pattern matching is a simple **substring check** — no wildcards or regex are evaluated.
