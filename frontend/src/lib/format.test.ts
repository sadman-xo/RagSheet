import { describe, expect, it } from "vitest";
import { byKind, compactNumber, deltaText, money, pct } from "./format";

describe("formatters", () => {
  it("formats money and compact numbers", () => {
    expect(money(5284387.7)).toBe("5,284,387.70");
    expect(compactNumber(1274657.55)).toBe("1.27M");
    expect(compactNumber(12500)).toBe("12.5K");
    expect(money(null)).toBe("–");
  });

  it("formats rates and deltas", () => {
    expect(pct(22.841)).toBe("22.84%");
    expect(byKind("pct", 27.2054)).toBe("27.21%");
    expect(deltaText("money", -14.533, -154178)).toBe("-14.5%");
    expect(deltaText("pct", null, 1.234)).toBe("+1.23 pts");
  });
});
