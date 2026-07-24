import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as client from "./api/client";
import { mergeQuoteResult, useAnalysisStore } from "./stores/analysis";

beforeEach(() => {
  localStorage.clear();
  setActivePinia(createPinia());
  vi.restoreAllMocks();
});

describe("Vue frontend bootstrap", () => {
  it("keeps the API fallback local", async () => {
    const client = await import("./api/client");
    expect(client.apiBase).toMatch(/^https?:\/\//);
  });

  it("drops cached forecast data that predates explicit horizon metadata", () => {
    localStorage.setItem("chinaQuantVue:lastAnalysis", JSON.stringify({
      analysis: { forecast: { expected_return_range: "-12% to 9%" } },
    }));
    setActivePinia(createPinia());

    const store = useAnalysisStore();

    expect(store.data).toBeNull();
    expect(localStorage.getItem("chinaQuantVue:lastAnalysis")).toBeNull();
  });

  it("updates the current quote and today's daily point without re-running analysis", async () => {
    const store = useAnalysisStore();
    store.data = {
      selectedSecurity: { security_id: "SSE:513300" },
      quote: {
        security_id: "SSE:513300",
        latest_price: 2.567,
        source_time: "2026-07-17T15:00:00+08:00",
      },
      chart: {
        interval: "1d",
        points: [
          { time_label: "2026-07-17T15:00:00+08:00", close_price: 2.567 },
        ],
      },
    };
    vi.spyOn(client, "quote").mockResolvedValue({
      ok: true,
      quote: {
        security_id: "SSE:513300",
        latest_price: 2.564,
        previous_close: 2.567,
        open_price: 2.57,
        high_price: 2.58,
        low_price: 2.55,
        volume: 100,
        amount: 256.4,
        source_time: "2026-07-20T10:00:03+08:00",
      },
      latestChangePct: 2.564 / 2.567 - 1,
      quoteState: { status: "LIVE", label: "实时行情" },
      cache: { status: "MISS" },
    });

    await store.fetchQuote("SSE:513300");

    expect(client.quote).toHaveBeenCalledOnce();
    expect(store.data?.quote.latest_price).toBe(2.564);
    expect(store.data?.chart.points).toHaveLength(2);
    expect(store.data?.chart.points[1].close_price).toBe(2.564);
    expect(store.quoteError).toBe("");
  });

  it("rejects a quote from another security and keeps the visible value", () => {
    const current = {
      selectedSecurity: { security_id: "SSE:513300" },
      quote: { security_id: "SSE:513300", latest_price: 2.564 },
    };
    const merged = mergeQuoteResult(current, {
      quote: { security_id: "SZSE:000725", latest_price: 8.5 },
    });
    expect(merged).toBe(current);
    expect(merged.quote.latest_price).toBe(2.564);
  });
});
