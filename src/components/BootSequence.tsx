import { motion, useReducedMotion } from "framer-motion";
import { useEffect } from "react";
import { Starfield } from "@/components/Starfield";

interface BootSequenceProps {
  /** Fired once the sequence has finished and the overlay should unmount. */
  onDone: () => void;
}

// Same dial geometry as the live Orb (viewBox 280×280, centred at 140) so the
// calibration ring lines up with the instrument it's about to reveal.
const C = 140;
const BEZEL_R = 126;
const DISC_R = 66;
const BEZEL_LEN = 2 * Math.PI * BEZEL_R;

const LOG_LINES = ["OPTICS ONLINE", "LIMB CALIBRATED", "ESTABLISHING LINK"];

const TOTAL_MS = 3200;
const REDUCED_MS = 900;

/**
 * The instrument waking up. Plays once per launch: bezel dims in, an amber
 * ring sweeps once around it (calibrating), a boot log ticks past, the dark
 * moon disc fades up, and the wordmark tracks in from wide to resting
 * spacing — then the whole dial dissolves to reveal the live Orb beneath.
 */
export function BootSequence({ onDone }: BootSequenceProps) {
  const reduceMotion = useReducedMotion();

  useEffect(() => {
    const t = setTimeout(onDone, reduceMotion ? REDUCED_MS : TOTAL_MS);
    return () => clearTimeout(t);
  }, [onDone, reduceMotion]);

  return (
    <motion.div
      className="fixed inset-0 z-50 flex flex-col items-center justify-center gap-8 bg-background"
      style={{
        backgroundImage:
          "radial-gradient(120% 90% at 30% 0%, var(--background) 0%, var(--background-deep) 100%)",
      }}
      initial={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: reduceMotion ? 0.25 : 0.55, ease: "easeInOut" }}
    >
      <Starfield />

      <div className="relative h-56 w-56">
        {/* ambient halo bloom, arrives with the disc */}
        <motion.div
          aria-hidden
          className="pointer-events-none absolute inset-[-30px] rounded-full"
          style={{
            background:
              "radial-gradient(circle, var(--elara-glow-soft) 0%, transparent 62%)",
          }}
          initial={{ opacity: 0 }}
          animate={{ opacity: 0.85 }}
          transition={{ duration: 0.8, delay: reduceMotion ? 0 : 1.4 }}
        />

        <svg viewBox="0 0 280 280" className="relative h-full w-full">
          <defs>
            <radialGradient id="boot-disc" cx="38%" cy="32%" r="80%">
              <stop offset="0%" stopColor="#1d2230" />
              <stop offset="55%" stopColor="#12151f" />
              <stop offset="100%" stopColor="#0a0c12" />
            </radialGradient>
          </defs>

          {/* dim instrument bezel, same ticks as the live dial */}
          <motion.circle
            cx={C}
            cy={C}
            r={BEZEL_R}
            fill="none"
            stroke="var(--foreground)"
            strokeOpacity={0.14}
            strokeWidth={5}
            strokeDasharray={`1.5 ${BEZEL_LEN / 72 - 1.5}`}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.6 }}
          />

          {/* calibration sweep — one amber pass around the bezel */}
          {!reduceMotion && (
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
              initial={{ strokeDashoffset: BEZEL_LEN, opacity: 0.9 }}
              animate={{ strokeDashoffset: 0, opacity: [0.9, 0.9, 0] }}
              transition={{
                strokeDashoffset: { duration: 1.1, delay: 0.15, ease: "easeInOut" },
                opacity: { duration: 1.4, delay: 0.15, times: [0, 0.85, 1] },
              }}
            />
          )}

          {/* the dark moon, fading up once calibration lands */}
          <motion.g
            style={{ transformOrigin: "140px 140px" }}
            initial={{ opacity: 0, scale: 0.85 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{
              duration: reduceMotion ? 0.4 : 0.7,
              delay: reduceMotion ? 0.1 : 1.4,
              ease: "easeOut",
            }}
          >
            <circle cx={C} cy={C} r={DISC_R} fill="url(#boot-disc)" />
            <circle
              cx={C}
              cy={C}
              r={DISC_R}
              fill="none"
              stroke="var(--elara-glow)"
              strokeOpacity={0.95}
              strokeWidth={1.8}
            />
          </motion.g>
        </svg>
      </div>

      {/* boot log */}
      {!reduceMotion && (
        <div className="telemetry flex h-4 items-center gap-2 text-muted-foreground/70">
          {LOG_LINES.map((line, i) => (
            <motion.span
              key={line}
              className="flex items-center gap-2"
              initial={{ opacity: 0, y: 4 }}
              animate={{ opacity: [0, 1, 1, 0], y: 0 }}
              transition={{
                duration: 0.9,
                delay: 0.35 + i * 0.42,
                times: [0, 0.2, 0.75, 1],
              }}
            >
              {i > 0 && <span className="text-muted-foreground/30">·</span>}
              {line}
            </motion.span>
          ))}
        </div>
      )}

      {/* wordmark, tracking in from wide to resting spacing */}
      <div className="flex flex-col items-center gap-1.5">
        <motion.h1
          className="font-mono text-xl font-medium text-foreground"
          initial={{ letterSpacing: "0.9em", opacity: 0 }}
          animate={{ letterSpacing: "0.32em", opacity: 1 }}
          transition={{
            duration: reduceMotion ? 0.3 : 0.75,
            delay: reduceMotion ? 0.15 : 2.05,
            ease: "easeOut",
          }}
        >
          ELARA
        </motion.h1>
        <motion.p
          className="telemetry text-muted-foreground/60"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{
            duration: 0.5,
            delay: reduceMotion ? 0.25 : 2.5,
          }}
        >
          Jupiter VII · Local companion
        </motion.p>
      </div>
    </motion.div>
  );
}
