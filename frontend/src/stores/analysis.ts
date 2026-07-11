import { defineStore } from "pinia";
import * as api from "../api/client";

const STORAGE_KEY = "chinaQuantVue:lastAnalysis";

export const useAnalysisStore = defineStore("analysis", {
  state: () => ({
    data: loadLastData() as Record<string, any> | null,
    loading: false,
    error: "",
    controller: null as AbortController | null,
    requestGeneration: 0,
    lastUpdatedAt: "",
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
  },
});

function loadLastData() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    localStorage.removeItem(STORAGE_KEY);
    return null;
  }
}
