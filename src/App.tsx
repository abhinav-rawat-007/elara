import { useEffect, useState, type ReactNode } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { Minimize2, RotateCcw } from "lucide-react";
import { useElara } from "@/hooks/useElara";
import { Orb } from "@/components/Orb";
import { ChatPanel } from "@/components/ChatPanel";
import { ToolBadge } from "@/components/ToolBadge";
import { SettingsDialog } from "@/components/SettingsDialog";
import { MiniOrb } from "@/components/MiniOrb";
import { BootSequence } from "@/components/BootSequence";
import { Starfield } from "@/components/Starfield";
import { Button } from "@/components/ui/button";
import { setMiniMode } from "@/lib/tauri";
import { ElaraState, Emotion } from "@/lib/protocol";
import { isEmotion } from "@/lib/emotions";
import { cn } from "@/lib/utils";

export default function App() {
  const elara = useElara();
  const [mini, setMini] = useState(false);
  const [booted, setBooted] = useState(false);

  // Dev-only visual QA: /?state=listening|thinking|speaking previews orb
  // states, /?emotion=joy|tease|curious|soft|alert|sigh previews moods.
  const params = import.meta.env.DEV
    ? new URLSearchParams(window.location.search)
    : null;
  const stateOverride = params?.get("state") as ElaraState | null;
  const emotionParam = params?.get("emotion");
  const emotionOverride: Emotion | null =
    emotionParam && isEmotion(emotionParam) ? emotionParam : null;
  const state = stateOverride ?? elara.state;
  const emotion = emotionOverride ?? elara.emotion;

  const enterMini = () => {
    setMini(true);
    void setMiniMode(true);
  };
  const exitMini = () => {
    setMini(false);
    void setMiniMode(false);
  };

  // Spacebar push-to-talk (ignored while typing in the input).
  // Depends on the stable callbacks, not `elara` itself: the elara object is
  // recreated every render (mic_level streams ~20/s while listening), and
  // re-running this effect would reset `holding` so keyup never sent "stop".
  const { startPtt, stopPtt } = elara;
  useEffect(() => {
    let holding = false;
    const isTyping = (t: EventTarget | null) =>
      t instanceof HTMLElement &&
      (t.tagName === "INPUT" || t.tagName === "TEXTAREA");

    const down = (e: KeyboardEvent) => {
      if (e.code === "Space" && !e.repeat && !isTyping(e.target)) {
        e.preventDefault();
        holding = true;
        startPtt();
      }
    };
    const up = (e: KeyboardEvent) => {
      if (e.code === "Space" && holding) {
        e.preventDefault();
        holding = false;
        stopPtt();
      }
    };
    // losing focus mid-hold swallows the keyup — close the mic instead of
    // leaving it stuck open
    const cancel = () => {
      if (holding) {
        holding = false;
        stopPtt();
      }
    };
    window.addEventListener("keydown", down);
    window.addEventListener("keyup", up);
    window.addEventListener("blur", cancel);
    return () => {
      window.removeEventListener("keydown", down);
      window.removeEventListener("keyup", up);
      window.removeEventListener("blur", cancel);
    };
  }, [startPtt, stopPtt]);

  const boot = (
    <AnimatePresence>
      {!booted && <BootSequence onDone={() => setBooted(true)} />}
    </AnimatePresence>
  );

  if (mini) {
    return (
      <>
        <ToolBadge tool={elara.tool} />
        <MiniOrb
          state={state}
          micLevel={elara.micLevel}
          emotion={emotion}
          onExpand={exitMini}
        />
        {boot}
      </>
    );
  }

  const offline = elara.connection !== "online";

  return (
    <div className="relative flex h-screen w-screen overflow-hidden text-foreground">
      <Starfield />

      {/* ambient night glows */}
      <div className="pointer-events-none absolute inset-0" aria-hidden>
        <div className="absolute -left-32 bottom-[-8rem] h-96 w-96 rounded-full bg-elara-glow/[0.06] blur-3xl" />
        <div className="absolute -right-24 top-[-6rem] h-80 w-80 rounded-full bg-elara-night/[0.08] blur-3xl" />
      </div>

      <ToolBadge tool={elara.tool} />

      {/* left: the stage */}
      <div className="relative hidden flex-1 flex-col md:flex">
        <header className="flex items-start justify-between px-7 pt-6">
          <div>
            <h1 className="font-mono text-lg font-medium tracking-[0.32em] text-foreground">
              ELARA
            </h1>
            <p className="telemetry mt-1 text-muted-foreground/70">
              Jupiter VII · Local companion
            </p>
          </div>
          <ConnectionReadout connection={elara.connection} />
        </header>

        <div className="flex flex-1 flex-col items-center justify-center gap-4">
          <Orb
            state={state}
            micLevel={elara.micLevel}
            emotion={emotion}
            onInterrupt={elara.interrupt}
          />
        </div>

        <footer className="pb-6 text-center">
          <p className="telemetry text-muted-foreground/60">
            Hold <Kbd>Space</Kbd> to talk · press while she speaks to cut in
          </p>
        </footer>
      </div>

      {/* right: conversation rail */}
      <div className="relative z-10 flex w-full flex-col border-l border-border bg-card/50 backdrop-blur-sm md:w-[440px]">
        <header className="flex items-center justify-between border-b border-border px-4 py-3">
          {/* identity — carries the brand when the stage is hidden (narrow window) */}
          <div className="flex items-center gap-2.5 md:hidden">
            <span className="font-mono text-sm font-medium tracking-[0.28em]">
              ELARA
            </span>
            <ConnectionReadout connection={elara.connection} compact />
          </div>
          <span className="telemetry hidden text-muted-foreground/70 md:inline">
            Conversation
          </span>

          <div className="flex items-center gap-1">
            <Button
              variant="ghost"
              size="icon"
              title="Mini orb mode"
              aria-label="Switch to mini orb mode"
              onClick={enterMini}
            >
              <Minimize2 className="size-4" />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              title="New conversation"
              aria-label="Start a new conversation"
              onClick={elara.reset}
            >
              <RotateCcw className="size-4" />
            </Button>
            <SettingsDialog
              config={elara.config}
              onChange={elara.updateConfig}
            />
          </div>
        </header>

        <div className="flex-1 overflow-hidden px-3 pb-3">
          <ChatPanel
            messages={elara.messages}
            state={state}
            tool={elara.tool}
            offline={offline && !stateOverride}
            onSend={elara.send}
            onPttDown={elara.startPtt}
            onPttUp={elara.stopPtt}
            onInterrupt={elara.interrupt}
          />
        </div>
      </div>

      <AnimatePresence>
        {elara.error && (
          <motion.div
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 16 }}
            role="alert"
            className="absolute bottom-5 left-1/2 z-20 flex -translate-x-1/2 items-center gap-2 rounded-lg border border-destructive/40 bg-popover px-4 py-2.5 text-sm text-destructive shadow-xl"
          >
            {elara.error}
          </motion.div>
        )}
      </AnimatePresence>
      {boot}
    </div>
  );
}

function Kbd({ children }: { children: ReactNode }) {
  return (
    <kbd className="rounded border border-border bg-secondary px-1.5 py-0.5 font-mono text-[10px] tracking-normal text-foreground/80">
      {children}
    </kbd>
  );
}

function ConnectionReadout({
  connection,
  compact = false,
}: {
  connection: string;
  compact?: boolean;
}) {
  const online = connection === "online";
  const connecting = connection === "connecting";
  return (
    <span
      className={cn(
        "telemetry flex items-center gap-2",
        online ? "text-success/80" : "text-muted-foreground/70"
      )}
      role="status"
    >
      <span
        className={cn(
          "h-1.5 w-1.5 rounded-full",
          online && "bg-success",
          connecting && "animate-pulse bg-elara-glow",
          !online && !connecting && "bg-destructive/80"
        )}
      />
      {compact
        ? null
        : online
          ? "Link online"
          : connecting
            ? "Linking…"
            : "Offline · retrying"}
    </span>
  );
}
