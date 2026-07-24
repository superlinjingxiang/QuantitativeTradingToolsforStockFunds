import { defineStore } from "pinia";
import * as api from "../api/client";

const STORAGE_KEY = "chinaQuantVue:lastAnalysis";

export const useAnalysisStore = defineStore("analysis", {
  state: () => ({
    data: loadLastData() as Record<string, any> | null,
    loading: false,
    error: "",
    controller: null as AbortController | null,
    quoteController: null as AbortController | null,
    requestGeneration: 0,
    quoteGeneration: 0,
    quoteLoading: false,
    quoteError: "",
    quoteQuery: "",
    lastUpdatedAt: "",
    lastQuoteUpdatedAt: "",
  }),
  actions: {
    async fetch(payload: Record<string, unknown>, options: { silent?: boolean } = {}) {
      this.requestGeneration += 1;
      const generation = this.requestGeneration;
      this.controller?.abort();
      this.controller = new AbortController();
      this.loading = true;
      if (!options.silent) this.error = "";
      try {
        const result = await api.analyze(payload, this.controller.signal);
        if (generation !== this.requestGeneration) return;
        this.data = result;
        this.lastUpdatedAt = new Date().toISOString();
        localStorage.setItem(STORAGE_KEY, JSON.stringify(result));
        this.error = result.cache?.status === "STALE" ? "数据源刷新失败，已保留上一次数据" : "";
      } catch (error: any) {
        if (error?.name === "AbortError") return;
        this.error = error?.message || "请求失败";
      } finally {
        if (generation === this.requestGeneration) this.loading = false;
      }
    },
    async fetchQuote(query: string) {
      const normalized = query.trim();
      if (!normalized || (this.quoteLoading && this.quoteQuery === normalized)) return;
      this.quoteGeneration += 1;
      const generation = this.quoteGeneration;
      this.quoteController?.abort();
      this.quoteController = new AbortController();
      this.quoteLoading = true;
      this.quoteQuery = normalized;
      try {
        const result = await api.quote(normalized, this.quoteController.signal);
        if (generation !== this.quoteGeneration) return;
        this.quoteError = result.cache?.status === "STALE"
          ? "实时行情获取失败，已保留上一次报价"
          : result.quoteState?.status === "STALE"
            ? "交易时段行情延迟"
            : "";
        this.lastQuoteUpdatedAt = new Date().toISOString();
        if (!this.data) return;
        this.data = mergeQuoteResult(this.data, result);
        localStorage.setItem(STORAGE_KEY, JSON.stringify(this.data));
      } catch (error: any) {
        if (error?.name === "AbortError") return;
        this.quoteError = this.data?.quote
          ? "实时行情刷新失败，已保留上一次报价"
          : (error?.message || "实时行情刷新失败");
      } finally {
        if (generation === this.quoteGeneration) this.quoteLoading = false;
      }
    },
  },
});

function loadLastData() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    const forecast = parsed?.analysis?.forecast;
    if (forecast && !Number.isInteger(Number(forecast.horizon))) {
      localStorage.removeItem(STORAGE_KEY);
      return null;
    }
    const account = parsed?.accountAssessment;
    if (account?.connected && !("personalizedTargetWeight" in account)) {
      localStorage.removeItem(STORAGE_KEY);
      return null;
    }
    return parsed;
  } catch {
    localStorage.removeItem(STORAGE_KEY);
    return null;
  }
}

export function mergeQuoteResult(
  current: Record<string, any>,
  result: Record<string, any>,
): Record<string, any> {
  const incoming = result.quote;
  if (!incoming) return current;
  const selectedSecurityId = current.selectedSecurity?.security_id;
  if (selectedSecurityId && incoming.security_id !== selectedSecurityId) return current;
  const currentTime = Date.parse(current.quote?.source_time || "");
  const incomingTime = Date.parse(incoming.source_time || "");
  if (
    Number.isFinite(currentTime)
    && Number.isFinite(incomingTime)
    && incomingTime < currentTime
  ) {
    return current;
  }
  const chart = mergeQuoteIntoChart(current.chart, incoming);
  return {
    ...current,
    quote: incoming,
    quoteState: result.quoteState,
    quoteCache: result.cache,
    latestChangePct: result.latestChangePct,
    chart,
  };
}

function mergeQuoteIntoChart(chart: Record<string, any> | undefined, quote: Record<string, any>) {
  if (!chart || chart.interval !== "1d" || !Array.isArray(chart.points) || !chart.points.length) {
    return chart;
  }
  const points = [...chart.points];
  const sourceDate = String(quote.source_time || "").slice(0, 10);
  const last = points[points.length - 1];
  const lastDate = String(last?.time_label || last?.time || "").slice(0, 10);
  if (!sourceDate || sourceDate < lastDate) return chart;
  const point = {
    time_label: quote.source_time,
    open_price: Number(quote.open_price || quote.latest_price || 0),
    high_price: Number(quote.high_price || quote.latest_price || 0),
    low_price: Number(quote.low_price || quote.latest_price || 0),
    close_price: Number(quote.latest_price || 0),
    volume: Number(quote.volume || 0),
    amount: Number(quote.amount || 0),
    reference_price: Number(quote.previous_close || last?.close_price || 0),
  };
  if (sourceDate === lastDate) points[points.length - 1] = { ...last, ...point };
  else points.push(point);
  return { ...chart, points };
}
