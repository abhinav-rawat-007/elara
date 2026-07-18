import { describe, expect, it } from "vitest";
import { EMOTIONS, isEmotion } from "./emotions";
import type { Emotion } from "./protocol";

const EXPECTED: Emotion[] = [
  "neutral",
  "joy",
  "tease",
  "curious",
  "soft",
  "alert",
  "sigh",
];

describe("emotions", () => {
  it("defines a visual for every emotion in the protocol", () => {
    for (const e of EXPECTED) {
      expect(EMOTIONS[e]).toBeDefined();
      expect(EMOTIONS[e].glow).toMatch(/^#/);
    }
  });

  it("isEmotion accepts known tags and rejects unknown ones", () => {
    expect(isEmotion("joy")).toBe(true);
    expect(isEmotion("neutral")).toBe(true);
    expect(isEmotion("hungry")).toBe(false);
    expect(isEmotion("")).toBe(false);
  });
});
