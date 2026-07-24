import { describe, expect, it } from "vitest";
import { buildBacktestMarkPoints, overlaysForBacktest } from "./backtestSignals";

describe("backtest signal projection", () => {
  it("keeps the toolbar mode and signal overlay synchronized", () => {
    expect(overlaysForBacktest(["VOLUME"], true)).toEqual(["VOLUME", "SIGNALS"]);
    expect(overlaysForBacktest(["VOLUME", "SIGNALS"], true)).toEqual(["VOLUME", "SIGNALS"]);
    expect(overlaysForBacktest(["VOLUME", "SIGNALS"], false)).toEqual(["VOLUME"]);
  });

  it("aligns snake-case trade dates with ISO chart timestamps", () => {
    const points = buildBacktestMarkPoints(
      [
        { trade_date: "2026-07-16", action: "BUY", price: 2.61, label: "B", detail: "买入" },
        { trade_date: "2026-07-22", action: "SELL", price: 2.67, label: "S", detail: "卖出" },
        { trade_date: "2026-06-01", action: "BUY", price: 2.1, label: "B" },
      ],
      ["2026-07-16T15:00:00+08:00", "2026-07-22T15:00:00+08:00"],
      { buy: "red", sell: "green" },
    );

    expect(points).toHaveLength(2);
    expect(points[0].coord).toEqual(["2026-07-16T15:00:00+08:00", 2.61]);
    expect(points[0].value).toBe("B");
    expect(points[1].coord).toEqual(["2026-07-22T15:00:00+08:00", 2.67]);
    expect(points[1].itemStyle.color).toBe("green");
  });
});
