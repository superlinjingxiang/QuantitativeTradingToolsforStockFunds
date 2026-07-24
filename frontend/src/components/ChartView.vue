<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from "vue";
import * as echarts from "echarts";
import {
  formatForecastEndpoint,
  projectTerminalRange,
} from "../charts/forecastProjection";

const props = defineProps<{ data: Record<string, any> | null; overlays: string[]; theme?: string }>();
const root = ref<HTMLElement | null>(null);
const forecastPointCount = ref(0);
let chart: echarts.ECharts | null = null;

function render() {
  if (!chart) return;
  const lightTheme = props.theme === "light";
  const colors = lightTheme
    ? { text: "#cbd5e1", axis: "#475569", grid: "#263246", tooltipBg: "#111827", tooltipBorder: "#475569", tooltipText: "#f8fafc", price: "#60a5fa", forecast: "#c084fc", red: "#ff4d45", green: "#2fd66f" }
    : { text: "#8ea3bf", axis: "#334155", grid: "#263246", tooltipBg: "#151d2b", tooltipBorder: "#334155", tooltipText: "#e5edf8", price: "#4ca3ff", forecast: "#c084fc", red: "#ff4d45", green: "#2fd66f" };
  const points = props.data?.chart?.points || [];
  const labels = points.map((point: any) => point.time_label || point.time || "--");
  const closes = points.map((point: any) => Number(point.close_price ?? point.close ?? 0));
  const baseLabels = labels.slice();
  const changes = points.map((point: any, index: number) => {
    const reference = Number(point.reference_price ?? points[index - 1]?.close_price ?? 0);
    const close = closes[index];
    return reference > 0 && Number.isFinite(close) ? (close / reference - 1) * 100 : 0;
  });
  const changeBars = changes.map((change: number) => ({
    value: Number(change.toFixed(4)),
    itemStyle: { color: change >= 0 ? colors.red : colors.green },
  }));
  const volumes = points.map((point: any, index: number) => ({
    value: Number(point.volume || 0),
    itemStyle: { color: changes[index] >= 0 ? colors.red : colors.green },
  }));
  const signals = props.data?.chart?.signals || [];
  const markPoints = signals.map((signal: any) => ({
    name: signal.action || signal.signal || "信号",
    coord: [signal.time_label || signal.time || "--", Number(signal.price || signal.close_price || 0)],
    value: signal.action || signal.signal || "信号",
    itemStyle: { color: String(signal.action || signal.signal || "").toUpperCase().includes("SELL") ? colors.green : colors.red },
  }));
  const latest = closes[closes.length - 1] || 0;
  const forecast = props.data?.analysis?.forecast || {};
  const range = parseRange(forecast.expected_return_range);
  const hasForecast = props.overlays.includes("FORECAST") && latest && range;
  const forecastSteps = hasForecast ? resolveForecastSteps(forecast, props.data?.analysis?.strategy) : 0;
  forecastPointCount.value = forecastSteps;
  const forecastLabels = hasForecast ? buildForecastLabels(baseLabels[baseLabels.length - 1], forecastSteps, props.data?.chart?.interval) : [];
  const forecastProjection = hasForecast
    ? projectTerminalRange(latest, range, forecastSteps)
    : null;
  const axisLabels = hasForecast ? [...baseLabels, ...forecastLabels] : baseLabels;
  const forecastValues = hasForecast ? [...closes, ...forecastLabels.map(() => null)] : closes;
  const changeValues = hasForecast ? [...changeBars, ...forecastLabels.map(() => null)] : changeBars;
  const volumeValues = hasForecast ? [...volumes, ...forecastLabels.map(() => null)] : volumes;
  const forecastPrefix = [...baseLabels.slice(0, -1).map(() => null), latest];
  const forecastData = forecastProjection ? [...forecastPrefix, ...forecastProjection.median] : [];
  const forecastLower = forecastProjection ? [...forecastPrefix, ...forecastProjection.lower] : [];
  const forecastUpper = forecastProjection ? [...forecastPrefix, ...forecastProjection.upper] : [];
  const forecastBand = hasForecast ? forecastLower.map((lower, index) => {
    if (lower === null || forecastUpper[index] === null) return null;
    return Number(forecastUpper[index]) - Number(lower);
  }) : [];
  const lowerEndpoint = forecastProjection?.lower.at(-1) ?? latest;
  const medianEndpoint = forecastProjection?.median.at(-1) ?? latest;
  const upperEndpoint = forecastProjection?.upper.at(-1) ?? latest;
  chart.setOption({
    backgroundColor: "transparent",
    animation: false,
    tooltip: { trigger: "axis", axisPointer: { type: "cross" }, backgroundColor: colors.tooltipBg, borderColor: colors.tooltipBorder, textStyle: { color: colors.tooltipText } },
    grid: [
      { left: 58, right: hasForecast ? 112 : 22, top: 34, height: "54%", containLabel: true },
      { left: 58, right: 22, top: "61%", height: "13%", containLabel: true },
      { left: 58, right: 22, top: "78%", bottom: 42, containLabel: true },
    ],
    xAxis: [
      { type: "category", gridIndex: 0, data: axisLabels, axisLabel: { show: false }, axisLine: { lineStyle: { color: colors.axis } } },
      { type: "category", gridIndex: 1, data: axisLabels, axisLabel: { show: false }, axisLine: { lineStyle: { color: colors.axis } } },
      { type: "category", gridIndex: 2, data: axisLabels, axisLabel: { color: colors.text, hideOverlap: true, formatter: formatAxisLabel }, axisLine: { lineStyle: { color: colors.axis } } },
    ],
    yAxis: [
      { type: "value", gridIndex: 0, scale: true, name: "价格(CNY)", nameTextStyle: { color: colors.text }, axisLabel: { color: colors.text }, splitLine: { lineStyle: { color: colors.grid } } },
      { type: "value", gridIndex: 1, min: (value: { min: number; max: number }) => -Math.max(Math.abs(value.min), Math.abs(value.max), 0.01), max: (value: { min: number; max: number }) => Math.max(Math.abs(value.min), Math.abs(value.max), 0.01), name: "涨跌幅", nameTextStyle: { color: colors.text }, axisLabel: { color: colors.text, formatter: (value: number) => `${value.toFixed(1)}%` }, splitLine: { lineStyle: { color: colors.grid } } },
      { type: "value", gridIndex: 2, name: "成交量", nameTextStyle: { color: colors.text }, axisLabel: { color: colors.text, formatter: formatVolume }, splitLine: { lineStyle: { color: colors.grid } } },
    ],
    series: [
      { name: "价格", type: "line", xAxisIndex: 0, yAxisIndex: 0, data: forecastValues, smooth: false, symbol: "none", lineStyle: { color: colors.price, width: 2 }, markPoint: { data: props.overlays.includes("SIGNALS") ? markPoints : [] } },
      ...(props.overlays.includes("MA") ? [{ name: "MA", type: "line", xAxisIndex: 0, yAxisIndex: 0, data: [...movingAverage(closes, 5), ...(hasForecast ? [null] : [])], symbol: "none", lineStyle: { color: lightTheme ? "#d97706" : "#f6c453", width: 1.5 } }] : []),
      { name: "涨跌幅", type: "bar", xAxisIndex: 1, yAxisIndex: 1, data: changeValues, barMaxWidth: 14 },
      ...(props.overlays.includes("VOLUME") ? [{ name: "成交量", type: "bar", xAxisIndex: 2, yAxisIndex: 2, data: volumeValues, barMaxWidth: 14 }] : []),
      ...(forecastData.length ? [
        {
          name: "p05区间插值（非逐日预测）",
          type: "line",
          xAxisIndex: 0,
          yAxisIndex: 0,
          data: forecastLower,
          symbol: "none",
          stack: "forecast-band",
          lineStyle: { color: colors.forecast, type: "dashed", width: 1 },
          endLabel: {
            show: true,
            formatter: formatForecastEndpoint("p05", lowerEndpoint, range.p05),
            color: colors.forecast,
            fontSize: 10,
          },
        },
        { name: "终点概率区间插值", type: "line", xAxisIndex: 0, yAxisIndex: 0, data: forecastBand, symbol: "none", stack: "forecast-band", lineStyle: { color: "transparent", width: 0 }, areaStyle: { color: lightTheme ? "rgba(124,58,237,.18)" : "rgba(192,132,252,.24)" }, tooltip: { show: false } },
        {
          name: "p95区间插值（非逐日预测）",
          type: "line",
          xAxisIndex: 0,
          yAxisIndex: 0,
          data: forecastUpper,
          symbol: "none",
          lineStyle: { color: colors.forecast, type: "dashed", width: 1 },
          endLabel: {
            show: true,
            formatter: formatForecastEndpoint("p95", upperEndpoint, range.p95),
            color: colors.forecast,
            fontSize: 10,
          },
        },
        {
          name: "p50中位插值（非逐日预测）",
          type: "line",
          xAxisIndex: 0,
          yAxisIndex: 0,
          data: forecastData,
          symbol: "none",
          lineStyle: { color: colors.forecast, type: "dashed", width: 2 },
          itemStyle: { color: colors.forecast },
          endLabel: {
            show: true,
            formatter: formatForecastEndpoint("p50", medianEndpoint, range.p50),
            color: colors.forecast,
            fontSize: 10,
            fontWeight: "bold",
          },
          markLine: { symbol: ["none", "none"], lineStyle: { color: colors.forecast, type: "dotted", opacity: 0.8 }, label: { formatter: "预测起点", color: colors.forecast }, data: [{ xAxis: baseLabels[baseLabels.length - 1] }] },
        },
      ] : []),
    ],
  }, true);
}

function formatVolume(value: number) {
  if (!Number.isFinite(value)) return "--";
  if (Math.abs(value) >= 100000000) return `${(value / 100000000).toFixed(1)}亿`;
  if (Math.abs(value) >= 10000) return `${(value / 10000).toFixed(1)}万`;
  return String(Math.round(value));
}

function formatAxisLabel(value: string) {
  if (value.startsWith("预测+")) return value;
  const match = value.match(/(\d{4})-(\d{2})-(\d{2})/);
  return match ? `${match[2]}-${match[3]}` : value;
}

function resolveForecastSteps(forecast: Record<string, any>, strategy: Record<string, any> = {}) {
  const candidates = [
    Number(forecast.horizon),
    Number(String(strategy.horizon_label || "").match(/\d+/)?.[0]),
    Number(String(forecast.model_version || "").match(/\d+/)?.[0]),
  ];
  const steps = candidates.find((value) => Number.isFinite(value) && value >= 1) || 10;
  return Math.min(Math.max(Math.round(steps), 1), 252);
}

function buildForecastLabels(lastLabel: string, steps: number, interval: string) {
  const labels: string[] = [];
  const lastDate = new Date(lastLabel);
  if (Number.isNaN(lastDate.getTime())) {
    return Array.from({ length: steps }, (_value, index) => `预测+${index + 1}`);
  }
  let cursor = lastDate;
  for (let index = 0; index < steps; index += 1) {
    if (interval === "1w") {
      cursor = new Date(cursor.getTime() + 7 * 24 * 60 * 60 * 1000);
    } else if (interval === "30m" || interval === "60m") {
      const minutes = interval === "30m" ? 30 : 60;
      cursor = new Date(cursor.getTime() + minutes * 60 * 1000);
    } else {
      cursor = nextBusinessDay(cursor);
    }
    labels.push(`预测+${index + 1} ${cursor.toISOString().slice(0, 10)}`);
  }
  return labels;
}

function nextBusinessDay(value: Date) {
  const next = new Date(value.getTime() + 24 * 60 * 60 * 1000);
  while (next.getUTCDay() === 0 || next.getUTCDay() === 6) {
    next.setUTCDate(next.getUTCDate() + 1);
  }
  return next;
}

function movingAverage(values: number[], window: number) {
  return values.map((_value, index) => index + 1 < window ? null : values.slice(index - window + 1, index + 1).reduce((sum, value) => sum + value, 0) / window);
}

function parseRange(value: string) {
  if (!value) return null;
  const matches = value.match(/(-?\d+(?:\.\d+)?)%\s*(?:to|至)\s*(-?\d+(?:\.\d+)?)%/i);
  const p50 = value.match(/p50\s*(-?\d+(?:\.\d+)?)%/i);
  if (!matches || !p50) return null;
  return { p05: Number(matches[1]) / 100, p95: Number(matches[2]) / 100, p50: Number(p50[1]) / 100 };
}

onMounted(() => {
  if (root.value) chart = echarts.init(root.value);
  render();
  window.addEventListener("resize", resize);
});
watch(() => [props.data, props.overlays, props.theme], render, { deep: true });
function resize() { chart?.resize(); }
onBeforeUnmount(() => { window.removeEventListener("resize", resize); chart?.dispose(); chart = null; });
</script>

<template>
  <div ref="root" class="chart-canvas" data-chart-layers="price,change,volume" :data-forecast-points="forecastPointCount"></div>
  <div v-if="forecastPointCount" class="forecast-interpretation">
    第{{ forecastPointCount }}个交易日终点区间 · 虚线仅为插值，非逐日预测
  </div>
</template>
