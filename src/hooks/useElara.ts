import { useCallback, useEffect, useRef, useState } from "react";
import {
  ChatMessage,
  ClientMessage,
  ElaraConfig,
  ElaraState,
  Emotion,
  ServerEvent,
  ToolActivity,
  TOOL_LABELS,
  WS_URL,
  wsUrlWithToken,
} from "@/lib/protocol";
import { isEmotion } from "@/lib/emotions";
import { getBackendToken } from "@/lib/tauri";

type Connection = "connecting" | "online" | "offline";

/** How long a feeling lingers on the orb once she has gone idle. */
const EMOTION_LINGER_MS = 8000;

export interface ElaraApi {
  connection: Connection;
  state: ElaraState;
  emotion: Emotion;
  messages: ChatMessage[];
  tool: ToolActivity | null;
  micLevel: number;
  config: ElaraConfig | null;
  error: string | null;
  send: (text: string) => void;
  startPtt: () => void;
  stopPtt: () => void;
  interrupt: () => void;
  reset: () => void;
  updateConfig: (patch: Partial<ElaraConfig>) => void;
}

export function useElara(): ElaraApi {
  const wsRef = useRef<WebSocket | null>(null);
  const emotionTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [connection, setConnection] = useState<Connection>("connecting");
  const [state, setState] = useState<ElaraState>("idle");
  const [emotion, setEmotion] = useState<Emotion>("neutral");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [tool, setTool] = useState<ToolActivity | null>(null);
  const [micLevel, setMicLevel] = useState(0);
  const [config, setConfig] = useState<ElaraConfig | null>(null);
  const [error, setError] = useState<string | null>(null);

  const post = useCallback((msg: ClientMessage) => {
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(msg));
  }, []);

  useEffect(() => {
    let reconnectTimer: ReturnType<typeof setTimeout>;
    let closed = false;

    const connect = async () => {
      setConnection("connecting");
      // The backend authorizes us with a per-launch token from the Rust shell.
      const token = await getBackendToken();
      if (closed) return;
      const ws = new WebSocket(wsUrlWithToken(WS_URL, token));
      wsRef.current = ws;

      ws.onopen = () => setConnection("online");
      ws.onclose = () => {
        if (closed) return;
        setConnection("offline");
        reconnectTimer = setTimeout(connect, 1500);
      };
      ws.onerror = () => ws.close();
      ws.onmessage = (ev) => handleEvent(JSON.parse(ev.data) as ServerEvent);
    };

    const handleEvent = (event: ServerEvent) => {
      switch (event.type) {
        case "assistant_start":
          setMessages((m) => [
            ...m,
            { id: event.id, role: "assistant", text: "", streaming: true },
          ]);
          break;
        case "assistant_delta":
          setMessages((m) =>
            m.map((msg) =>
              msg.id === event.id ? { ...msg, text: msg.text + event.text } : msg
            )
          );
          break;
        case "assistant_done":
          setMessages((m) =>
            m
              .map((msg) =>
                msg.id === event.id
                  ? { ...msg, text: event.text || msg.text, streaming: false }
                  : msg
              )
              // a proactive turn that produced nothing leaves no empty bubble
              .filter((msg) => msg.id !== event.id || msg.text.trim() !== "")
          );
          break;
        case "transcript":
          setMessages((m) => [
            ...m,
            { id: crypto.randomUUID(), role: "user", text: event.text },
          ]);
          break;
        case "emotion":
          if (isEmotion(event.name)) {
            if (emotionTimer.current) clearTimeout(emotionTimer.current);
            setEmotion(event.name);
          }
          break;
        case "status":
          setState(event.state);
          if (event.state !== "listening") setMicLevel(0);
          // feelings linger a moment after she goes quiet, then settle
          if (emotionTimer.current) clearTimeout(emotionTimer.current);
          if (event.state === "idle") {
            emotionTimer.current = setTimeout(
              () => setEmotion("neutral"),
              EMOTION_LINGER_MS
            );
          }
          break;
        case "mic_level":
          setMicLevel(event.level);
          break;
        case "tool_event": {
          const label = TOOL_LABELS[event.name] ?? event.name;
          setTool({
            name: label,
            status: event.status,
            detail:
              typeof event.detail === "string"
                ? event.detail
                : JSON.stringify(event.detail),
          });
          if (event.status !== "start") {
            setTimeout(
              () => setTool((t) => (t?.name === label ? null : t)),
              1400
            );
          }
          break;
        }
        case "history":
          setMessages(
            event.messages.map((m) => ({
              id: crypto.randomUUID(),
              role: m.role,
              text: m.content,
            }))
          );
          break;
        case "config":
          setConfig(event.config);
          break;
        case "error":
          setError(event.message);
          setTimeout(() => setError(null), 4000);
          break;
      }
    };

    connect();
    return () => {
      closed = true;
      clearTimeout(reconnectTimer);
      if (emotionTimer.current) clearTimeout(emotionTimer.current);
      wsRef.current?.close();
    };
  }, []);

  const send = useCallback(
    (text: string) => {
      const trimmed = text.trim();
      if (!trimmed) return;
      setMessages((m) => [
        ...m,
        { id: crypto.randomUUID(), role: "user", text: trimmed },
      ]);
      post({ type: "user_text", text: trimmed });
    },
    [post]
  );

  const startPtt = useCallback(() => post({ type: "ptt", action: "start" }), [post]);
  const stopPtt = useCallback(() => post({ type: "ptt", action: "stop" }), [post]);
  const interrupt = useCallback(() => post({ type: "interrupt" }), [post]);
  const reset = useCallback(() => {
    post({ type: "reset" });
    setMessages([]);
    setEmotion("neutral");
  }, [post]);
  const updateConfig = useCallback(
    (patch: Partial<ElaraConfig>) => post({ type: "set_config", config: patch }),
    [post]
  );

  return {
    connection,
    state,
    emotion,
    messages,
    tool,
    micLevel,
    config,
    error,
    send,
    startPtt,
    stopPtt,
    interrupt,
    reset,
    updateConfig,
  };
}
