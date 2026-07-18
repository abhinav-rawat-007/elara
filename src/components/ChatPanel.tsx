import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { ArrowUp, Loader2, Mic, Square } from "lucide-react";
import { ChatMessage, ElaraState, ToolActivity } from "@/lib/protocol";
import { formatReply } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

interface ChatPanelProps {
  messages: ChatMessage[];
  state: ElaraState;
  tool: ToolActivity | null;
  offline: boolean;
  onSend: (text: string) => void;
  onPttDown: () => void;
  onPttUp: () => void;
  onInterrupt: () => void;
}

const SUGGESTIONS = [
  "What can you do?",
  "Open Spotify",
  "What's the weather right now?",
  "Set the volume to 30 percent",
];

export function ChatPanel({
  messages,
  state,
  tool,
  offline,
  onSend,
  onPttDown,
  onPttUp,
  onInterrupt,
}: ChatPanelProps) {
  const [draft, setDraft] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);
  const holdingRef = useRef(false);

  useEffect(() => {
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [messages, tool]);

  const submit = () => {
    if (!draft.trim() || offline) return;
    onSend(draft);
    setDraft("");
  };

  const pttDown = () => {
    if (offline) return;
    holdingRef.current = true;
    onPttDown();
  };
  const pttUp = () => {
    if (!holdingRef.current) return;
    holdingRef.current = false;
    onPttUp();
  };

  return (
    <div className="flex h-full flex-col">
      <div
        ref={scrollRef}
        className="flex-1 space-y-4 overflow-y-auto px-1 py-3 [scrollbar-gutter:stable]"
      >
        {messages.length === 0 && <EmptyState onSend={onSend} offline={offline} />}
        <AnimatePresence initial={false}>
          {messages.map((msg) =>
            msg.role === "user" ? (
              <motion.div
                key={msg.id}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                className="flex justify-end"
              >
                <div className="max-w-[85%] rounded-xl rounded-br-sm border border-elara-glow/20 bg-elara-glow/10 px-3.5 py-2 text-[15px] leading-relaxed text-foreground">
                  {msg.text}
                </div>
              </motion.div>
            ) : (
              <motion.div
                key={msg.id}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                className="flex gap-2.5 pr-6"
              >
                <CrescentGlyph className="mt-1.5 shrink-0" />
                <div className="min-w-0 text-[15px] leading-relaxed text-foreground/95">
                  {msg.text ? (
                    <AssistantText text={msg.text} streaming={msg.streaming} />
                  ) : msg.streaming ? (
                    <TypingDots />
                  ) : null}
                </div>
              </motion.div>
            )
          )}
        </AnimatePresence>

        {/* live tool activity — stays visible for the whole tool run, unlike
            the floating badge, so long searches never look like silence */}
        <AnimatePresence>
          {tool?.status === "start" && (
            <motion.div
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: 6 }}
              className="flex items-center gap-2.5 pl-7"
              role="status"
            >
              <Loader2 className="size-3 shrink-0 animate-spin text-elara-glow/80" />
              <span className="telemetry text-muted-foreground">
                {tool.name}…
              </span>
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {/* composer */}
      <div className="border-t border-border pt-3">
        <AnimatePresence>
          {state === "speaking" && (
            <motion.div
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: 6 }}
              className="mb-2 flex justify-center"
            >
              <button
                onClick={onInterrupt}
                className="telemetry flex items-center gap-1.5 rounded-full border border-border bg-secondary/60 px-3 py-1.5 text-muted-foreground transition-colors hover:border-elara-glow/40 hover:text-foreground"
              >
                <Square className="size-2.5 fill-current" />
                Stop speaking
              </button>
            </motion.div>
          )}
        </AnimatePresence>

        <div className="flex items-center gap-2">
          <Input
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.nativeEvent.isComposing) submit();
            }}
            placeholder={offline ? "Waiting for backend…" : "Message Elara…"}
            aria-label="Message Elara"
            disabled={offline}
            className="h-10 flex-1 rounded-xl bg-secondary/50"
          />
          <Button
            size="icon"
            variant="secondary"
            aria-label="Hold to talk"
            title="Hold to talk"
            disabled={offline}
            className={cn(
              "size-10 rounded-xl transition-shadow",
              state === "listening" &&
                "bg-elara-glow text-primary-foreground shadow-[0_0_20px_-4px_var(--elara-glow)] hover:bg-elara-glow"
            )}
            onPointerDown={pttDown}
            onPointerUp={pttUp}
            onPointerLeave={pttUp}
            onPointerCancel={pttUp}
          >
            <Mic className="size-4" />
          </Button>
          <Button
            size="icon"
            aria-label="Send message"
            title="Send"
            onClick={submit}
            disabled={!draft.trim() || offline}
            className="size-10 rounded-xl"
          >
            <ArrowUp className="size-4" />
          </Button>
        </div>
      </div>
    </div>
  );
}

function EmptyState({
  onSend,
  offline,
}: {
  onSend: (text: string) => void;
  offline: boolean;
}) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-6 px-6 text-center">
      <CrescentGlyph size={28} />
      <div className="space-y-1.5">
        <p className="text-sm text-foreground/90">
          Say hello — type below, or hold the mic to talk.
        </p>
        <p className="text-xs text-muted-foreground">
          She can open apps, search the web, control volume, and more.
        </p>
      </div>
      {!offline && (
        <div className="flex max-w-xs flex-wrap justify-center gap-2">
          {SUGGESTIONS.map((s) => (
            <button
              key={s}
              onClick={() => onSend(s)}
              className="rounded-full border border-border bg-secondary/40 px-3 py-1.5 text-xs text-muted-foreground transition-colors hover:border-elara-glow/40 hover:text-foreground"
            >
              {s}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/** Small eclipse mark used as the assistant's avatar. */
function CrescentGlyph({
  size = 14,
  className,
}: {
  size?: number;
  className?: string;
}) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 16 16"
      aria-hidden
      className={className}
    >
      <circle cx="8" cy="8" r="7" fill="#12151f" stroke="rgba(255,255,255,0.1)" />
      <path
        d="M 3.05 5.15 A 7 7 0 0 1 12.95 5.15"
        fill="none"
        stroke="var(--elara-glow)"
        strokeWidth="1.6"
        strokeLinecap="round"
      />
    </svg>
  );
}

/**
 * Elara's reply, laid out as breaths. A long answer becomes stacked paragraphs
 * instead of a wall of text; each breath fades up in sequence, the way she'd
 * say them. The streaming caret rides the last line.
 */
function AssistantText({
  text,
  streaming,
}: {
  text: string;
  streaming?: boolean;
}) {
  const reduce = useReducedMotion();
  const paragraphs = formatReply(text);

  return (
    <div className="space-y-2.5">
      {paragraphs.map((para, i) => {
        const isLast = i === paragraphs.length - 1;
        return (
          <motion.p
            // index keys keep already-shown breaths mounted as new ones stream in,
            // so only the fresh paragraph animates — the rest stay put
            key={i}
            initial={reduce ? false : { opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.28, ease: "easeOut" }}
            className="[overflow-wrap:anywhere]"
          >
            {para}
            {streaming && isLast && <StreamCaret />}
          </motion.p>
        );
      })}
    </div>
  );
}

function StreamCaret() {
  return (
    <motion.span
      aria-hidden
      className="ml-0.5 inline-block h-[1em] w-[7px] translate-y-[2px] bg-elara-glow/80"
      animate={{ opacity: [1, 0.15, 1] }}
      transition={{ duration: 1, repeat: Infinity, ease: "easeInOut" }}
    />
  );
}

function TypingDots() {
  return (
    <span className="inline-flex gap-1 py-2" aria-label="Elara is thinking">
      {[0, 1, 2].map((i) => (
        <motion.span
          key={i}
          className="h-1.5 w-1.5 rounded-full bg-elara-glow/70"
          animate={{ opacity: [0.25, 1, 0.25] }}
          transition={{ duration: 1, repeat: Infinity, delay: i * 0.2 }}
        />
      ))}
    </span>
  );
}
