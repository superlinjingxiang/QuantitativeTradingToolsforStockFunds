const apiBase = window.quant?.apiBase ?? "http://127.0.0.1:8765";

const state = {
  query: "",
  chartBacktestActive: false,
  activeTab: "market",
  autoRefreshTimer: null,
  autoRefreshMs: 15000,
  isFetching: false,
  isFetchingRecommendations: false,
  pendingFetch: false,
  lastRefreshAt: null,
  lastPayload: null,
  lastData: null,
  recommendations: null,
  accountPanelOpen: false
};

const els = {
  searchInput: document.getElementById("searchInput"),
  strategyMode: document.getElementById("strategyMode"),
  maxTrades: document.getElementById("maxTrades"),
  themeMode: document.getElementById("themeMode"),
  autoRefreshMode: document.getElementById("autoRefreshMode"),
  accountToggleButton: document.getElementById("accountToggleButton"),
  accountPanel: document.getElementById("accountPanel"),
  accountCapitalInput: document.getElementById("accountCapitalInput"),
  accountCashInput: document.getElementById("accountCashInput"),
  accountQuantityInput: document.getElementById("accountQuantityInput"),
  accountCostInput: document.getElementById("accountCostInput"),
  accountRiskInput: document.getElementById("accountRiskInput"),
  accountSaveButton: document.getElementById("accountSaveButton"),
  accountClearButton: document.getElementById("accountClearButton"),
  accountInlineSummary: document.getElementById("accountInlineSummary"),
  chartBacktestButton: document.getElementById("chartBacktestButton"),
  intervalSelect: document.getElementById("intervalSelect"),
  rangeSelect: document.getElementById("rangeSelect"),
  adjustmentSelect: document.getElementById("adjustmentSelect"),
  volumeToggle: document.getElementById("volumeToggle"),
  maToggle: document.getElementById("maToggle"),
  signalToggle: document.getElementById("signalToggle"),
  forecastToggle: document.getElementById("forecastToggle"),
  refreshButton: document.getElementById("refreshButton"),
  addWatchButton: document.getElementById("addWatchButton"),
  clearWatchButton: document.getElementById("clearWatchButton"),
  rerunButton: document.getElementById("rerunButton"),
  recommendationPanel: document.getElementById("recommendationPanel"),
  recommendationLimit: document.getElementById("recommendationLimit"),
  recommendationIncludeUs: document.getElementById("recommendationIncludeUs"),
  refreshRecommendationsButton: document.getElementById("refreshRecommendationsButton"),
  recommendationSummary: document.getElementById("recommendationSummary"),
  recommendationTable: document.getElementById("recommendationTable"),
  recommendationDetail: document.getElementById("recommendationDetail"),
  recommendationFailures: document.getElementById("recommendationFailures"),
  healthBanner: document.getElementById("healthBanner"),
  marketTime: document.getElementById("marketTime"),
  assetTitle: document.getElementById("assetTitle"),
  assetSubtitle: document.getElementById("assetSubtitle"),
  kpiPrice: document.getElementById("kpiPrice"),
  kpiChange: document.getElementById("kpiChange"),
  kpiSignal: document.getElementById("kpiSignal"),
  kpiSignalMeta: document.getElementById("kpiSignalMeta"),
  kpiReturn: document.getElementById("kpiReturn"),
  kpiReturnMeta: document.getElementById("kpiReturnMeta"),
  kpiBacktest: document.getElementById("kpiBacktest"),
  kpiBacktestMeta: document.getElementById("kpiBacktestMeta"),
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
  navItems: [...document.querySelectorAll(".nav-item")],
  tabs: [...document.querySelectorAll(".tab")],
  dockTitle: document.getElementById("dockTitle"),
  backtestSummary: document.getElementById("backtestSummary"),
  backtestMetrics: document.getElementById("backtestMetrics"),
  backtestEvidence: document.getElementById("backtestEvidence")
};

function init() {
  bindEvents();
  initTheme();
  renderInitialState();
  resizeCanvas();
  window.addEventListener("resize", () => {
    resizeCanvas();
    drawChart(state.lastData);
  });
  setStatus("IDLE", "IDLE", "--");
  checkHealth();
  configureAutoRefresh();
  els.searchInput.focus();
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
  [els.strategyMode, els.maxTrades, els.intervalSelect, els.rangeSelect, els.adjustmentSelect].forEach((element) =>
    element.addEventListener("change", () => fetchAnalysis())
  );
  [els.volumeToggle, els.maToggle, els.forecastToggle].forEach((element) =>
    element.addEventListener("change", applyDisplayOnlyChange)
  );
  els.themeMode.addEventListener("change", () => applyTheme(els.themeMode.value));
  els.autoRefreshMode.addEventListener("change", configureAutoRefresh);
  els.accountToggleButton.addEventListener("click", toggleAccountPanel);
  els.accountSaveButton.addEventListener("click", saveAccountContext);
  els.accountClearButton.addEventListener("click", clearAccountContext);
  [els.accountCapitalInput, els.accountCashInput, els.accountQuantityInput, els.accountCostInput, els.accountRiskInput].forEach(
    (element) => element.addEventListener("change", renderAccountInlinePreview)
  );
  els.signalToggle.addEventListener("change", () => {
    state.chartBacktestActive = els.signalToggle.checked;
    renderPendingUi(currentPayload(), { instantOnly: !state.chartBacktestActive });
    if (!state.chartBacktestActive) {
      applyDisplayOnlyChange();
      return;
    }
    fetchAnalysis();
  });
  els.chartBacktestButton.addEventListener("click", () => {
    state.chartBacktestActive = !state.chartBacktestActive;
    els.signalToggle.checked = state.chartBacktestActive;
    renderPendingUi(currentPayload(), { instantOnly: !state.chartBacktestActive });
    if (!state.chartBacktestActive) {
      applyDisplayOnlyChange();
      return;
    }
    fetchAnalysis();
  });
  els.refreshButton.addEventListener("click", () => fetchAnalysis());
  els.addWatchButton.addEventListener("click", addCurrentToWatchlist);
  els.clearWatchButton.addEventListener("click", () => {
    els.watchlist.innerHTML = "";
  });
  els.rerunButton.addEventListener("click", () => fetchAnalysis());
  els.refreshRecommendationsButton.addEventListener("click", () => fetchRecommendations());
  [els.recommendationLimit, els.recommendationIncludeUs].forEach((element) =>
    element.addEventListener("change", () => {
      if (state.activeTab === "recommendations") fetchRecommendations();
    })
  );
  els.tabs.forEach((tab) => {
    tab.addEventListener("click", () => setActiveTab(tab.dataset.tab));
  });
  els.navItems.forEach((item) => {
    item.addEventListener("click", () => setActiveTab(item.dataset.tabTarget));
  });
  window.addEventListener("beforeunload", () => {
    if (state.autoRefreshTimer) window.clearInterval(state.autoRefreshTimer);
  });
}

function renderInitialState() {
  els.strategyPanel.innerHTML = rows([
    ["模式", tag("等待输入", "warn")],
    ["策略", strong("--")],
    ["窗口", "--"],
    ["核心", "输入代码后加载短线/长线策略参数"],
    ["模型", "--"]
  ]);
  els.forecastPanel.innerHTML = rows([
    ["方向", tag("--", "warn")],
    ["概率", "--"],
    ["区间", "--"],
    ["回撤", "--"],
    ["校准", "--"]
  ]);
  els.operationPanel.innerHTML = rows([
    ["策略建议", tag("--", "warn")],
    ["等级", "N · 尚未计算"],
    ["仓位上限", "--"],
    ["不交易原因", "尚未选择标的"],
    ["风险", "--"]
  ]);
  els.decisionPanel.innerHTML = rows([
    ["执行状态", tag("仅研究观察", "warn")],
    ["门禁信号", tag("--", "warn")],
    ["置信度", "--"],
    ["回测证据", "--"],
    ["阻断", "等待行情与回测证据"]
  ]);
  els.backtestSummary.textContent = "输入股票、ETF 或基金代码后，这里会展示策略收益、最大回撤和交易次数。";
  els.backtestMetrics.textContent = "指标等待计算。";
  els.backtestEvidence.textContent = "交易流水等待生成。";
  renderAccountInlinePreview();
  renderRecommendations(null);
  updateDockForTab();
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
    chartBacktestActive: state.chartBacktestActive || els.signalToggle.checked,
    accountContext: readAccountContextForPayload()
  };
}

function applyDisplayOnlyChange() {
  const payload = currentPayload();
  state.lastPayload = payload;
  syncBacktestButton(payload);
  if (!state.lastData) {
    fetchAnalysis();
    return;
  }
  drawChart(state.lastData);
  const chart = state.lastData.chart ?? {};
  els.chartMeta.textContent = `周期：${chart.interval ?? "--"} | 复权：${chart.adjustment ?? "--"} | 范围：${chart.range ?? "--"} | 点数：${(chart.points ?? []).length}`;
  const target = state.lastData.selectedSecurity?.security_id ?? payload.query ?? "--";
  setStatus("VIEW_UPDATED", autoRefreshLabel(), target);
}

function renderPendingUi(payload, options = {}) {
  state.lastPayload = payload;
  syncBacktestButton(payload);
  document.body.classList.toggle("is-loading", !options.instantOnly);
  const target = payload.query || state.lastData?.selectedSecurity?.security_id || "--";
  setStatus(options.auto ? "AUTO_REFRESHING" : "FETCHING", "RUNNING", target);
  if (state.lastData) {
    drawChart(state.lastData);
  }
}

function syncBacktestButton(payload = currentPayload()) {
  const active = Boolean(payload.chartBacktestActive);
  els.chartBacktestButton.classList.toggle("active", active);
  els.chartBacktestButton.textContent = active ? "正常显示" : "回测曲线";
}

function configureAutoRefresh() {
  if (state.autoRefreshTimer) {
    window.clearInterval(state.autoRefreshTimer);
    state.autoRefreshTimer = null;
  }
  state.autoRefreshMs = Number.parseInt(els.autoRefreshMode.value, 10) || 0;
  if (state.autoRefreshMs <= 0) {
    const target = state.lastData?.selectedSecurity?.security_id ?? state.query ?? "--";
    setStatus("AUTO_REFRESH_OFF", "IDLE", target);
    return;
  }
  state.autoRefreshTimer = window.setInterval(() => {
    const query = state.query || els.searchInput.value.trim();
    if (!query || document.hidden) return;
    fetchAnalysis({ auto: true });
  }, state.autoRefreshMs);
}

async function fetchAnalysis(options = {}) {
  const payload = currentPayload();
  if (!payload.query) {
    return;
  }
  if (state.isFetching) {
    if (!options.auto) {
      state.pendingFetch = true;
      renderPendingUi(payload, options);
    }
    return;
  }
  state.isFetching = true;
  renderPendingUi(payload, options);
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
    state.lastRefreshAt = new Date();
    render(data);
  } catch (error) {
    if (state.lastData) {
      setHealth("DEGRADED", [`刷新失败，已保留上一次数据：${error.message}`], false);
      const target = state.lastData.selectedSecurity?.security_id ?? payload.query;
      setStatus(options.auto ? "AUTO_REFRESH_FAILED" : "ERROR_KEEP_LAST", "RETRYING", target);
      return;
    }
    setHealth("DEGRADED", [`请求失败：${error.message}`], true);
    setStatus("ERROR", "FAILED", payload.query);
  } finally {
    state.isFetching = false;
    document.body.classList.remove("is-loading");
    if (state.pendingFetch) {
      state.pendingFetch = false;
      window.setTimeout(() => fetchAnalysis({ queued: true }), 0);
    }
  }
}

async function fetchRecommendations() {
  if (state.isFetchingRecommendations) return;
  state.isFetchingRecommendations = true;
  els.refreshRecommendationsButton.textContent = "正在刷新";
  els.refreshRecommendationsButton.disabled = true;
  setStatus("RECOMMENDATION_REFRESH", "RUNNING", "候选池");
  try {
    const response = await fetch(`${apiBase}/api/recommendations`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        limit: Number.parseInt(els.recommendationLimit.value, 10),
        horizonDays: els.strategyMode.value === "long_term" ? 21 : 10,
        includeUsLinked: els.recommendationIncludeUs.checked
      })
    });
    const data = await response.json();
    if (!response.ok || data.ok === false) {
      throw new Error(data.error || "荐股池刷新失败");
    }
    state.recommendations = data;
    renderRecommendations(data);
    updateDockForTab();
    const health = data.dataHealth ?? {};
    setHealth(health.status ?? "HEALTHY", health.issues ?? [], health.block_signal);
    setStatus("RECOMMENDATION_READY", `${data.evaluatedCount ?? 0} evaluated`, "候选池");
  } catch (error) {
    if (state.recommendations) {
      setHealth("DEGRADED", [`荐股池刷新失败，保留上一次结果：${error.message}`], false);
      setStatus("RECOMMENDATION_FAILED_KEEP_LAST", "IDLE", "候选池");
      return;
    }
    els.recommendationSummary.innerHTML = `<div class="summary-card"><span>刷新失败</span><strong class="down">${escapeHtml(error.message)}</strong></div>`;
    setHealth("DEGRADED", [`荐股池刷新失败：${error.message}`], true);
    setStatus("RECOMMENDATION_ERROR", "FAILED", "候选池");
  } finally {
    state.isFetchingRecommendations = false;
    els.refreshRecommendationsButton.textContent = "刷新荐股池";
    els.refreshRecommendationsButton.disabled = false;
  }
}

function render(data) {
  const selected = data.selectedSecurity;
  const target = selected ? selected.security_id : state.lastPayload?.query ?? "--";
  setHealth(data.dataHealth?.status ?? "HEALTHY", data.dataHealth?.issues ?? [], data.dataHealth?.block_signal);
  els.marketTime.textContent = `行情时间：${shortDateTime(data.quote?.source_time)}`;
  renderLists(data);
  loadAccountContextIntoForm(data);
  renderMarketOverview(data.marketOverview);
  renderDashboardSummary(data);
  renderRightPanels(data);
  updateDockForTab();
  drawChart(data);
  const chart = data.chart ?? {};
  els.chartMeta.textContent = `周期：${chart.interval ?? "--"} | 复权：${chart.adjustment ?? "--"} | 范围：${chart.range ?? "--"} | 点数：${(chart.points ?? []).length}`;
  const refreshText = state.lastRefreshAt ? `刷新：${state.lastRefreshAt.toLocaleTimeString("zh-CN", { hour12: false })}` : "刷新：--";
  setStatus("REALTIME_RUNNING", `${refreshText} / ${autoRefreshLabel()}`, target);
}

function renderRecommendations(data) {
  if (!data) {
    els.recommendationSummary.innerHTML = [
      summaryCard("候选数", "--", "等待刷新"),
      summaryCard("强候选", "--", "按六维评分"),
      summaryCard("观察候选", "--", "需人工复核"),
      summaryCard("数据状态", "--", "尚未加载")
    ].join("");
    els.recommendationTable.innerHTML = `<tr><td colspan="8">点击“刷新荐股池”后生成候选列表。</td></tr>`;
    els.recommendationDetail.textContent = "选择一只候选标的查看六维评分和风险备注。";
    els.recommendationFailures.textContent = "暂无。";
    return;
  }
  const summary = data.summary ?? {};
  els.recommendationSummary.innerHTML = [
    summaryCard("候选数", String(summary.candidateCount ?? 0), `评估 ${data.evaluatedCount ?? 0}/${data.universeCount ?? 0}`),
    summaryCard("强候选", String(summary.strongCount ?? 0), "85分以上降级后仍通过"),
    summaryCard("观察候选", String(summary.observeCount ?? 0), "70分以上或强候选降级"),
    summaryCard("市场环境", data.marketState ?? "--", shortDateTime(data.asOf))
  ].join("");

  const candidates = [...(data.candidates ?? [])].sort(
    (left, right) =>
      Number(right.totalScore ?? right.total_score ?? 0) -
        Number(left.totalScore ?? left.total_score ?? 0) ||
      String(left.symbol ?? "").localeCompare(String(right.symbol ?? ""))
  );
  els.recommendationTable.innerHTML = candidates.length
    ? candidates.map((item, index) => recommendationRow(item, index)).join("")
    : `<tr><td colspan="8">没有通过可展示等级的候选。请稍后刷新或检查数据源。</td></tr>`;
  [...els.recommendationTable.querySelectorAll("tr[data-index]")].forEach((row) => {
    row.addEventListener("click", () => {
      const item = candidates[Number.parseInt(row.dataset.index, 10)];
      openRecommendationCandidate(item);
    });
    row.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" && event.key !== " ") return;
      event.preventDefault();
      const item = candidates[Number.parseInt(row.dataset.index, 10)];
      openRecommendationCandidate(item);
    });
  });
  els.recommendationFailures.textContent = (data.failures ?? []).length
    ? (data.failures ?? [])
        .map((item) => `${item.symbol ?? item.securityId} ${item.name ?? ""}：${item.reason}`)
        .join("\n")
    : "无取数失败。事件类风控仍需人工复核。";
  renderRecommendationDetail(candidates[0]);
}

function summaryCard(label, value, meta) {
  return `<div class="summary-card"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong><small>${escapeHtml(meta ?? "")}</small></div>`;
}

function recommendationRow(item, index) {
  const gradeClass = item.gradeClass ?? "weak";
  const trading = item.tradingSystem ?? {};
  const tradingClass = trading.isT0 ? "t0" : "t1";
  const title = `打开 ${item.symbol} ${item.name} 的行情曲线`;
  return `<tr data-index="${index}" tabindex="0" title="${escapeHtml(title)}">
    <td><div class="symbol">${escapeHtml(item.symbol)} ${escapeHtml(item.name)}</div><div class="sub">${escapeHtml(item.securityId)} · ${escapeHtml(item.bucket)}</div></td>
    <td><span class="grade-pill ${escapeHtml(gradeClass)}">${escapeHtml(item.grade)}</span></td>
    <td><strong>${escapeHtml(item.totalScore)}</strong></td>
    <td><span class="trade-pill ${tradingClass}">${escapeHtml(trading.label ?? "--")}</span><div class="sub">${escapeHtml(trading.isT0 ? "可日内" : "非日内")}</div></td>
    <td>${escapeHtml(item.coreLogic)}</td>
    <td>${escapeHtml(item.buyTrigger)}</td>
    <td>${escapeHtml(item.stopLoss)}<br>${escapeHtml(item.takeProfit)}</td>
    <td>${escapeHtml(item.maxPosition)}</td>
  </tr>`;
}

function openRecommendationCandidate(item) {
  if (!item) return;
  renderRecommendationDetail(item);
  const target = item.securityId || item.symbol;
  els.searchInput.value = target;
  state.query = target;
  state.chartBacktestActive = false;
  els.signalToggle.checked = false;
  setActiveTab("market", { skipRecommendationFetch: true });
  setStatus("OPEN_RECOMMENDATION", "LOADING_CHART", target);
  window.requestAnimationFrame(() => {
    const chartShell = document.querySelector(".chart-shell");
    chartShell?.scrollIntoView({ behavior: "smooth", block: "start" });
  });
  fetchAnalysis();
}

function renderRecommendationDetail(item) {
  if (!item) {
    els.recommendationDetail.textContent = "暂无候选详情。";
    return;
  }
  const components = item.components ?? {};
  const reasons = item.componentReasons ?? {};
  const trading = item.tradingSystem ?? {};
  els.recommendationDetail.textContent = [
    `${item.symbol} ${item.name}｜${item.grade}｜总分 ${item.totalScore}`,
    `交易制度：${trading.label ?? "--"}｜${trading.detail ?? "需人工确认。"}`,
    "",
    "六维评分：",
    `- 市场环境：${components.market_environment ?? "--"}｜${reasons.market_environment ?? "--"}`,
    `- 板块主线：${components.sector_theme ?? "--"}｜${reasons.sector_theme ?? "--"}`,
    `- 资金强度：${components.capital_strength ?? "--"}｜${reasons.capital_strength ?? "--"}`,
    `- 趋势形态：${components.trend_pattern ?? "--"}｜${reasons.trend_pattern ?? "--"}`,
    `- 相对强度：${components.relative_strength ?? "--"}｜${reasons.relative_strength ?? "--"}`,
    `- 可退出性：${components.exit_risk ?? "--"}｜${reasons.exit_risk ?? "--"}`,
    "",
    `买入触发：${item.buyTrigger}`,
    `止损：${item.stopLoss}`,
    `止盈：${item.takeProfit}`,
    `最大仓位：${item.maxPosition}`,
    "",
    "风险备注：",
    ...((item.riskNotes ?? []).length ? item.riskNotes.map((note) => `- ${note}`) : ["- --"]),
    "",
    "硬过滤：",
    ...((item.hardFilters ?? []).length ? item.hardFilters.map((note) => `- ${note}`) : ["- --"])
  ].join("\n");
}

function renderDashboardSummary(data) {
  const selected = data.selectedSecurity;
  const chartPoints = data.chart?.points ?? [];
  const latest = chartPoints[chartPoints.length - 1];
  const previous = chartPoints[chartPoints.length - 2] ?? latest;
  const forecast = data.analysis?.forecast ?? {};
  const operation = data.analysis?.operation ?? {};
  const strategy = data.analysis?.strategy ?? {};
  const backtest = data.backtest ?? {};

  setText(els.assetTitle, selected ? `${selected.symbol} ${selected.name}` : "量化策略工作台");
  setText(
    els.assetSubtitle,
    selected
      ? `${selected.security_id ?? selected.symbol} · ${strategy.mode_label ?? "策略待计算"} · ${strategy.horizon_label ?? "--"}`
      : "输入代码后回车，加载行情、策略预测与回测证据。"
  );

  if (latest) {
    const change = previous?.close_price > 0 ? latest.close_price / previous.close_price - 1 : 0;
    const changeClass = change >= 0 ? "up" : "down";
    setText(els.kpiPrice, latest.close_price.toFixed(3));
    setClassText(
      els.kpiChange,
      `${change >= 0 ? "+" : ""}${(change * 100).toFixed(2)}% · ${shortDateTime(latest.time_label)}`,
      changeClass
    );
  } else {
    setText(els.kpiPrice, "--");
    setClassText(els.kpiChange, "等待行情", "neutral");
  }

  setClassText(els.kpiSignal, signalLabel(operation.final_signal), signalTextClass(operation.final_signal));
  setText(els.kpiSignalMeta, `${operation.grade ? `等级 ${operation.grade}` : "等级 --"} · 仓位上限 ${operation.target_position_limit ?? "--"}`);
  setText(els.kpiReturn, forecast.expected_return_range ?? "--");
  setText(els.kpiReturnMeta, `${forecast.probability_summary ?? "概率 --"} · 回撤 ${forecast.expected_drawdown ?? "--"}`);
  setText(els.kpiBacktest, backtest.total_return ?? "--");
  setText(
    els.kpiBacktestMeta,
    `${backtest.status ?? "等待验证"} · 交易 ${backtest.trade_count ?? "--"} · 胜率 ${backtest.win_rate ?? "--"}`
  );
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

function addCurrentToWatchlist() {
  const selected = state.lastData?.selectedSecurity;
  const query = state.query || els.searchInput.value.trim();
  if (selected) {
    els.watchlist.innerHTML = listItem(`[默认] ${selected.symbol}`, selected.name);
  } else if (query) {
    els.watchlist.innerHTML = listItem(query, "等待加载行情");
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
  const account = data.accountAssessment ?? {};
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
    ["策略建议", tag(signalLabel(operation.final_signal), signalClass(operation.final_signal))],
    ["等级", `${tag(operation.grade ?? "--", operation.grade === "A" || operation.grade === "B" ? "buy" : "warn")} ${escapeHtml(operation.grade_description ?? "")}`],
    ["仓位上限", strong(operation.target_position_limit ?? "--")],
    ["账户建议", tag(account.accountAdvice ?? "未录入", accountTagClass(account.accountAdvice))],
    ["建议金额", strong(account.suggestedAmount ?? "--")],
    ["建议份额", escapeHtml(account.suggestedQuantity ?? "--")],
    ["不交易原因", escapeHtml(operation.abstain_reason ?? "--")],
    ["账户原因", escapeHtml(account.reason ?? "--")],
    ["风险", escapeHtml(joinList(operation.negative_drivers, "；") || "--")]
  ]);
  els.decisionPanel.innerHTML = rows([
    ["执行状态", tag(readinessLabel(decision.readiness), readinessClass(decision.readiness))],
    ["门禁信号", tag(signalLabel(decision.final_signal), signalClass(decision.final_signal))],
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

function setActiveTab(tab, options = {}) {
  if (!tab) return;
  state.activeTab = tab;
  els.tabs.forEach((item) => item.classList.toggle("active", item.dataset.tab === tab));
  els.navItems.forEach((item) => item.classList.toggle("active", item.dataset.tabTarget === tab));
  els.recommendationPanel.classList.toggle("active", tab === "recommendations");
  updateDockForTab();
  if (tab === "recommendations" && !state.recommendations && !options.skipRecommendationFetch) {
    fetchRecommendations();
  }
}

function updateDockForTab() {
  const data = state.lastData;
  const tab = state.activeTab;
  const titles = {
    market: "市场总览",
    recommendations: "短线荐股候选池",
    strategy: "策略验证",
    backtest: "盈利验证回测",
    paper: "模拟账户",
    risk: "风险雷达",
    knowledge: "知识中心"
  };
  setText(els.dockTitle, titles[tab] ?? "市场总览");
  els.rerunButton.style.display = tab === "backtest" || tab === "strategy" ? "" : "none";
  if (tab === "market") renderMarketDock(data);
  else if (tab === "recommendations") renderRecommendationDock(state.recommendations);
  else if (tab === "strategy") renderStrategyDock(data);
  else if (tab === "backtest") renderBacktestDock(data?.backtest);
  else if (tab === "paper") renderPaperDock();
  else if (tab === "risk") renderRiskDock(data);
  else renderKnowledgeDock();
}

function renderRecommendationDock(report) {
  if (!report) {
    els.backtestSummary.textContent = "荐股池等待刷新。点击上方“刷新荐股池”生成短线候选。";
    els.backtestMetrics.textContent = "评分维度：市场环境15、板块主线20、资金强度20、趋势形态15、相对强度15、风险可退出性15。";
    els.backtestEvidence.textContent = "输出是候选池和研究建议，不是真实下单指令。新闻、解禁、减持、财务异常暂未接入，需人工复核。";
    return;
  }
  const summary = report.summary ?? {};
  els.backtestSummary.textContent = [
    `候选数：${summary.candidateCount ?? 0}`,
    `强候选：${summary.strongCount ?? 0}`,
    `观察候选：${summary.observeCount ?? 0}`,
    `市场：${report.marketState ?? "--"}`
  ].join("\n");
  els.backtestMetrics.textContent = (report.candidates ?? [])
    .slice(0, 8)
    .map((item, index) => `${index + 1}. ${item.symbol} ${item.name}｜${item.grade}｜${item.totalScore}分｜仓位${item.maxPosition}`)
    .join("\n") || "暂无候选。";
  els.backtestEvidence.textContent = [
    "机制说明：",
    report.method?.gradeRule ?? "--",
    report.method?.riskDisclosure ?? "--",
    "",
    "失败标的：",
    ...((report.failures ?? []).length
      ? report.failures.map((item) => `${item.symbol ?? item.securityId}：${item.reason}`)
      : ["无。"])
  ].join("\n");
}

function renderMarketDock(data) {
  const selected = data?.selectedSecurity;
  const overview = data?.marketOverview;
  els.backtestSummary.textContent = selected
    ? `当前标的：${selected.security_id ?? selected.symbol}\n名称：${selected.name ?? "--"}`
    : "输入代码并回车后，市场模块会同步当前标的、自选和最近访问。";
  els.backtestMetrics.textContent = overview
    ? [
        `市场状态：${overview.trend_state ?? "--"}`,
        `市场广度：${overview.breadth_summary ?? "--"}`,
        `成交额：${overview.turnover_summary ?? "--"}`,
        `波动：${overview.volatility_state ?? "--"}`,
        `数据：${overview.data_health_text ?? "--"}`
      ].join("\n")
    : "市场指数等待加载。";
  els.backtestEvidence.textContent = "可用操作：\n- 输入代码后回车搜索。\n- 切换周期、范围、复权后自动刷新。\n- 刷新按钮重新拉取当前标的。";
}

function renderStrategyDock(data) {
  const strategy = data?.analysis?.strategy ?? {};
  const forecast = data?.analysis?.forecast ?? {};
  const operation = data?.analysis?.operation ?? {};
  els.backtestSummary.textContent = [
    `策略：${strategy.strategy_id ?? "--"}`,
    `模式：${strategy.mode_label ?? "--"}`,
    `窗口：${strategy.horizon_label ?? "--"}`,
    `样本：${strategy.sample_count ?? "--"}`
  ].join("\n");
  els.backtestMetrics.textContent = [
    `方向：${forecast.direction_label ?? "--"}`,
    `概率：${forecast.probability_summary ?? "--"}`,
    `收益区间：${forecast.expected_return_range ?? "--"}`,
    `预期回撤：${forecast.expected_drawdown ?? "--"}`
  ].join("\n");
  els.backtestEvidence.textContent = [
    `策略建议：${signalLabel(operation.final_signal)}`,
    `等级：${operation.grade ?? "--"} ${operation.grade_description ?? ""}`,
    `仓位上限：${operation.target_position_limit ?? "--"}`,
    `不交易原因：${operation.abstain_reason ?? "--"}`,
    `风险：${joinList(operation.negative_drivers, "；") || "--"}`
  ].join("\n");
}

function renderBacktestDock(backtest) {
  if (!backtest) {
    els.backtestSummary.textContent = "暂无回测结果。";
    els.backtestMetrics.textContent = "--";
    els.backtestEvidence.textContent = "--";
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

function renderPaperDock() {
  const account = state.lastData?.accountAssessment ?? {};
  if (!account.connected) {
    els.backtestSummary.textContent = account.summary ?? "尚未录入账户数据。点击“账户输入”填写计划资金、成本价和持仓数量。";
    els.backtestMetrics.textContent = "需要填写：\n- 计划总资金\n- 当前持仓数量\n- 成本价\n- 可用现金（可选）\n- 风险偏好";
    els.backtestEvidence.textContent = "当前状态：手动账户未录入。\n说明：本模块只做研究级仓位评估，不读取券商账户，不执行真实下单。";
    return;
  }
  els.backtestSummary.textContent = [
    account.summary,
    `账户建议：${account.accountAdvice ?? "--"}`,
    `建议金额：${account.suggestedAmount ?? "--"}`,
    `建议份额：${account.suggestedQuantity ?? "--"}`
  ].join("\n");
  els.backtestMetrics.textContent = [
    `计划总资金：${account.plannedCapital ?? "--"}`,
    `可用现金：${account.availableCash ?? "--"}`,
    `持仓数量：${account.holdingQuantity ?? "--"} 股/份`,
    `成本价：${account.averageCost ?? "--"}`,
    `最新价：${account.latestPrice ?? "--"}`,
    `当前市值：${account.marketValue ?? "--"}`,
    `浮动盈亏：${account.unrealizedPnl ?? "--"} (${account.unrealizedReturn ?? "--"})`,
    `当前仓位：${account.currentWeight ?? "--"}`,
    `策略目标仓位：${account.targetWeight ?? "--"}`,
    `风险偏好：${account.riskProfile ?? "--"}`
  ].join("\n");
  els.backtestEvidence.textContent = [
    `原因：${account.reason ?? "--"}`,
    "",
    account.disclaimer ?? "研究建议，不构成真实交易指令。"
  ].join("\n");
}

function renderRiskDock(data) {
  const operation = data?.analysis?.operation ?? {};
  const backtest = data?.backtest ?? {};
  els.backtestSummary.textContent = [
    `仓位上限：${operation.target_position_limit ?? "--"}`,
    `等级：${operation.grade ?? "--"} ${operation.grade_description ?? ""}`,
    `不交易原因：${operation.abstain_reason ?? "--"}`
  ].join("\n");
  els.backtestMetrics.textContent = [
    `最大回撤：${backtest.max_drawdown ?? "--"}`,
    `相对基准：${backtest.excess_return ?? "--"}`,
    `Brier：${backtest.brier_score ?? "--"}`,
    `可靠性：${backtest.reliability_grade ?? "--"}`
  ].join("\n");
  els.backtestEvidence.textContent = joinList(operation.negative_drivers, "\n") || "风险证据等待策略计算。";
}

function renderKnowledgeDock() {
  els.backtestSummary.textContent = "信号说明：\n买入候选表示研究级机会；卖出/减仓表示风险或趋势转弱；观察表示暂不操作；暂不交易表示样本、风险或门禁不足。";
  els.backtestMetrics.textContent = "等级说明：\nA：预测、回测、校准、风险门槛较强。\nB：可研究使用，仍需模拟盘确认。\nC：证据偏弱，只能观察。\nN：不交易或样本不足。";
  els.backtestEvidence.textContent = "当前版本默认仅研究观察，不会真实下单。只有模拟盘和 API 门禁都通过后，才会进入后续执行候选。";
}

function toggleAccountPanel() {
  state.accountPanelOpen = !state.accountPanelOpen;
  els.accountPanel.hidden = !state.accountPanelOpen;
  els.accountToggleButton.classList.toggle("active", state.accountPanelOpen);
  els.accountToggleButton.textContent = state.accountPanelOpen ? "收起账户" : "账户输入";
  if (state.accountPanelOpen) {
    loadAccountContextIntoForm(state.lastData);
    renderAccountInlinePreview();
    window.requestAnimationFrame(() => els.accountPanel.scrollIntoView({ behavior: "smooth", block: "nearest" }));
  }
}

function saveAccountContext() {
  const context = readAccountContextFromForm();
  const keys = accountStorageKeys();
  if (!keys.length) {
    setStatus("ACCOUNT_INPUT", "NEED_SYMBOL", "--");
    els.accountInlineSummary.textContent = "请先输入代码并回车，再保存账户数据。";
    return;
  }
  keys.forEach((key) => localStorage.setItem(key, JSON.stringify(context)));
  renderAccountInlinePreview();
  setActiveTab("paper");
  fetchAnalysis();
}

function clearAccountContext() {
  accountStorageKeys().forEach((key) => localStorage.removeItem(key));
  [els.accountCapitalInput, els.accountCashInput, els.accountQuantityInput, els.accountCostInput].forEach((input) => {
    input.value = "";
  });
  els.accountRiskInput.value = "standard";
  renderAccountInlinePreview();
  fetchAnalysis();
}

function readAccountContextForPayload() {
  return readStoredAccountContext() ?? null;
}

function readStoredAccountContext() {
  for (const key of accountStorageKeys()) {
    try {
      const raw = localStorage.getItem(key);
      if (!raw) continue;
      const parsed = JSON.parse(raw);
      if (parsed && typeof parsed === "object") return parsed;
    } catch {
      localStorage.removeItem(key);
    }
  }
  return null;
}

function loadAccountContextIntoForm(data) {
  if (!els.accountPanel || els.accountPanel.hidden) return;
  const context = readStoredAccountContext();
  if (!context) {
    renderAccountInlinePreview();
    return;
  }
  els.accountCapitalInput.value = context.plannedCapital ?? "";
  els.accountCashInput.value = context.availableCash ?? "";
  els.accountQuantityInput.value = context.holdingQuantity ?? "";
  els.accountCostInput.value = context.averageCost ?? "";
  els.accountRiskInput.value = context.riskProfile ?? "standard";
  renderAccountInlinePreview(data?.accountAssessment);
}

function renderAccountInlinePreview(assessment = state.lastData?.accountAssessment) {
  const form = readAccountContextFromForm();
  if (!hasAccountFormValue(form)) {
    els.accountInlineSummary.textContent = "当前标的尚未录入账户数据。填写后点击“按当前策略评估”。";
    return;
  }
  if (assessment?.connected) {
    els.accountInlineSummary.textContent = `${assessment.summary ?? ""} ${assessment.disclaimer ?? ""}`.trim();
    return;
  }
  els.accountInlineSummary.textContent = [
    `计划资金 ${formatPlainMoney(form.plannedCapital)}`,
    `持仓 ${form.holdingQuantity || 0} 股/份`,
    `成本 ${form.averageCost || "--"}`,
    `风险偏好记录 ${riskProfileLabel(form.riskProfile)}`
  ].join(" · ");
}

function readAccountContextFromForm() {
  return {
    plannedCapital: numberInputValue(els.accountCapitalInput),
    availableCash: optionalNumberInputValue(els.accountCashInput),
    holdingQuantity: Math.max(0, Math.floor(numberInputValue(els.accountQuantityInput))),
    averageCost: numberInputValue(els.accountCostInput),
    riskProfile: els.accountRiskInput.value || "standard"
  };
}

function hasAccountFormValue(context) {
  return Boolean(
    context.plannedCapital ||
      context.availableCash ||
      context.holdingQuantity ||
      context.averageCost
  );
}

function accountStorageKeys() {
  const selected = state.lastData?.selectedSecurity ?? {};
  return Array.from(
    new Set(
      [
        selected.security_id,
        selected.symbol,
        state.query,
        els.searchInput.value.trim()
      ]
        .filter(Boolean)
        .map((value) => `chinaQuantAccount:${String(value).trim().toUpperCase()}`)
    )
  );
}

function numberInputValue(input) {
  const value = Number.parseFloat(input.value);
  return Number.isFinite(value) && value > 0 ? value : 0;
}

function optionalNumberInputValue(input) {
  if (input.value.trim() === "") return null;
  return numberInputValue(input);
}

function formatPlainMoney(value) {
  return value ? `${Number(value).toLocaleString("zh-CN")} 元` : "--";
}

function riskProfileLabel(value) {
  return {
    conservative: "保守",
    standard: "标准",
    aggressive: "激进"
  }[value] ?? "标准";
}

function accountTagClass(value) {
  const text = String(value ?? "");
  if (text.includes("加仓") || text.includes("试买")) return "buy";
  if (text.includes("减仓") || text.includes("止损")) return "sell";
  return "warn";
}

function initTheme() {
  const saved = localStorage.getItem("chinaQuantTheme") || "dark";
  els.themeMode.value = saved;
  applyTheme(saved);
}

function applyTheme(theme) {
  const normalized = theme === "light" ? "light" : "dark";
  document.documentElement.dataset.theme = normalized;
  els.themeMode.value = normalized;
  localStorage.setItem("chinaQuantTheme", normalized);
  drawChart(state.lastData);
}

function autoRefreshLabel() {
  if (!state.autoRefreshMs) return "自动刷新：已停止";
  if (state.autoRefreshMs < 1000) return `自动刷新：${state.autoRefreshMs}ms`;
  return `自动刷新：${Math.round(state.autoRefreshMs / 1000)}秒`;
}

function setText(element, value) {
  if (element) element.textContent = value;
}

function setClassText(element, value, className) {
  if (!element) return;
  element.textContent = value;
  element.className = className;
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

  const overlays = effectiveOverlays(data);
  const forecast = overlays.includes("FORECAST") ? forecastQuantiles(data) : null;
  const margin = { left: 76, right: 18, top: 24, bottom: 34 };
  const forecastWidth = forecast ? Math.min(180, Math.max(110, width * 0.12)) : 0;
  const priceRect = {
    x: margin.left,
    y: margin.top,
    w: width - margin.left - margin.right,
    h: height * 0.55
  };
  const dataRect = { ...priceRect, w: priceRect.w - forecastWidth };
  const forecastRect = forecast
    ? { x: dataRect.x + dataRect.w, y: priceRect.y, w: forecastWidth, h: priceRect.h }
    : null;
  const changeRect = { x: margin.left, y: priceRect.y + priceRect.h + 26, w: dataRect.w, h: height * 0.15 };
  const volumeRect = { x: margin.left, y: changeRect.y + changeRect.h + 24, w: dataRect.w, h: height - changeRect.y - changeRect.h - margin.bottom - 24 };

  const prices = points.flatMap((p) => [p.low_price, p.high_price]).filter((v) => Number.isFinite(v));
  if (forecast) {
    prices.push(forecast.p05Price, forecast.p50Price, forecast.p95Price);
  }
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
  drawPriceLine(ctx, points, dataRect, minPrice, maxPrice);
  if (forecast) drawForecastOverlay(ctx, points, forecast, dataRect, forecastRect, minPrice, maxPrice);
  if (overlays.includes("MA")) drawMovingAverage(ctx, points, dataRect, minPrice, maxPrice);
  if (overlays.includes("SIGNALS")) drawSignals(ctx, points, data.chart.signals ?? [], dataRect, minPrice, maxPrice);
  if (overlays.includes("VOLUME")) {
    drawChangeBars(ctx, points, changeRect);
    drawVolumeBars(ctx, points, volumeRect);
  }
  drawLatest(ctx, points, dataRect, minPrice, maxPrice);
  drawXAxis(ctx, points, volumeRect, forecast);
}

function effectiveOverlays(data) {
  const source = state.lastPayload?.overlays ?? data?.chart?.overlays ?? [];
  return Array.from(new Set(source));
}

function forecastQuantiles(data) {
  const points = data?.chart?.points ?? [];
  const latest = points[points.length - 1];
  if (!latest?.close_price) return null;
  const forecast = data?.analysis?.forecast ?? {};
  const text = `${forecast.expected_return_range ?? ""} ${forecast.probability_summary ?? ""}`;
  const values = [...text.matchAll(/[-+]?\d+(?:\.\d+)?%/g)].map((match) => Number.parseFloat(match[0]) / 100);
  if (values.length < 2) return null;
  const p05 = values[0];
  const p95 = values[1];
  const p50 = Number.isFinite(values[2]) ? values[2] : (p05 + p95) / 2;
  return {
    p05,
    p50,
    p95,
    p05Price: latest.close_price * (1 + p05),
    p50Price: latest.close_price * (1 + p50),
    p95Price: latest.close_price * (1 + p95),
    label: forecast.expected_return_range ?? "预测区间"
  };
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

function drawForecastOverlay(ctx, points, forecast, dataRect, forecastRect, minPrice, maxPrice) {
  if (!forecastRect) return;
  const latest = points[points.length - 1];
  const startX = xAt(points.length - 1, points.length, dataRect);
  const endX = forecastRect.x + forecastRect.w - 12;
  const latestY = yAt(latest.close_price, dataRect, minPrice, maxPrice);
  const p05Y = yAt(forecast.p05Price, dataRect, minPrice, maxPrice);
  const p50Y = yAt(forecast.p50Price, dataRect, minPrice, maxPrice);
  const p95Y = yAt(forecast.p95Price, dataRect, minPrice, maxPrice);

  ctx.save();
  ctx.strokeStyle = "rgba(192, 132, 252, 0.45)";
  ctx.lineWidth = 1;
  ctx.setLineDash([4, 6]);
  ctx.beginPath();
  ctx.moveTo(forecastRect.x, dataRect.y);
  ctx.lineTo(forecastRect.x, dataRect.y + dataRect.h);
  ctx.stroke();

  ctx.fillStyle = "rgba(168, 85, 247, 0.18)";
  ctx.beginPath();
  ctx.moveTo(startX, latestY);
  ctx.lineTo(endX, p95Y);
  ctx.lineTo(endX, p05Y);
  ctx.closePath();
  ctx.fill();

  ctx.strokeStyle = "#c084fc";
  ctx.lineWidth = 2.2;
  ctx.setLineDash([9, 6]);
  ctx.beginPath();
  ctx.moveTo(startX, latestY);
  ctx.lineTo(endX, p50Y);
  ctx.stroke();

  ctx.setLineDash([]);
  ctx.fillStyle = "#c084fc";
  ctx.beginPath();
  ctx.arc(endX, p50Y, 4.5, 0, Math.PI * 2);
  ctx.fill();

  const labelY = Math.min(dataRect.y + dataRect.h - 12, Math.max(dataRect.y + 24, p50Y - 12));
  ctx.fillStyle = "#d8b4fe";
  ctx.font = "bold 12px Microsoft YaHei UI";
  ctx.fillText("预测区间", forecastRect.x + 10, labelY);
  ctx.font = "11px Consolas";
  ctx.fillText(compactText(forecast.label, 24), forecastRect.x + 10, labelY + 17);
  ctx.restore();
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

function drawXAxis(ctx, points, rect, forecast) {
  ctx.fillStyle = "#94a3b8";
  ctx.font = "12px Consolas";
  const indexes = [0, Math.floor(points.length / 2), points.length - 1];
  indexes.forEach((index) => {
    const x = xAt(index, points.length, rect);
    ctx.fillText(points[index].time_label.slice(0, 10), x - 36, rect.y + rect.h + 20);
  });
  if (forecast) {
    ctx.fillStyle = "#c084fc";
    ctx.font = "bold 12px Microsoft YaHei UI";
    ctx.fillText("预测", rect.x + rect.w + 16, rect.y + rect.h + 20);
  }
}

function xAt(index, count, rect) {
  if (count <= 1) return rect.x + rect.w / 2;
  return rect.x + (rect.w * index) / (count - 1);
}

function yAt(value, rect, minPrice, maxPrice) {
  return rect.y + rect.h - ((value - minPrice) / (maxPrice - minPrice)) * rect.h;
}

function compactText(value, maxLength) {
  const text = String(value ?? "");
  if (text.length <= maxLength) return text;
  return `${text.slice(0, maxLength - 1)}…`;
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

function signalLabel(value) {
  const labels = {
    BUY_CANDIDATE: "买入候选",
    ADD_CANDIDATE: "加仓候选",
    SELL: "卖出",
    REDUCE: "减仓",
    HOLD: "持有",
    WATCH: "观察",
    ABSTAIN: "暂不交易"
  };
  return labels[value] ?? value ?? "--";
}

function signalTextClass(value) {
  const cls = signalClass(value);
  if (cls === "buy") return "up";
  if (cls === "sell") return "down";
  if (cls === "warn") return "warn";
  return "neutral";
}

function readinessLabel(value) {
  const labels = {
    RESEARCH_ONLY: "仅研究观察",
    PAPER_READY: "模拟盘就绪",
    API_CANDIDATE: "API候选",
    LIVE_BLOCKED: "实盘阻断",
    BLOCKED: "已阻断",
    MISSING: "缺少验证",
    PASS: "通过",
    WARN: "警告",
    FAIL: "失败"
  };
  return labels[value] ?? value ?? "--";
}

function readinessClass(value) {
  if (["PAPER_READY", "API_CANDIDATE", "PASS"].includes(value)) return "buy";
  if (["FAIL", "BLOCKED", "LIVE_BLOCKED"].includes(value)) return "sell";
  return "warn";
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
