import { describe, expect, it } from "vitest";
import { parseFilters, toApiFilters, writeFilters, filterQuery } from "./filters";
import type { Catalog } from "@/api/types";

const catalog = {
  periods: [{ id: "last_12m", label: "Last 12 months", date_from: "2024-01-01", date_to: "2024-12-24" }],
} as unknown as Catalog;

describe("filters <-> URL", () => {
  it("round-trips lists, the period, and the revenue mode", () => {
    const sp = new URLSearchParams("region=Asia|Europe&category=Home%20%26%20Kitchen&period=y2023&rev=net&other=1");
    const f = parseFilters(sp);
    expect(f.regions).toEqual(["Asia", "Europe"]);
    expect(f.categories).toEqual(["Home & Kitchen"]);
    expect(f.period).toBe("y2023");
    expect(f.revenue).toBe("net");
    const back = writeFilters(new URLSearchParams("other=1"), f);
    expect(parseFilters(back)).toEqual(f);
    expect(back.get("other")).toBe("1");
  });

  it("maps periods to API filters", () => {
    const base = parseFilters(new URLSearchParams(""));
    expect(toApiFilters({ ...base, period: "y2023" }, catalog)).toEqual({ years: [2023] });
    expect(toApiFilters({ ...base, period: "y2023q3" }, catalog)).toEqual({ years: [2023], quarters: [3] });
    expect(toApiFilters({ ...base, period: "last_12m" }, catalog)).toEqual({ date_from: "2024-01-01", date_to: "2024-12-24" });
    expect(toApiFilters({ ...base, period: "custom", from: "2022-02-01", to: "2022-03-31" }, catalog)).toEqual({ date_from: "2022-02-01", date_to: "2022-03-31" });
    expect(toApiFilters({ ...base, regions: ["Asia"] }, catalog)).toEqual({ regions: ["Asia"] });
  });

  it("keeps only filter parameters in links", () => {
    expect(filterQuery(new URLSearchParams("region=Asia&m=orders"))).toBe("?region=Asia");
    expect(filterQuery(new URLSearchParams("m=orders"))).toBe("");
  });

  it("drops empty values", () => {
    const f = parseFilters(new URLSearchParams("region="));
    expect(f.regions).toEqual([]);
    expect(writeFilters(new URLSearchParams(), f).toString()).toBe("");
  });
});
