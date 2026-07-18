// Thin wrappers around Tauri APIs that safely no-op when running in a plain
// browser (e.g. the Vite dev preview), so the UI works in both places.

export const isTauri = (): boolean =>
  typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;

/** The per-launch token the backend requires, fetched from the Rust shell.
 * Empty when running outside Tauri (plain browser dev), where the backend
 * falls back to an Origin check instead. */
export async function getBackendToken(): Promise<string> {
  if (!isTauri()) return "";
  try {
    const { invoke } = await import("@tauri-apps/api/core");
    return await invoke<string>("backend_token");
  } catch {
    return "";
  }
}

const MINI = { width: 240, height: 300 };
const FULL = { width: 1100, height: 720 };

export async function setMiniMode(mini: boolean): Promise<void> {
  if (!isTauri()) return;
  const { getCurrentWindow, LogicalSize } = await import("@tauri-apps/api/window");
  const win = getCurrentWindow();
  const size = mini ? MINI : FULL;
  await win.setAlwaysOnTop(mini);
  await win.setSize(new LogicalSize(size.width, size.height));
  if (mini) {
    await win.setResizable(false);
  } else {
    await win.setResizable(true);
    await win.center();
  }
}

export async function startDragging(): Promise<void> {
  if (!isTauri()) return;
  const { getCurrentWindow } = await import("@tauri-apps/api/window");
  await getCurrentWindow().startDragging();
}

export async function getAutostart(): Promise<boolean> {
  if (!isTauri()) return false;
  const { isEnabled } = await import("@tauri-apps/plugin-autostart");
  try {
    return await isEnabled();
  } catch {
    return false;
  }
}

export async function setAutostart(on: boolean): Promise<void> {
  if (!isTauri()) return;
  const { enable, disable } = await import("@tauri-apps/plugin-autostart");
  try {
    if (on) await enable();
    else await disable();
  } catch {
    /* ignore — autostart only works in the packaged/dev Tauri app */
  }
}
