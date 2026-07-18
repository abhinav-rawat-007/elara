import { Maximize2 } from "lucide-react";
import { ElaraState, Emotion } from "@/lib/protocol";
import { startDragging } from "@/lib/tauri";
import { Orb } from "@/components/Orb";

interface MiniOrbProps {
  state: ElaraState;
  micLevel: number;
  emotion?: Emotion;
  onExpand: () => void;
}

// Compact always-on-top view: just the orb, draggable, with a button to
// restore the full HUD. Push-to-talk (Space) keeps working here.
export function MiniOrb({ state, micLevel, emotion, onExpand }: MiniOrbProps) {
  return (
    <div
      className="group relative flex h-screen w-screen cursor-grab items-center justify-center overflow-hidden active:cursor-grabbing"
      onMouseDown={(e) => {
        // drag the window from the background, but not from the button
        if (!(e.target as HTMLElement).closest("button")) startDragging();
      }}
    >
      <div className="pointer-events-none absolute inset-0" aria-hidden>
        <div className="absolute left-1/2 top-1/2 h-64 w-64 -translate-x-1/2 -translate-y-1/2 rounded-full bg-elara-glow/[0.08] blur-3xl" />
      </div>

      <div className="scale-[0.68]">
        <Orb state={state} micLevel={micLevel} emotion={emotion} />
      </div>

      <button
        onClick={onExpand}
        title="Expand"
        aria-label="Restore full window"
        className="absolute right-2 top-2 rounded-md border border-transparent p-1.5 text-muted-foreground opacity-0 transition hover:border-border hover:bg-secondary hover:text-foreground focus-visible:opacity-100 group-hover:opacity-100"
      >
        <Maximize2 className="size-4" />
      </button>
    </div>
  );
}
