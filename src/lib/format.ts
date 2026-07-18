/**
 * Turn one of Elara's spoken replies into readable paragraphs.
 *
 * Her replies arrive as plain speech — no markdown, no line breaks — so a long
 * answer would otherwise render as one undifferentiated wall of text. She is
 * written to sound like "a person mid-thought", so we lay her words out the way
 * she says them: in breaths. Each paragraph is a breath of one or two sentences,
 * and a closing question detaches onto its own line — mirroring the backend,
 * where asking something ends her turn and hands it back to you.
 *
 * Pure and deterministic so it can be unit-tested and re-run safely on every
 * streamed token without surprising the layout.
 */

// A breath runs to two sentences, or ~180 characters, whichever comes first.
const MAX_SENTENCES_PER_PARA = 2;
const MAX_CHARS_PER_PARA = 180;
// Below this, a whole reply stays a single breath — breaking a quick line into
// stacked fragments reads as choppy, not natural.
const SINGLE_BREATH_MAX = 140;

/** Split on the whitespace that follows a sentence terminator, keeping the
 *  terminator attached. WebView2 is Chromium, so the lookbehind is safe. */
function splitSentences(text: string): string[] {
  return text
    .split(/(?<=[.!?…])\s+/)
    .map((s) => s.trim())
    .filter(Boolean);
}

const isQuestion = (s: string) => /\?["')\]]*$/.test(s.trim());

export function formatReply(text: string): string[] {
  const trimmed = text.trim();
  if (!trimmed) return [];

  // Respect explicit breaks if the text ever carries them (e.g. a future
  // multi-paragraph answer joined with newlines).
  if (/\n/.test(trimmed)) {
    return trimmed
      .split(/\n+/)
      .map((p) => p.trim())
      .filter(Boolean);
  }

  const sentences = splitSentences(trimmed);
  // A short reply is one breath — don't fragment a quick line.
  if (sentences.length <= 1) return [trimmed];
  if (trimmed.length <= SINGLE_BREATH_MAX && sentences.length <= 2) {
    return [trimmed];
  }

  const paragraphs: string[] = [];
  let current: string[] = [];
  let currentLen = 0;
  const flush = () => {
    if (current.length) paragraphs.push(current.join(" "));
    current = [];
    currentLen = 0;
  };

  sentences.forEach((sentence, i) => {
    const isLast = i === sentences.length - 1;
    // A closing question, after she's already said something, gets its own line
    // — the beat where she hands the turn back. Only once the reply is
    // substantial enough (3+ sentences) that the pause reads as intentional.
    if (isLast && isQuestion(sentence) && current.length && sentences.length >= 3) {
      flush();
      paragraphs.push(sentence);
      return;
    }
    current.push(sentence);
    currentLen += sentence.length;
    if (current.length >= MAX_SENTENCES_PER_PARA || currentLen >= MAX_CHARS_PER_PARA) {
      flush();
    }
  });
  flush();
  return paragraphs;
}
