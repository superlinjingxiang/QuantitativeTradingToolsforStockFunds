const apiBase = window.quant?.apiBase ?? "http://127.0.0.1:8765";

const state = {
  query: "",
  chartBacktestActive: false,
  lastPayload: null,
  lastData: null
};

const els = {
  searchInput: document.getElementById("searchInput"),
  strategyMode: document.getElementById("strategyMode"),
  maxTrades: document.getElementById("maxTrades"),
  chartBacktestButton: document.getElementById("chartBacktestButton"),
  intervalSelect: document.getElementById("intervalSelect"),
  rangeSelect: document.getElementById("rangeSelect"),
  adjustmentSelect: document.getElementById("adjustmentSelect"),
  volumeToggle: document.getElementById("volumeToggle"),
  maToggle: document.getElementById("maToggle"),
  signalToggle: document.getElementById("signalToggle"),
  forecastToggle: document.getElementById("forecastToggle"),
  refreshButton: document.getElementById("refreshButton"),
  rerunButton: document.getElementById("rerunButton"),
  healthBanner: document.getElementById("healthBanner"),
  marketTime: document.getElementById("marketTime"),
  chartMeta: document.getElementById("chartMeta"),
  chartEmpty: document.getElementById("chartEmpty"),
  statusBar: document.getElementById("statusBar"),
  canvas: document.getElementById("priceChart"),
  marketOverview: document.getElementById("marketOverview"),
  watchlist: document.getElementById("watchlist"),
  recentList: document.getElementById("recentList"),
  strategyPanel: document.getElementById("strategyPanel"),
  forecastPanel: document.getElementById("forecastPanel"),
  operationPanel: document.getElementById("operationPanel"),
  decisionPanel: document.getElementById("decisionPanel"),
  backtestSummary: document.getElementById("backtestSummary"),
  backtestMetrics: document.getElementById("backtestMetrics"),
  backtestEvidence: document.getElementById("backtestEvidence")
};

function init() {
  bindEvents();
  resizeCanvas();
  window.addEventListener("resize", () => {
    resizeCanvas();
    drawChart(state.lastData);
  });
  setStatus("IDLE", "IDLE", "--");
  checkHealth();
}

function bindEvents() {
  els.searchInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      state.query = els.searchInput.value.trim();
      state.chartBacktestActive = false;
      els.signalToggle.checked = false;
      fetchAnalysis();
    }
  });
  [
    els.strategyMode,
    els.maxTrades,
    els.intervalSelect,
    els.rangeSelect,
    els.adjustmentSelect,
    els.volumeToggle,
    els.maToggle,
    els.forecastToggle
  ].forEach((element) => element.addEventListener("change", () => fetchAnalysis()));
  els.signalToggle.addEventListener("change", () => {
    state.chartBacktestActive = els.signalToggle.checked;
    fetchAnalysis();
  });
  els.chartBacktestButton.addEventListener("click", () => {
    state.chartBacktestActive = !state.chartBacktestActive;
    els.signalToggle.checked = state.chartBacktestActive;
    fetchAnalysis();
  });
  els.refreshButton.addEventListener("click", () => fetchAnalysis());
  els.rerunButton.addEventListener("click", () => fetchAnalysis());
}

async function checkHealth() {
  try {
    const response = await fetch(`${apiBase}/api/health`);
    const data = await response.json();
    setStatus("READY", data.provider, state.query || "--");
  } catch (error) {
    setHealth("DEGRADED", [`后端未连接：${error.message}`], true);
  }
}

function currentPayload() {
  const overlays = [];
  if (els.volumeToggle.checked) overlays.push("VOLUME");
  if (els.maToggle.checked) overlays.push("MA");
  if (els.forecastToggle.checked) overlays.push("FORECAST");
  if (state.chartBacktestActive || els.signalToggle.checked) overlays.push("SIGNALS");
  return {
    query: state.query || els.searchInput.value.trim(),
    strategyMode: els.strategyMode.value,
    maxTrades: Number.parseInt(els.maxTrades.value, 10),
    interval: els.intervalSelect.value,
    range: els.rangeSelect.value,
    adjustment: els.adjustmentSelect.value,
    overlays,
    chartBacktestActive: state.chartBacktestActive || els.signalToggle.checked
  };
}

async function fetchAnalysis() {
  const payload = currentPayload();
  if (!payload.query) {
    return;
  }
  state.lastPayload = payload;
  setStatus("FETCHING", "RUNNING", payload.query);
  els.chartBacktestButton.classList.toggle("active", payload.chartBacktestActive);
  try {
    const response = await fetch(`${apiBase}/api/analyze`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    const data = await response.json();
    if (!response.ok || data.ok === false) {
      throw new Error(data.error || "请求失败");
    }
    state.lastData = data;
    render(data);
  } catch (error) {
    setHealth("DEGRADED", [`请求失败：${error.message}`], true);
    setStatus("ERROR", "FAILED", payload.query);
  }
}

function render(data) {
  const selected = data.selectedSecurity;
  const target = selected ? selected.security_id : state.lastPayload?.query ?? "--";
  setHealth(data.dataHealth?.status ?? "HEALTHY", data.dataHealth?.issues ?? [], data.dataHealth?.block_signal);
  els.marketTime.textContent = `行情时间：${shortDateTime(data.quote?.source_time)}`;
  renderLists(data);
  renderMarketOverview(data.marketOverview);
  renderRightPanels(data);
  renderBacktest(data.backtest);
  drawChart(data);
  const chart = data.chart ?? {};
  els.chartMeta.textContent = `周期：${chart.interval ?? "--"} | 复权：${chart.adjustment ?? "--"} | 范围：${chart.range ?? "--"} | 点数：${(chart.points ?? []).length}`;
  setStatus("REALTIME_RUNNING", "COMPLETED", target);
}

function setHealth(status, issues, blocked) {
  els.healthBanner.className = "health";
  if (blocked) {
    els.healthBanner.classList.add("blocked");
  } else if (status !== "HEALTHY") {
    els.healthBanner.classList.add("degraded");
  } else {
    els.healthBanner.classList.add("healthy");
  }
  const suffix = issues && issues.length ? `（${issues[0]}）` : "";
  els.healthBanner.textContent = `数据健康：${status}${suffix}`;
}

function setStatus(runState, task, target) {
  els.statusBar.textContent = `状态：${runState} | 任务：${task} | 标的：${target}`;
}

function renderLists(data) {
  const selected = data.selectedSecurity;
  if (selected) {
    els.watchlist.innerHTML = listItem(`[默认] ${selected.symbol}`, selected.name);
    els.recentList.innerHTML = listItem(selected.symbol, selected.name);
  }
}

function listItem(title, text) {
  return `<div class="list-item"><strong>${escapeHtml(title)}</strong><br>${escapeHtml(text ?? "")}</div>`;
}

function renderMarketOverview(overview) {
  if (!overview) {
    els.marketOverview.innerHTML = "";
    return;
  }
  const rows = (overview.indices ?? [])
    .map((index) => {
      const changeClass = valueDirectionClass(index.change_pct);
      return `<div class="market-row">
        <div>${escapeHtml(index.name)}</div>
        <div class="value ${changeClass}">${escapeHtml(index.latest_value)}</div>
        <div class="change ${changeClass}">${escapeHtml(index.change_pct)}</div>
      </div>`;
    })
    .join("");
  els.marketOverview.innerHTML = `
    <div>市场状态：<span class="metric-strong warn">${escapeHtml(overview.trend_state ?? "--")}</span></div>
    <div>市场广度：${colorBreadth(overview.breadth_summary ?? "--")}</div>
    <div>成交额：<span class="metric-strong warn">${escapeHtml(overview.turnover_summary ?? "--")}</span></div>
    <div>波动：<span class="metric-strong">${escapeHtml(overview.volatility_state ?? "--")}</span></div>
    <div>数据：<span class="metric-strong ${overview.is_stale ? "warn" : "up"}">${escapeHtml(overview.data_health_text ?? "--")}</span></div>
    ${rows}`;
}

function renderRightPanels(data) {
  const strategy = data.analysis?.strategy ?? {};
  const forecast = data.analysis?.forecast ?? {};
  const operation = data.analysis?.operation ?? {};
  const decision = data.decision ?? {};
  els.strategyPanel.innerHTML = rows([
    ["模式", tag(strategy.mode_label ?? "--", "warn")],
    ["策略", strong(strategy.strategy_id ?? "--")],
    ["窗口", `${escapeHtml(strategy.horizon_label ?? "--")} / 样本 ${escapeHtml(strategy.sample_count ?? "--")}`],
    ["核心", escapeHtml(joinList(strategy.core_indicators, "、") || "--")],
    ["模型", escapeHtml(strategy.model_version ?? "--")]
  ]);
  els.forecastPanel.innerHTML = rows([
    ["方向", tag(forecast.direction_label ?? "--", directionTagClass(forecast.direction_label))],
    ["概率", escapeHtml(forecast.probability_summary ?? "--")],
    ["区间", escapeHtml(forecast.expected_return_range ?? "--")],
    ["回撤", escapeHtml(forecast.expected_drawdown ?? "--")],
    ["校准", escapeHtml(forecast.validation_metrics ?? "--")]
  ]);
  els.operationPanel.innerHTML = rows([
    ["策略建议", tag(operation.final_signal ?? "--", signalClass(operation.final_signal))],
    ["等级", `${tag(operation.grade ?? "--", operation.grade === "A" || operation.grade === "B" ? "buy" : "warn")} ${escapeHtml(operation.grade_description ?? "")}`],
    ["仓位上限", strong(operation.target_position_limit ?? "--")],
    ["不交易原因", escapeHtml(operation.abstain_reason ?? "--")],
    ["风险", escapeHtml(joinList(operation.negative_drivers, "；") || "--")]
  ]);
  els.decisionPanel.innerHTML = rows([
    ["执行状态", tag(decision.readiness ?? "--", "warn")],
    ["门禁信号", tag(decision.final_signal ?? "--", signalClass(decision.final_signal))],
    ["置信度", strong(decision.confidence ?? "--")],
    ["回测证据", escapeHtml(decision.profitability_summary ?? "--")],
    ["阻断", escapeHtml(joinList(decision.blocking_reasons, "；") || "--")]
  ]);
}

function rows(items) {
  return items.map(([label, value]) => `<div class="row"><span class="label">${label}</span><span>${value}</span></div>`).join("");
}

function tag(text, cls = "") {
  return `<span class="tag ${cls}">${escapeHtml(text)}</span>`;
}

function strong(text) {
  return `<span class="metric-strong">${escapeHtml(text)}</span>`;
}

function renderBacktest(backtest) {
  if (!backtest) {
    return;
  }
  els.backtestSummary.textContent = backtest.summary ?? "暂无回测结果";
  els.backtestMetrics.textContent = [
    `标的：${backtest.security_id ?? "--"}`,
    `期限：${backtest.horizon_label ?? "--"}`,
    `交易上限：${backtest.max_trades_per_year ?? "--"}`,
    `阈值：${backtest.selected_threshold ?? "--"}`,
    `净收益：${backtest.total_return ?? "--"}`,
    `年化：${backtest.annualized_return ?? "--"}`,
    `最大回撤：${backtest.max_drawdown ?? "--"}`,
    `相对基准：${backtest.excess_return ?? "--"}`,
    `胜率：${backtest.win_rate ?? "--"}`,
    `交易次数：${backtest.trade_count ?? "--"}`,
    `Brier：${backtest.brier_score ?? "--"}`,
    `可靠性：${backtest.reliability_grade ?? "--"}`,
    `状态：${backtest.status ?? "--"}`
  ].join("\n");
  els.backtestEvidence.textContent = [
    "交易流水：",
    ...((backtest.trades ?? []).length ? backtest.trades : ["--"]),
    "",
    "验证说明：",
    ...((backtest.notes ?? []).length ? backtest.notes : ["--"])
  ].join("\n");
}

function resizeCanvas() {
  const rect = els.canvas.parentElement.getBoundingClientRect();
  const ratio = window.devicePixelRatio || 1;
  els.canvas.width = Math.max(1, Math.floor(rect.width * ratio));
  els.canvas.height = Math.max(1, Math.floor(rect.height * ratio));
  els.canvas.style.width = `${rect.width}px`;
  els.canvas.style.height = `${rect.height}px`;
}

function drawChart(data) {
  resizeCanvas();
  const canvas = els.canvas;
  const ctx = canvas.getContext("2d");
  const ratio = window.devicePixelRatio || 1;
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  const width = canvas.width / ratio;
  const height = canvas.height / ratio;
  ctx.clearRect(0, 0, width, height);
  const points = data?.chart?.points ?? [];
  els.chartEmpty.style.display = points.length ? "none" : "flex";
  if (!points.length) return;

  const margin = { left: 76, right: 18, top: 24, bottom: 34 };
  const priceRect = {
    x: margin.left,
    y: margin.top,
    w: width - margin.left - margin.right,
    h: height * 0.55
  };
  const changeRect = { x: margin.left, y: priceRect.y + priceRect.h + 26, w: priceRect.w, h: height * 0.15 };
  const volumeRect = { x: margin.left, y: changeRect.y + changeRect.h + 24, w: priceRect.w, h: height - changeRect.y - changeRect.h - margin.bottom - 24 };

  const prices = points.flatMap((p) => [p.low_price, p.high_price]).filter((v) => Number.isFinite(v));
  let minPrice = Math.min(...prices);
  let maxPrice = Math.max(...prices);
  if (minPrice === maxPrice) {
    minPrice -= 1;
    maxPrice += 1;
  }
  const pad = (maxPrice - minPrice) * 0.05;
  minPrice -= pad;
  maxPrice += pad;

  drawGrid(ctx, priceRect, minPrice, maxPrice);
  drawPriceLine(ctx, points, priceRect, minPrice, maxPrice);
  if ((data?.chart?.overlays ?? []).includes("MA")) drawMovingAverage(ctx, points, priceRect, minPrice, maxPrice);
  if ((data?.chart?.overlays ?? []).includes("SIGNALS")) drawSignals(ctx, points, data.chart.signals ?? [], priceRect, minPrice, maxPrice);
  if ((data?.chart?.overlays ?? []).includes("VOLUME")) {
    drawChangeBars(ctx, points, changeRect);
    drawVolumeBars(ctx, points, volumeRect);
  }
  drawLatest(ctx, points, priceRect, minPrice, maxPrice);
  drawXAxis(ctx, points, volumeRect);
}

function drawGrid(ctx, rect, minPrice, maxPrice) {
  ctx.strokeStyle = "#263143";
  ctx.fillStyle = "#94a3b8";
  ctx.font = "12px Consolas";
  ctx.lineWidth = 1;
  for (let i = 0; i <= 4; i += 1) {
    const y = rect.y + (rect.h * i) / 4;
    const price = maxPrice - ((maxPrice - minPrice) * i) / 4;
    ctx.beginPath();
    ctx.moveTo(rect.x, y);
    ctx.lineTo(rect.x + rect.w, y);
    ctx.stroke();
    ctx.fillText(price.toFixed(3), rect.x - 58, y + 4);
  }
  ctx.fillText("价格", rect.x - 58, rect.y - 8);
}

function drawPriceLine(ctx, points, rect, minPrice, maxPrice) {
  ctx.strokeStyle = "#4aa3ff";
  ctx.lineWidth = 2.2;
  ctx.beginPath();
  points.forEach((point, index) => {
    const x = xAt(index, points.length, rect);
    const y = yAt(point.close_price, rect, minPrice, maxPrice);
    if (index === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();
}

function drawMovingAverage(ctx, points, rect, minPrice, maxPrice) {
  ctx.strokeStyle = "#ffd166";
  ctx.lineWidth = 1.6;
  ctx.beginPath();
  points.forEach((point, index) => {
    const start = Math.max(0, index - 4);
    const slice = points.slice(start, index + 1);
    const avg = slice.reduce((sum, item) => sum + item.close_price, 0) / slice.length;
    const x = xAt(index, points.length, rect);
    const y = yAt(avg, rect, minPrice, maxPrice);
    if (index === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();
}

function drawSignals(ctx, points, signals, rect, minPrice, maxPrice) {
  const byDate = new Map();
  signals.forEach((signal) => byDate.set(signal.trade_date, signal));
  points.forEach((point, index) => {
    const date = point.time_label.slice(0, 10);
    const signal = byDate.get(date);
    if (!signal) return;
    const x = xAt(index, points.length, rect);
    const y = yAt(signal.price, rect, minPrice, maxPrice);
    const isBuy = signal.action === "BUY";
    ctx.fillStyle = isBuy ? "#2fd66f" : "#ff4d43";
    ctx.beginPath();
    ctx.arc(x, y, 7, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = "#061015";
    ctx.font = "bold 10px Consolas";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(isBuy ? "B" : "S", x, y + 0.5);
    ctx.fillStyle = "#cbd5e1";
    ctx.font = "11px Microsoft YaHei UI";
    ctx.fillText(isBuy ? "买入" : "卖出", x, y + (isBuy ? 18 : -18));
  });
  ctx.textAlign = "left";
  ctx.textBaseline = "alphabetic";
}

function drawChangeBars(ctx, points, rect) {
  const changes = points.map((point) => {
    const base = point.reference_price || point.open_price || point.close_price;
    return base > 0 ? point.close_price / base - 1 : 0;
  });
  const maxAbs = Math.max(0.001, ...changes.map((value) => Math.abs(value)));
  const zeroY = rect.y + rect.h / 2;
  ctx.strokeStyle = "#263143";
  ctx.beginPath();
  ctx.moveTo(rect.x, zeroY);
  ctx.lineTo(rect.x + rect.w, zeroY);
  ctx.stroke();
  changes.forEach((change, index) => {
    const x = xAt(index, points.length, rect);
    const barW = Math.max(3, rect.w / points.length - 6);
    const h = (Math.abs(change) / maxAbs) * (rect.h / 2 - 4);
    ctx.fillStyle = change >= 0 ? "#ff4d43" : "#2fd66f";
    ctx.fillRect(x - barW / 2, change >= 0 ? zeroY - h : zeroY, barW, h);
    if (Math.abs(change) > 0.006) {
      ctx.fillStyle = "#b7c4d8";
      ctx.font = "10px Consolas";
      ctx.fillText(`${change >= 0 ? "+" : ""}${(change * 100).toFixed(1)}%`, x - 13, change >= 0 ? zeroY - h - 4 : zeroY + h + 12);
    }
  });
  ctx.fillStyle = "#94a3b8";
  ctx.fillText("涨跌幅", rect.x - 58, zeroY + 4);
}

function drawVolumeBars(ctx, points, rect) {
  const maxVolume = Math.max(1, ...points.map((point) => point.volume || 0));
  points.forEach((point, index) => {
    const x = xAt(index, points.length, rect);
    const previous = points[index - 1] ?? point;
    const up = point.close_price >= previous.close_price;
    const barW = Math.max(3, rect.w / points.length - 6);
    const h = ((point.volume || 0) / maxVolume) * rect.h;
    ctx.fillStyle = up ? "#ff4d43" : "#2fd66f";
    ctx.fillRect(x - barW / 2, rect.y + rect.h - h, barW, h);
  });
  ctx.fillStyle = "#94a3b8";
  ctx.font = "12px Consolas";
  ctx.fillText("成交量", rect.x - 58, rect.y + rect.h - 4);
  ctx.fillText(formatVolume(maxVolume), rect.x - 58, rect.y + 10);
}

function drawLatest(ctx, points, rect, minPrice, maxPrice) {
  const latest = points[points.length - 1];
  const previous = points[points.length - 2] ?? latest;
  const change = previous.close_price > 0 ? latest.close_price / previous.close_price - 1 : 0;
  ctx.fillStyle = change >= 0 ? "#ff4d43" : "#2fd66f";
  ctx.font = "bold 16px Microsoft YaHei UI";
  ctx.fillText(`最新 ${latest.close_price.toFixed(3)}  ${change >= 0 ? "+" : ""}${(change * 100).toFixed(2)}%`, rect.x + 70, rect.y + 18);
  ctx.fillStyle = "#94a3b8";
  ctx.font = "12px Microsoft YaHei UI";
  ctx.fillText("价格(CNY)", rect.x, rect.y + 18);
}

function drawXAxis(ctx, points, rect) {
  ctx.fillStyle = "#94a3b8";
  ctx.font = "12px Consolas";
  const indexes = [0, Math.floor(points.length / 2), points.length - 1];
  indexes.forEach((index) => {
    const x = xAt(index, points.length, rect);
    ctx.fillText(points[index].time_label.slice(0, 10), x - 36, rect.y + rect.h + 20);
  });
}

function xAt(index, count, rect) {
  if (count <= 1) return rect.x + rect.w / 2;
  return rect.x + (rect.w * index) / (count - 1);
}

function yAt(value, rect, minPrice, maxPrice) {
  return rect.y + rect.h - ((value - minPrice) / (maxPrice - minPrice)) * rect.h;
}

function valueDirectionClass(value) {
  const text = String(value ?? "");
  if (text.startsWith("-")) return "down";
  if (text.includes("+") || Number.parseFloat(text) > 0) return "up";
  return "neutral";
}

function signalClass(value) {
  if (["BUY_CANDIDATE", "ADD_CANDIDATE", "HOLD"].includes(value)) return "buy";
  if (["SELL", "REDUCE"].includes(value)) return "sell";
  if (["WATCH", "ABSTAIN"].includes(value)) return "warn";
  return "";
}

function directionTagClass(value) {
  const text = String(value ?? "");
  if (text.includes("上涨")) return "buy";
  if (text.includes("下跌")) return "sell";
  return "warn";
}

function colorBreadth(text) {
  return escapeHtml(text)
    .replace(/上涨(\d+)/, '上涨<span class="up">$1</span>')
    .replace(/下跌(\d+)/, '下跌<span class="down">$1</span>');
}

function joinList(items, delimiter) {
  return Array.isArray(items) ? items.filter(Boolean).join(delimiter) : "";
}

function shortDateTime(value) {
  if (!value) return "--";
  return String(value).replace("T", " ").slice(0, 19);
}

function formatVolume(value) {
  if (value >= 1e8) return `${(value / 1e8).toFixed(1)}B`;
  if (value >= 1e4) return `${(value / 1e4).toFixed(1)}万`;
  return String(Math.round(value));
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

init();
