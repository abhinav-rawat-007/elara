// Message protocol shared with the Python backend (backend/main.py).

export type ElaraState = "idle" | "listening" | "thinking" | "speaking";

// Emotion tags Elara weaves into her replies (backend/characters/elara.yaml).
// The backend strips them from text/speech and emits them as events; the orb
// wears them. Keep in sync with EMOTIONS in lib/emotions.ts.
export type Emotion =
  | "neutral"
  | "joy"
  | "tease"
  | "curious"
  | "soft"
  | "alert"
  | "sigh";

export type ToolStatus = "start" | "done" | "error";

export interface ElaraConfig {
  model: string;
  speak_replies: boolean;
  stt_model: string;
  user_name: string;
  ollama_host: string;
  proactive: boolean;
  proactive_minutes: number;
  anthropic_api_key: string;
  cloud_model: string;
  cloud_mode: "auto" | "always" | "never";
  cloud_backend: "auto" | "subscription" | "api";
}

// server -> client
export type ServerEvent =
  | { type: "assistant_start"; id: string }
  | { type: "assistant_delta"; id: string; text: string }
  | { type: "assistant_done"; id: string; text: string }
  | { type: "tool_event"; name: string; status: ToolStatus; detail: unknown }
  | { type: "emotion"; name: string }
  | { type: "status"; state: ElaraState }
  | { type: "transcript"; text: string }
  | { type: "mic_level"; level: number }
  | { type: "config"; config: ElaraConfig }
  | { type: "history"; messages: { role: "user" | "assistant"; content: string }[] }
  | { type: "error"; message: string };

// client -> server
export type ClientMessage =
  | { type: "user_text"; text: string }
  | { type: "ptt"; action: "start" | "stop" }
  | { type: "interrupt" }
  | { type: "reset" }
  | { type: "get_config" }
  | { type: "set_config"; config: Partial<ElaraConfig> };

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  text: string;
  streaming?: boolean;
}

export interface ToolActivity {
  name: string;
  status: ToolStatus;
  detail: string;
}

// Dev-only QA override (like /?state=): /?ws=ws://127.0.0.1:9999/ws points
// the UI at a stand-in backend without touching a running real one.
export const WS_URL =
  (import.meta.env.DEV &&
    typeof window !== "undefined" &&
    new URLSearchParams(window.location.search).get("ws")) ||
  "ws://127.0.0.1:8765/ws";

/** Append the backend auth token to a WebSocket URL as a query param, if any. */
export function wsUrlWithToken(base: string, token: string): string {
  if (!token) return base;
  return `${base}${base.includes("?") ? "&" : "?"}token=${encodeURIComponent(token)}`;
}

// Friendly labels for tool activity shown in the HUD.
export const TOOL_LABELS: Record<string, string> = {
  web_search: "Searching the web",
  read_page: "Reading a page",
  open_website: "Opening a site",
  play_on_youtube: "Opening YouTube",
  open_app: "Opening an app",
  close_app: "Closing an app",
  set_volume: "Adjusting volume",
  media_control: "Controlling media",
  set_brightness: "Adjusting brightness",
  take_screenshot: "Taking a screenshot",
  lock_pc: "Locking the PC",
  get_system_status: "Checking system status",
  set_timer: "Setting a timer",
  run_powershell: "Running a command",
  find_files: "Searching files",
  open_path: "Opening a file",
  enter_focus_mode: "Thinking harder",
  launch_steam_game: "Launching a game",
  list_steam_games: "Checking the game library",
  browser_open: "Opening her browser",
  browser_snapshot: "Reading the page",
  browser_click: "Clicking",
  browser_type: "Typing",
  browser_scroll: "Scrolling",
  browser_back: "Going back",
  browser_read: "Reading the page",
  browser_close: "Closing her browser",
  list_windows: "Checking open windows",
  focus_window: "Switching windows",
  inspect_window: "Looking inside an app",
  click_control: "Clicking in an app",
  click_control_by_name: "Clicking in an app",
  type_text: "Typing in an app",
  read_window: "Reading an app",
};
