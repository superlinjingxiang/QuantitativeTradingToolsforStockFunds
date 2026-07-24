import { describe, expect, it } from "vitest";
import {
  formatForecastEndpoint,
  projectTerminalRange,
} from "./forecastProjection";

describe("forecast terminal range projection", () => {
  it("keeps the starting price and lands exactly on backend p05/p50/p95 returns", () => {
    const latest = 2.556;
    const range = { p05: -0.12, p50: 0.011, p95: 0.095 };
    const projection = projectTerminalRange(latest, range, 21);

    expect(projection.lower).toHaveLength(21);
    expect(projection.lower.at(-1)).toBeCloseTo(latest * 0.88, 10);
    expect(projection.median.at(-1)).toBeCloseTo(latest * 1.011, 10);
    expect(projection.upper.at(-1)).toBeCloseTo(latest * 1.095, 10);
    expect(projection.lower[0]).toBeLessThan(latest);
    expect(projection.median[0]).toBeGreaterThan(latest);
  });

  it("labels endpoint prices as terminal quantiles rather than daily forecasts", () => {
    expect(formatForecastEndpoint("p50", 2.584116, 0.011)).toBe(
      "p50 2.584\n+1.1%",
    );
    expect(formatForecastEndpoint("p05", 2.24928, -0.12)).toBe(
      "p05 2.249\n-12.0%",
    );
  });

  it("rejects unordered quantiles", () => {
    expect(() => projectTerminalRange(
      2.556,
      { p05: 0.02, p50: -0.01, p95: 0.05 },
      21,
    )).toThrow("forecast quantiles must be ordered");
  });
});
