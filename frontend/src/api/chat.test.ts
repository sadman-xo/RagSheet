import { describe, expect, it } from "vitest";
import { SSE_OPTIONS } from "./chat";

describe("SSE client options", () => {
  it("keeps the stream open when the tab is hidden (no repeated GPU turn)", () => {
    expect(SSE_OPTIONS.openWhenHidden).toBe(true);
  });
});
