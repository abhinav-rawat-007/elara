import type { CSSProperties } from "react";
import { motion, useReducedMotion } from "framer-motion";
import { ElaraState, Emotion } from "@/lib/protocol";
import { EMOTIONS } from "@/lib/emotions";
import { cn } from "@/lib/utils";

interface OrbProps {
  state: ElaraState;
  micLevel: number;
  /** Current feeling — recolors the glow and bends the motion. */
  emotion?: Emotion;
  /** Called when the orb is clicked while speaking (cut her off). */
  onInterrupt?: () => void;
}

const STATE_LABEL: Record<ElaraState, string> = {
  idle: "Standing by",
  listening: "Listening",
  thinking: "Thinking",
  speaking: "Speaking",
};

// SVG geometry — viewBox is 280×280, centred at 140.
const C = 140;
const BEZEL_R = 126; // tick ring / level meter
const ORBIT_R = 102; // path of the orbiting mote
const DISC_R = 66; // the dark moon disc
const BEZEL_LEN = 2 * Math.PI * BEZEL_R;
const LIMB_LEN = 2 * Math.PI * DISC_R;

/**
 * The eclipse dial. A dark moon disc with an amber limb-light, ringed by an
 * instrument bezel whose ticks double as the mic level meter, plus one mote
 * orbiting the disc — Elara circling Jupiter.
 *
 * Motion signatures: idle = slow limb drift · listening = level arc on the
 * bezel · thinking = fast limb sweep · speaking = ripple rings.
 */
export function Orb({ state, micLevel, emotion = "neutral", onInterrupt }: OrbProps) {
  const reduceMotion = useReducedMotion();
  const speaking = state === "speaking";
  const listening = state === "listening";
  const thinking = state === "thinking";

  // Mic level (0..~0.15 typical) → 0..1 of the bezel arc.
  const level = Math.min(micLevel * 7, 1);

  // The feeling she wears: glow color cross-fades via the registered CSS
  // variables (see index.css); speeds and halo intensity shift with it.
  const mood = EMOTIONS[emotion] ?? EMOTIONS.neutral;
  const haloDim = (o: number) => Math.min(1, o * mood.halo);

  return (
    <div
      className="orb-mood flex select-none flex-col items-center gap-7"
      style={
        {
          "--elara-glow": mood.glow,
          "--elara-glow-soft": mood.glowSoft,
        } as CSSProperties
      }
    >
      <motion.div
        className={cn("relative h-70 w-70", speaking && "cursor-pointer")}
        onClick={speaking ? onInterrupt : undefined}
        role={speaking ? "button" : undefined}
        aria-label={speaking ? "Stop speaking" : undefined}
        title={speaking ? "Click to interrupt" : undefined}
        whileTap={speaking ? { scale: 0.98 } : undefined}
      >
        {/* ambient halo behind the instrument */}
        <motion.div
          aria-hidden
          className="absolute inset-[-40px] rounded-full"
          style={{
            background:
              "radial-gradient(circle, var(--elara-glow-soft) 0%, transparent 62%)",
          }}
          animate={
            reduceMotion
              ? { opacity: haloDim(state === "idle" ? 0.5 : 0.9) }
              : {
                  opacity: (state === "idle"
                    ? [0.35, 0.55, 0.35]
                    : [0.7, 1, 0.7]
                  ).map(haloDim),
                  scale: speaking ? [1, 1.08, 1] : [1, 1.03, 1],
                }
          }
          transition={{
            duration: speaking ? 1.1 : 4.5,
            repeat: reduceMotion ? 0 : Infinity,
            ease: "easeInOut",
          }}
        />

        <svg viewBox="0 0 280 280" className="relative h-full w-full">
          <defs>
            <radialGradient id="orb-disc" cx="38%" cy="32%" r="80%">
              <stop offset="0%" stopColor="#1d2230" />
              <stop offset="55%" stopColor="#12151f" />
              <stop offset="100%" stopColor="#0a0c12" />
            </radialGradient>
          </defs>

          {/* bezel — instrument ticks */}
          <circle
            cx={C}
            cy={C}
            r={BEZEL_R}
            fill="none"
            stroke="var(--foreground)"
            strokeOpacity={0.14}
            strokeWidth={5}
            strokeDasharray={`1.5 ${BEZEL_LEN / 72 - 1.5}`}
          />

          {/* bezel meter — mic level while listening, sweep while thinking */}
          {listening && (
            <motion.circle
              cx={C}
              cy={C}
              r={BEZEL_R}
              fill="none"
              stroke="var(--elara-glow)"
              strokeWidth={5}
              strokeLinecap="round"
              strokeDasharray={BEZEL_LEN}
              transform={`rotate(-90 ${C} ${C})`}
              initial={{ strokeDashoffset: BEZEL_LEN }}
              animate={{
                strokeDashoffset: BEZEL_LEN * (1 - Math.max(level, 0.02)),
              }}
              transition={{ type: "spring", stiffness: 260, damping: 26 }}
            />
          )}
          {thinking && (
            <motion.g
              animate={reduceMotion ? undefined : { rotate: 360 }}
              transition={{ duration: 2.4, repeat: Infinity, ease: "linear" }}
              style={{ transformOrigin: "140px 140px" }}
            >
              <circle
                cx={C}
                cy={C}
                r={BEZEL_R}
                fill="none"
                stroke="var(--elara-glow)"
                strokeOpacity={0.85}
                strokeWidth={5}
                strokeLinecap="round"
                strokeDasharray={`${BEZEL_LEN * 0.16} ${BEZEL_LEN * 0.84}`}
              />
            </motion.g>
          )}

          {/* orbit path + mote */}
          <circle
            cx={C}
            cy={C}
            r={ORBIT_R}
            fill="none"
            stroke="var(--foreground)"
            strokeOpacity={0.07}
            strokeWidth={1}
          />
          {!reduceMotion && (
            <motion.g
              animate={{ rotate: 360 }}
              transition={{
                duration: thinking ? 10 : mood.moteSeconds,
                repeat: Infinity,
                ease: "linear",
              }}
              style={{ transformOrigin: "140px 140px" }}
            >
              <circle
                cx={C + ORBIT_R}
                cy={C}
                r={3}
                fill="var(--elara-glow)"
                fillOpacity={0.9}
              />
            </motion.g>
          )}

          {/* speaking ripples */}
          {speaking && !reduceMotion && (
            <>
              {[0, 1].map((i) => (
                <motion.circle
                  key={i}
                  cx={C}
                  cy={C}
                  r={DISC_R}
                  fill="none"
                  stroke="var(--elara-glow)"
                  strokeWidth={1.5}
                  initial={{ scale: 1, opacity: 0.55 }}
                  animate={{ scale: 1.75, opacity: 0 }}
                  transition={{
                    duration: 1.6,
                    repeat: Infinity,
                    delay: i * 0.8,
                    ease: "easeOut",
                  }}
                  style={{ transformOrigin: "140px 140px" }}
                />
              ))}
            </>
          )}

          {/* the dark moon */}
          <motion.g
            style={{ transformOrigin: "140px 140px" }}
            animate={
              reduceMotion
                ? undefined
                : listening
                  ? { scale: 1 + level * 0.06 }
                  : speaking
                    ? { scale: [1, 1.035, 0.99, 1] }
                    : { scale: [1, 1.015, 1] }
            }
            transition={
              listening
                ? { type: "spring", stiffness: 300, damping: 22 }
                : {
                    duration: speaking ? 0.6 : 5,
                    repeat: reduceMotion ? 0 : Infinity,
                    ease: "easeInOut",
                  }
            }
          >
            <circle cx={C} cy={C} r={DISC_R} fill="url(#orb-disc)" />
            <circle
              cx={C}
              cy={C}
              r={DISC_R}
              fill="none"
              stroke="var(--foreground)"
              strokeOpacity={0.1}
              strokeWidth={1}
            />

            {/* limb light — the sunlit edge */}
            <motion.g
              style={{ transformOrigin: "140px 140px" }}
              animate={reduceMotion ? undefined : { rotate: 360 }}
              transition={{
                duration: thinking ? 3 : mood.limbSeconds,
                repeat: Infinity,
                ease: "linear",
              }}
            >
              {/* glow is faked with layered soft strokes — SVG blur filters
                  re-rasterize every frame and stall the compositor */}
              <motion.g
                animate={{
                  opacity: speaking
                    ? [0.9, 1, 0.7, 0.9]
                    : listening
                      ? 0.7 + level * 0.3
                      : [0.55, 0.85, 0.55],
                }}
                transition={{
                  duration: speaking ? 0.6 : 4,
                  repeat: reduceMotion || listening ? 0 : Infinity,
                  ease: "easeInOut",
                }}
              >
                <circle
                  cx={C}
                  cy={C}
                  r={DISC_R}
                  fill="none"
                  stroke="var(--elara-glow)"
                  strokeOpacity={0.12}
                  strokeWidth={9}
                  strokeLinecap="round"
                  strokeDasharray={`${LIMB_LEN * 0.3} ${LIMB_LEN * 0.7}`}
                />
                <circle
                  cx={C}
                  cy={C}
                  r={DISC_R}
                  fill="none"
                  stroke="var(--elara-glow)"
                  strokeOpacity={0.3}
                  strokeWidth={4.5}
                  strokeLinecap="round"
                  strokeDasharray={`${LIMB_LEN * 0.3} ${LIMB_LEN * 0.7}`}
                />
                <circle
                  cx={C}
                  cy={C}
                  r={DISC_R}
                  fill="none"
                  stroke="var(--elara-glow)"
                  strokeOpacity={0.95}
                  strokeWidth={1.8}
                  strokeLinecap="round"
                  strokeDasharray={`${LIMB_LEN * 0.3} ${LIMB_LEN * 0.7}`}
                />
              </motion.g>
            </motion.g>
          </motion.g>
        </svg>
      </motion.div>

      {/* state readout */}
      <div
        className="telemetry flex items-center gap-2.5 text-muted-foreground"
        role="status"
        aria-live="polite"
      >
        <span
          className={cn(
            "h-1.5 w-1.5 rounded-full",
            state === "idle" ? "bg-muted-foreground/50" : "bg-elara-glow"
          )}
        />
        {STATE_LABEL[state]}
        {speaking && (
          <span className="normal-case tracking-normal text-muted-foreground/60">
            · click to interrupt
          </span>
        )}
      </div>
    </div>
  );
}
