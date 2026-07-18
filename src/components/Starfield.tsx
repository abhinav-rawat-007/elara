import { useMemo } from "react";
import { useReducedMotion } from "framer-motion";

/** Sparse, deterministic star specks behind the stage. */
export function Starfield() {
  const reduceMotion = useReducedMotion();
  const stars = useMemo(() => {
    // simple seeded PRNG (mulberry32) so the sky is stable between renders
    let seed = 1905; // Elara's discovery year
    const rand = () => {
      seed |= 0;
      seed = (seed + 0x6d2b79f5) | 0;
      let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
    return Array.from({ length: 70 }, (_, i) => ({
      id: i,
      x: rand() * 100,
      y: rand() * 100,
      r: 0.4 + rand() * 0.9,
      o: 0.08 + rand() * 0.3,
      twinkle: rand() > 0.75,
      delay: rand() * 6,
    }));
  }, []);

  return (
    <svg
      className="pointer-events-none absolute inset-0 h-full w-full"
      aria-hidden
    >
      {stars.map((s) => (
        <circle
          key={s.id}
          cx={`${s.x}%`}
          cy={`${s.y}%`}
          r={s.r}
          fill="var(--foreground)"
          opacity={s.o}
          className={s.twinkle && !reduceMotion ? "star-twinkle" : undefined}
          style={s.twinkle ? { animationDelay: `${s.delay}s` } : undefined}
        />
      ))}
    </svg>
  );
}
