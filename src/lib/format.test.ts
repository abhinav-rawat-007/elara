import { describe, expect, it } from "vitest";
import { formatReply } from "./format";

describe("formatReply", () => {
  it("keeps a short reply as a single breath", () => {
    expect(formatReply("Hey there. All good?")).toEqual(["Hey there. All good?"]);
  });

  it("returns nothing for empty text", () => {
    expect(formatReply("   ")).toEqual([]);
  });

  it("keeps a single sentence intact even when long", () => {
    const one = "The fans are calm today and the CPU is barely awake, honestly.";
    expect(formatReply(one)).toEqual([one]);
  });

  it("breaks a long reply into paragraphs of at most two sentences", () => {
    const text =
      "Found a few headlines. The big one is a new coding model. " +
      "There's also chatter about AI ethics. And Google shipped new agents. " +
      "It's a busy news day, honestly.";
    const paras = formatReply(text);
    expect(paras.length).toBeGreaterThan(1);
    // no paragraph runs longer than two sentences
    for (const p of paras) {
      const sentences = p.split(/(?<=[.!?…])\s+/).filter(Boolean);
      expect(sentences.length).toBeLessThanOrEqual(2);
    }
    // every word survives the reflow
    expect(paras.join(" ")).toBe(text);
  });

  it("detaches a closing question onto its own line in a longer reply", () => {
    const text =
      "Found three headlines. The big one is a new coding model. " +
      "Want me to dig into any of them?";
    const paras = formatReply(text);
    expect(paras[paras.length - 1]).toBe("Want me to dig into any of them?");
  });

  it("does not detach the question in a short two-sentence reply", () => {
    // choppy otherwise — a quick line should stay whole
    expect(formatReply("Done. Anything else?")).toEqual(["Done. Anything else?"]);
  });

  it("respects explicit newlines when present", () => {
    expect(formatReply("First thought.\n\nSecond thought.")).toEqual([
      "First thought.",
      "Second thought.",
    ]);
  });
});
