const KEY = "radar.lastVisit";
const DAY = 24 * 3600e3;

function read(): number {
  try {
    const t = Date.parse(localStorage.getItem(KEY) ?? "");
    if (!Number.isNaN(t)) return t;
  } catch {
    /* storage blocked: treat as a first visit */
  }
  return Date.now() - DAY;
}

/** When this device last left the page, read once on load: a drop found after it is "new" until the next visit. */
export const LAST_VISIT = read();

function stamp() {
  try {
    localStorage.setItem(KEY, new Date().toISOString());
  } catch {
    /* session-only */
  }
}
addEventListener("pagehide", stamp);
addEventListener("visibilitychange", () => document.visibilityState === "hidden" && stamp());
