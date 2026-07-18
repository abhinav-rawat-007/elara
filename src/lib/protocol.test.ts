import { describe, expect, it } from "vitest";
import { wsUrlWithToken, TOOL_LABELS } from "./protocol";

describe("wsUrlWithToken", () => {
  it("returns the base URL unchanged when there is no token", () => {
    expect(wsUrlWithToken("ws://127.0.0.1:8765/ws", "")).toBe(
      "ws://127.0.0.1:8765/ws"
    );
  });

  it("appends the token with ? when the URL has no query", () => {
    expect(wsUrlWithToken("ws://127.0.0.1:8765/ws", "abc")).toBe(
      "ws://127.0.0.1:8765/ws?token=abc"
    );
  });

  it("appends the token with & when the URL already has a query", () => {
    expect(wsUrlWithToken("ws://host/ws?x=1", "abc")).toBe(
      "ws://host/ws?x=1&token=abc"
    );
  });

  it("url-encodes the token", () => {
    expect(wsUrlWithToken("ws://host/ws", "a b/c")).toContain(
      "token=a%20b%2Fc"
    );
  });
});

describe("TOOL_LABELS", () => {
  it("has a friendly label for the powershell tool", () => {
    expect(TOOL_LABELS.run_powershell).toBeTruthy();
  });
});
