import { Emotion } from "@/lib/protocol";

// How each emotion wears on the orb. Colors flow through the --elara-glow
// CSS variables (registered in index.css so they cross-fade); speeds bend
// the mote orbit and limb-light rotation; halo scales the ambient glow.
export interface EmotionVisual {
  /** limb light + bezel + mote color (--elara-glow) */
  glow: string;
  /** ambient halo color (--elara-glow-soft) */
  glowSoft: string;
  /** mote orbit period in seconds (neutral baseline 32) */
  moteSeconds: number;
  /** limb-light rotation period in seconds (neutral baseline 26) */
  limbSeconds: number;
  /** multiplier on halo opacity — >1 radiant, <1 subdued */
  halo: number;
}

export const EMOTIONS: Record<Emotion, EmotionVisual> = {
  // moonlight amber — her resting face
  neutral: {
    glow: "#e9b458",
    glowSoft: "rgba(233, 180, 88, 0.14)",
    moteSeconds: 32,
    limbSeconds: 26,
    halo: 1,
  },
  // bright gold, everything quickens
  joy: {
    glow: "#ffd077",
    glowSoft: "rgba(255, 208, 119, 0.2)",
    moteSeconds: 16,
    limbSeconds: 16,
    halo: 1.25,
  },
  // rose mischief, the mote races
  tease: {
    glow: "#f0a0c8",
    glowSoft: "rgba(240, 160, 200, 0.16)",
    moteSeconds: 9,
    limbSeconds: 22,
    halo: 1.1,
  },
  // cool teal, the limb light scans
  curious: {
    glow: "#8fd8e8",
    glowSoft: "rgba(143, 216, 232, 0.16)",
    moteSeconds: 22,
    limbSeconds: 13,
    halo: 1.1,
  },
  // warm lavender, everything slows and dims
  soft: {
    glow: "#cdb9f2",
    glowSoft: "rgba(205, 185, 242, 0.13)",
    moteSeconds: 44,
    limbSeconds: 38,
    halo: 0.85,
  },
  // signal ember — urgent, high contrast
  alert: {
    glow: "#ff8f66",
    glowSoft: "rgba(255, 143, 102, 0.2)",
    moteSeconds: 8,
    limbSeconds: 10,
    halo: 1.3,
  },
  // washed-out blue-grey, a long exhale
  sigh: {
    glow: "#9aa7c4",
    glowSoft: "rgba(154, 167, 196, 0.12)",
    moteSeconds: 42,
    limbSeconds: 34,
    halo: 0.75,
  },
};

export function isEmotion(name: string): name is Emotion {
  return name in EMOTIONS;
}
