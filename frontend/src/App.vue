<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import ChartView from "./components/ChartView.vue";
import { marketOverview as fetchMarketOverview, recommendations as fetchRecommendations } from "./api/client";
import { useAnalysisStore } from "./stores/analysis";

type WatchlistItem = { securityId: string; symbol: string; name: string };
type HistoryItem = WatchlistItem & { visitedAt: string };

function loadWatchlist(): WatchlistItem[] {
  try {
    const value = JSON.parse(localStorage.getItem("chinaQuantVue:watchlist") || "[]");
    if (!Array.isArray(value)) return [];
    return value.filter((item) => item && typeof item.securityId === "string").map((item) => ({
      securityId: item.securityId,
      symbol: item.symbol || item.securityId,
      name: item.name || "未命名标的",
    }));
  } catch {
    localStorage.removeItem("chinaQuantVue:watchlist");
    return [];
  }
}
function loadHistory(): HistoryItem[] {
  try {
    const value = JSON.parse(localStorage.getItem("chinaQuantVue:history") || "[]");
    if (!Array.isArray(value)) return [];
    return value.filter((item) => item && typeof item.securityId === "string").map((item) => ({
      securityId: item.securityId,
      symbol: item.symbol || item.securityId,
      name: item.name || "未命名标的",
      visitedAt: item.visitedAt || "",
    }));
  } catch {
    localStorage.removeItem("chinaQuantVue:history");
    return [];
  }
}

const store = useAnalysisStore();
const { data, loading, error } = storeToRefs(store);
const WATCHLIST_KEY = "chinaQuantVue:watchlist";
const activeTab = ref("market");
const query = ref(data.value?.selectedSecurity?.security_id || "");
const watchlist = ref(loadWatchlist());
const history = ref(loadHistory());
const strategyMode = ref(data.value?.strategyControls?.mode || "short_term");
const maxTrades = ref(Number(data.value?.strategyControls?.max_trades_per_year || 12));
const theme = ref(localStorage.getItem("chinaQuantVue:theme") || "dark");
const refreshMs = ref(Number(localStorage.getItem("chinaQuantVue:refreshMs") || 15000));
const interval = ref(data.value?.chart?.interval || "1d");
const range = ref(data.value?.chart?.range || "1m");
const adjustment = ref(data.value?.chart?.adjustment || "NONE");
const overlays = ref<string[]>(data.value?.chart?.overlays || ["VOLUME"]);
const backtestActive = ref(Boolean(data.value?.chart?.chartBacktestActive));
const accountOpen = ref(false);
const marketOverview = ref<Record<string, any> | null>(loadMarketOverviewCache());
const marketOverviewLoading = ref(false);
const marketOverviewError = ref("");
const recommendations = ref<Record<string, any> | null>(loadRecommendationsCache());
const recommendationLoading = ref(false);
const recommendationError = ref("");
let refreshTimer: number | null = null;
let debounceTimer: number | null = null;

const account = reactive({ plannedCapital: "", availableCash: "", holdingQuantity: "", averageCost: "", riskProfile: "standard" });

const selected = computed(() => data.value?.selectedSecurity || null);
const selectedWatchlistId = computed(() => selected.value?.security_id || query.value.trim());
const chart = computed(() => data.value?.chart || { points: [], signals: [] });
const analysis = computed(() => data.value?.analysis || {});
const forecast = computed(() => analysis.value.forecast || {});
const operation = computed(() => analysis.value.operation || {});
const strategy = computed(() => analysis.value.strategy || {});
const backtest = computed(() => data.value?.backtest || {});
const health = computed(() => data.value?.dataHealth || {});
const latest = computed(() => chart.value.points?.[chart.value.points.length - 1] || null);
const latestChange = computed(() => {
  const points = chart.value.points || [];
  const current = Number(latest.value?.close_price || 0);
  const previous = Number(points[points.length - 2]?.close_price || current);
  return previous ? ((current / previous - 1) * 100).toFixed(2) : "0.00";
});
const accountAssessment = computed(() => data.value?.accountAssessment || {});
const cacheLabel = computed(() => data.value?.cache?.status === "STALE" ? "已保留上次数据" : "");

function loadMarketOverviewCache() {
  try {
    return JSON.parse(localStorage.getItem("chinaQuantVue:marketOverview") || "null");
  } catch {
    localStorage.removeItem("chinaQuantVue:marketOverview");
    return null;
  }
}
function loadRecommendationsCache() {
  try {
    return JSON.parse(localStorage.getItem("chinaQuantVue:recommendations") || "null");
  } catch {
    localStorage.removeItem("chinaQuantVue:recommendations");
    return null;
  }
}

function payload() {
  const accountContext = readAccount();
  return { query: query.value.trim(), strategyMode: strategyMode.value, maxTrades: maxTrades.value, interval: interval.value, range: range.value, adjustment: adjustment.value, overlays: overlays.value, chartBacktestActive: backtestActive.value, accountContext };
}

function runAnalysis(options: { silent?: boolean } = {}) {
  if (!query.value.trim()) return;
  store.fetch(payload(), options);
}

function submitSearch() { runAnalysis(); }
function toggleOverlay(name: string) {
  overlays.value = overlays.value.includes(name) ? overlays.value.filter((item) => item !== name) : [...overlays.value, name];
}
function toggleBacktest() { backtestActive.value = !backtestActive.value; runAnalysis(); }
function scheduleAnalysis() {
  if (debounceTimer) window.clearTimeout(debounceTimer);
  debounceTimer = window.setTimeout(() => runAnalysis(), 180);
}
function configureRefresh() {
  if (refreshTimer) window.clearInterval(refreshTimer);
  refreshTimer = null;
  localStorage.setItem("chinaQuantVue:refreshMs", String(refreshMs.value));
  if (refreshMs.value > 0) refreshTimer = window.setInterval(() => runAnalysis({ silent: true }), refreshMs.value);
}

function accountKey() {
  const symbol = selected.value?.security_id || query.value.trim();
  return symbol ? `chinaQuantVue:account:${symbol.toUpperCase()}` : "";
}
function readAccount() {
  const values: Record<string, any> = {};
  if (account.plannedCapital) values.plannedCapital = Number(account.plannedCapital);
  if (account.availableCash) values.availableCash = Number(account.availableCash);
  if (account.holdingQuantity) values.holdingQuantity = Number(account.holdingQuantity);
  if (account.averageCost) values.averageCost = Number(account.averageCost);
  if (account.riskProfile) values.riskProfile = account.riskProfile;
  return Object.keys(values).length ? values : null;
}
function loadAccount() {
  const key = accountKey();
  const value = key ? JSON.parse(localStorage.getItem(key) || "null") : null;
  Object.assign(account, { plannedCapital: value?.plannedCapital ?? "", availableCash: value?.availableCash ?? "", holdingQuantity: value?.holdingQuantity ?? "", averageCost: value?.averageCost ?? "", riskProfile: value?.riskProfile ?? "standard" });
}
function saveAccount() {
  const key = accountKey();
  if (!key) return;
  localStorage.setItem(key, JSON.stringify(readAccount()));
  runAnalysis();
}
function clearAccount() {
  const key = accountKey();
  if (key) localStorage.removeItem(key);
  Object.assign(account, { plannedCapital: "", availableCash: "", holdingQuantity: "", averageCost: "", riskProfile: "standard" });
  runAnalysis();
}

async function refreshMarketOverview(options: { silent?: boolean } = {}) {
  if (marketOverviewLoading.value) return;
  marketOverviewLoading.value = true;
  marketOverviewError.value = "";
  try {
    const result = await fetchMarketOverview();
    marketOverview.value = result.marketOverview || null;
    if (marketOverview.value) {
      localStorage.setItem("chinaQuantVue:marketOverview", JSON.stringify(marketOverview.value));
    }
  } catch (reason: any) {
    marketOverviewError.value = marketOverview.value ? "刷新失败，已保留上次数据" : (reason?.message || "市场指数获取失败");
    if (!options.silent) marketOverviewError.value = reason?.message || marketOverviewError.value;
  } finally {
    marketOverviewLoading.value = false;
  }
}

async function refreshRecommendations(options: { silent?: boolean } = {}) {
  if (recommendationLoading.value) return;
  recommendationLoading.value = true;
  recommendationError.value = "";
  try {
    recommendations.value = await fetchRecommendations({ limit: 10, horizonDays: strategyMode.value === "long_term" ? 21 : 10, includeUsLinked: true });
    localStorage.setItem("chinaQuantVue:recommendations", JSON.stringify(recommendations.value));
  } catch (reason: any) {
    recommendationError.value = recommendations.value ? "刷新失败，已保留上次结果" : (reason?.message || "荐股池刷新失败");
    if (!recommendations.value) recommendations.value = loadRecommendationsCache();
    if (!options.silent) recommendationError.value = reason?.message || recommendationError.value;
  } finally {
    recommendationLoading.value = false;
  }
}
function openCandidate(item: any) {
  query.value = item.securityId || item.symbol;
  activeTab.value = "market";
  loadAccount();
  runAnalysis();
}
function addCurrentToWatchlist() {
  if (!selected.value?.security_id) return;
  if (watchlist.value.some((item) => item.securityId === selected.value.security_id)) return;
  watchlist.value.push({
    securityId: selected.value.security_id,
    symbol: selected.value.symbol || selected.value.security_id,
    name: selected.value.name || "未命名标的",
  });
}
function removeFromWatchlist(securityId: string) {
  watchlist.value = watchlist.value.filter((item) => item.securityId !== securityId);
}
function clearWatchlist() {
  watchlist.value = [];
}
function selectWatchlistItem(item: WatchlistItem) {
  query.value = item.securityId;
  activeTab.value = "market";
  loadAccount();
  runAnalysis();
}
function selectHistoryItem(item: HistoryItem) {
  query.value = item.securityId;
  activeTab.value = "market";
  loadAccount();
  runAnalysis();
}
function removeHistoryItem(securityId: string) {
  history.value = history.value.filter((item) => item.securityId !== securityId);
}
function clearHistory() {
  history.value = [];
}
function recordHistory(security: any) {
  if (!security?.security_id) return;
  const next: HistoryItem = {
    securityId: security.security_id,
    symbol: security.symbol || security.security_id,
    name: security.name || "未命名标的",
    visitedAt: new Date().toISOString(),
  };
  history.value = [next, ...history.value.filter((item) => item.securityId !== next.securityId)].slice(0, 10);
}
function selectMarketIndex(index: any) {
  if (!index?.security_id) return;
  query.value = index.security_id;
  activeTab.value = "market";
  runAnalysis();
}
function indexChangeClass(value: string) {
  const numeric = Number.parseFloat(String(value).replace("%", ""));
  return numeric >= 0 ? "up" : "down";
}
function setTheme(value: string) { theme.value = value; localStorage.setItem("chinaQuantVue:theme", value); }
function toggleAccount() { accountOpen.value = !accountOpen.value; if (accountOpen.value) loadAccount(); }

function signalLabel(signal: string) { return ({ BUY_CANDIDATE: "买入候选", SELL: "卖出", REDUCE: "减仓", HOLD: "持有", WATCH: "观察", ABSTAIN: "暂不交易" } as any)[signal] || signal || "--"; }
function signalClass(signal: string) { return ["BUY_CANDIDATE", "SELL"].includes(signal) ? "up" : ["REDUCE", "ABSTAIN"].includes(signal) ? "down" : "warn"; }
function changeArrow(value: string) { const numeric = Number(value); return numeric > 0 ? "↑" : numeric < 0 ? "↓" : "→"; }
function display(value: any) { return value === undefined || value === null || value === "" ? "--" : String(value); }
function rows(source: Record<string, any>, fields: [string, string][]) { return fields.map(([label, key]) => ({ label, value: display(source?.[key]) })); }
function recommendationGradeClass(item: any) { return item.gradeClass || (Number(item.totalScore) >= 85 ? "strong" : Number(item.totalScore) >= 70 ? "observe" : "weak"); }

watch([strategyMode, maxTrades, interval, range, adjustment, backtestActive], scheduleAnalysis);
watch(theme, (value) => document.documentElement.dataset.theme = value, { immediate: true });
watch(refreshMs, configureRefresh);
watch(() => selected.value?.security_id, loadAccount);
watch(watchlist, (items) => localStorage.setItem(WATCHLIST_KEY, JSON.stringify(items)), { deep: true });
watch(history, (items) => localStorage.setItem("chinaQuantVue:history", JSON.stringify(items)), { deep: true });
watch(selected, recordHistory, { immediate: true });
watch(activeTab, (value) => { if (value === "recommendations" && !recommendations.value) refreshRecommendations(); });
onMounted(() => {
  loadAccount();
  configureRefresh();
  if (!data.value && query.value) runAnalysis();
  void refreshMarketOverview({ silent: true });
  void refreshRecommendations({ silent: true });
});
onUnmounted(() => { if (refreshTimer) window.clearInterval(refreshTimer); if (debounceTimer) window.clearTimeout(debounceTimer); });
</script>

<template>
  <div class="app-shell">
    <aside class="sidebar">
      <div class="brand"><div class="brand-mark">Q</div><div><strong>量化工作台</strong><small>股票与基金研究终端</small></div></div>
      <nav class="nav-list">
        <button v-for="item in [{id:'market',label:'市场总览',sub:'行情与指数'},{id:'recommendations',label:'荐股池',sub:'短线候选'},{id:'strategy',label:'策略验证',sub:'预测与建议'},{id:'paper',label:'模拟账户',sub:'手动仓位'},{id:'risk',label:'风险雷达',sub:'回撤与门禁'}]" :key="item.id" :class="['nav-item', {active: activeTab === item.id}]" @click="activeTab = item.id"><span>{{ item.label }}</span><small>{{ item.sub }}</small></button>
      </nav>
      <section class="side-card watchlist-card">
        <div class="section-title-row"><div class="section-title">自选列表</div><div class="side-actions"><button class="mini-button" :disabled="!selected" @click="addCurrentToWatchlist">加入</button><button class="mini-button" :disabled="!watchlist.length" @click="clearWatchlist">清空</button></div></div>
        <div v-if="watchlist.length" class="watchlist-list">
          <div v-for="item in watchlist" :key="item.securityId" :class="['watchlist-item', { active: selectedWatchlistId === item.securityId }]" @click="selectWatchlistItem(item)">
            <span><strong>{{ item.symbol }}</strong><small>{{ item.name }}</small></span><button class="watchlist-remove" title="从自选列表删除" @click.stop="removeFromWatchlist(item.securityId)">×</button>
          </div>
        </div>
        <div v-else class="side-empty">输入代码并分析后，点击“加入”保存。</div>
      </section>
      <section class="side-card market-index-card">
        <div class="section-title-row"><div class="section-title">市场指数</div><button class="mini-button" :disabled="marketOverviewLoading" @click="refreshMarketOverview">{{ marketOverviewLoading ? '刷新中' : '刷新' }}</button></div>
        <div v-if="marketOverview?.indices?.length" class="index-list">
          <div v-for="index in marketOverview.indices" :key="index.security_id" class="index-item" @click="selectMarketIndex(index)">
            <span class="index-name">{{ index.name }}</span><strong :class="indexChangeClass(index.change_pct)">{{ index.latest_value }}</strong><small :class="indexChangeClass(index.change_pct)">{{ index.change_pct }}</small>
          </div>
          <small class="index-meta">{{ marketOverview.data_health_text || '市场指数已更新' }} · {{ marketOverview.as_of || '--' }}</small>
        </div>
        <div v-else class="side-empty">{{ marketOverviewError || (marketOverviewLoading ? '正在获取市场指数…' : '市场指数暂不可用') }}</div>
      </section>
      <section class="side-card history-card">
        <div class="section-title-row"><div class="section-title">历史浏览</div><button class="mini-button" :disabled="!history.length" @click="clearHistory">清空</button></div>
        <div v-if="history.length" class="history-list">
          <div v-for="item in history" :key="item.securityId" :class="['history-item', { active: selectedWatchlistId === item.securityId }]" @click="selectHistoryItem(item)">
            <span><strong>{{ item.symbol }}</strong><small>{{ item.name }}</small></span><button class="watchlist-remove" title="从历史浏览删除" @click.stop="removeHistoryItem(item.securityId)">×</button>
          </div>
        </div>
        <div v-else class="side-empty">搜索并打开标的后，会自动记录在这里。</div>
      </section>
    </aside>

    <main class="main-content">
      <header class="top-header">
        <div class="eyebrow">Research Workspace</div>
        <h1>{{ selected ? `${selected.symbol || ''} ${selected.name || ''}` : '量化策略工作台' }}</h1>
        <p>{{ selected ? `${selected.security_id || selected.symbol} · ${strategy.mode_label || '策略待计算'} · ${strategy.horizon_label || '--'}` : '输入代码后回车，加载行情、策略预测与回测证据。' }}</p>
        <div class="toolbar">
          <input v-model="query" class="search-input" placeholder="代码 / 名称" @keyup.enter="submitSearch" />
          <select v-model="strategyMode" class="control"><option value="short_term">短线策略</option><option value="long_term">长线策略</option></select>
          <select v-model.number="maxTrades" class="control"><option v-for="number in [4,6,8,10,12,20,30]" :key="number" :value="number">{{ number }} 次</option></select>
          <select v-model="theme" class="control"><option value="dark">黑色主题</option><option value="light">白色主题</option></select>
          <select v-model.number="refreshMs" class="control"><option :value="5000">5秒刷新</option><option :value="15000">15秒刷新</option><option :value="30000">30秒刷新</option><option :value="0">停止刷新</option></select>
          <button class="secondary-button" :class="{active: accountOpen}" @click="toggleAccount">账户输入</button>
          <button class="primary-button" :class="{active: backtestActive}" @click="toggleBacktest">{{ backtestActive ? '正常显示' : '回测曲线' }}</button>
        </div>
      </header>

      <section class="health-row"><div :class="['health', health.status === 'HEALTHY' ? 'healthy' : 'degraded']">数据健康：{{ health.status || (loading ? '获取中' : '等待行情') }} <span v-if="cacheLabel">· {{ cacheLabel }}</span></div><span>行情时间：{{ latest?.time_label || '--' }}</span></section>

      <section class="kpi-grid">
        <article class="kpi accent-blue"><small>当前价格</small><strong>{{ latest ? Number(latest.close_price).toFixed(3) : '--' }}</strong><span :class="Number(latestChange) >= 0 ? 'up' : 'down'">{{ latest ? `${changeArrow(latestChange)} ${Number(latestChange) >= 0 ? '+' : ''}${latestChange}%` : '等待行情' }}</span></article>
        <article class="kpi accent-red"><small>策略建议</small><strong :class="signalClass(operation.final_signal)">{{ signalLabel(operation.final_signal) }}</strong><span>等级 {{ operation.grade || '--' }} · 仓位上限 {{ operation.target_position_limit || '--' }}</span></article>
        <article class="kpi accent-green"><small>预期收益区间</small><strong>{{ forecast.expected_return_range || '--' }}</strong><span>{{ forecast.probability_summary || '概率待计算' }} · 回撤 {{ forecast.expected_drawdown || '--' }}</span></article>
        <article class="kpi accent-amber"><small>回测状态</small><strong>{{ backtest.total_return || '--' }}</strong><span>{{ backtest.status || '样本外验证待加载' }} · 交易 {{ backtest.trade_count || '--' }} · 胜率 {{ backtest.win_rate || '--' }} · Sharpe {{ backtest.sharpe_ratio || '--' }}</span></article>
      </section>

      <section class="workspace-grid">
        <section class="chart-panel">
          <div class="panel-heading"><div><h2>行情曲线</h2><p>周期：{{ interval }} · 复权：{{ adjustment }} · 范围：{{ range }} · 点数：{{ chart.points?.length || 0 }}</p></div><div class="chart-controls"><select v-model="interval" class="control"><option value="1d">日线</option><option value="30m">30分</option><option value="60m">60分</option><option value="1w">周线</option></select><select v-model="range" class="control"><option value="5d">5日</option><option value="1m">1月</option><option value="3m">3月</option><option value="6m">6月</option><option value="1y">1年</option></select><select v-model="adjustment" class="control"><option value="NONE">不复权</option><option value="FORWARD">前复权</option><option value="BACKWARD">后复权</option></select><label><input type="checkbox" :checked="overlays.includes('VOLUME')" @change="toggleOverlay('VOLUME')" />成交量</label><label><input type="checkbox" :checked="overlays.includes('MA')" @change="toggleOverlay('MA')" />MA</label><label><input type="checkbox" :checked="overlays.includes('SIGNALS')" @change="toggleOverlay('SIGNALS')" />回测信号</label><label><input type="checkbox" :checked="overlays.includes('FORECAST')" @change="toggleOverlay('FORECAST')" />预测区间</label></div></div>
          <section v-if="accountOpen" class="account-panel"><div class="panel-heading"><div><h2>手动账户 / 仓位评估</h2><p>只保存在本机；建议与当前 {{ strategyMode === 'short_term' ? '短线' : '长线' }}策略联动，不读取券商账户。</p></div><button class="secondary-button" @click="clearAccount">清空当前标的</button></div><div class="account-form"><label>计划总资金<input v-model="account.plannedCapital" type="number" min="0" /></label><label>可用现金<input v-model="account.availableCash" type="number" min="0" /></label><label>持仓数量<input v-model="account.holdingQuantity" type="number" min="0" /></label><label>成本价<input v-model="account.averageCost" type="number" min="0" step="0.001" /></label><label>风险偏好(记录)<select v-model="account.riskProfile"><option value="conservative">保守</option><option value="standard">标准</option><option value="aggressive">激进</option></select></label><button class="primary-button" @click="saveAccount">按当前策略评估</button></div><div class="account-result">{{ accountAssessment.summary || '填写账户数据后，点击按当前策略评估。' }}<span v-if="accountAssessment.disclaimer"> {{ accountAssessment.disclaimer }}</span></div></section>
          <div class="chart-wrap"><ChartView :data="data" :overlays="overlays" :theme="theme" /><div v-if="!chart.points?.length" class="chart-empty">{{ error || '暂无图表数据' }}</div></div>
        </section>

        <aside class="insight-stack">
          <section class="info-card"><h2>当前策略</h2><div class="info-grid"> <template v-for="row in rows(strategy, [['模式','mode_label'],['策略','strategy_id'],['窗口','horizon_label'],['市场状态','market_regime'],['原始信号','raw_signal'],['样本','sample_count'],['模型','model_version']])" :key="row.label"><b>{{ row.label }}</b><span>{{ row.value }}</span></template></div></section>
          <section class="info-card"><h2>预期走势</h2><div class="info-grid"><template v-for="row in rows(forecast, [['方向','direction_label'],['概率','probability_summary'],['区间','expected_return_range'],['回撤','expected_drawdown'],['校准','validation_metrics']])" :key="row.label"><b>{{ row.label }}</b><span :class="row.label === '方向' ? 'tag warn' : ''">{{ row.value }}</span></template></div></section>
          <section class="info-card"><h2>操作与风险</h2><div class="info-grid"><b>策略建议</b><strong :class="signalClass(operation.final_signal)">{{ signalLabel(operation.final_signal) }}</strong><b>等级</b><span>{{ operation.grade || '--' }} {{ operation.grade_description || '' }}</span><b>仓位上限</b><span>{{ operation.target_position_limit || '0.0%' }}</span><b>主要风险</b><span>{{ operation.negative_drivers?.[0] || '暂无额外风险说明' }}</span><b>失效条件</b><span>{{ operation.exit_or_invalidation_conditions?.[0] || '--' }}</span><b>账户建议</b><strong>{{ accountAssessment.accountAdvice || '--' }}</strong><b>不交易原因</b><span>{{ operation.abstain_reason || '无' }}</span></div></section>
          <section class="info-card"><h2>决策证据</h2><div class="info-grid"><b>执行状态</b><span class="tag warn">{{ data?.decision?.readiness || '仅研究观察' }}</span><b>门禁信号</b><span>{{ signalLabel(data?.decision?.final_signal || operation.final_signal) }}</span><b>置信度</b><span>{{ data?.decision?.confidence || '--' }}</span><b>门禁汇总</b><span>{{ data?.decision?.gate_summary || '--' }}</span><b>阻断原因</b><span>{{ data?.decision?.blocking_reasons?.[0] || '无' }}</span><b>回测证据</b><span>{{ backtest.total_return || '--' }} · 回撤 {{ backtest.max_drawdown || '--' }} · Sharpe {{ backtest.sharpe_ratio || '--' }}</span><b>滚动前推</b><span>{{ backtest.walk_forward_consistency || '--' }}</span><b>成本压力</b><span>{{ backtest.cost_stress || '--' }}</span></div></section>
        </aside>
      </section>

      <section class="bottom-panel">
        <div class="tab-list"><button v-for="tab in ['market','recommendations','strategy','paper','risk']" :key="tab" :class="{active: activeTab === tab}" @click="activeTab = tab">{{ ({market:'市场总览',recommendations:'荐股池',strategy:'策略验证',paper:'模拟账户',risk:'风险雷达'} as any)[tab] }}</button></div>
        <div v-if="activeTab === 'recommendations'" class="recommendation-area"><div class="panel-heading"><div><h2>短线荐股候选池</h2><p>A股账户可买标的；海外方向使用境内跨境ETF，不推荐直接买 QQQ/SPY。</p></div><button class="primary-button" :disabled="recommendationLoading" @click="refreshRecommendations">{{ recommendationLoading ? '正在刷新' : '刷新荐股池' }}</button></div><p v-if="recommendationError" class="error-text">{{ recommendationError }}，已优先保留上次结果。</p><div class="summary-grid"><div><small>候选数</small><strong>{{ recommendations?.summary?.candidateCount || 0 }}</strong></div><div><small>强候选</small><strong>{{ recommendations?.summary?.strongCount || 0 }}</strong></div><div><small>观察候选</small><strong>{{ recommendations?.summary?.observeCount || 0 }}</strong></div><div><small>市场环境</small><strong>{{ recommendations?.marketState || '--' }}</strong></div></div><div class="table-scroll"><table><thead><tr><th>标的</th><th>等级</th><th>总分</th><th>交易制度</th><th>核心逻辑</th><th>买入触发</th><th>止损/止盈</th><th>仓位</th></tr></thead><tbody><tr v-for="item in recommendations?.candidates || []" :key="item.securityId" @click="openCandidate(item)"><td><strong>{{ item.symbol }} {{ item.name }}</strong><small>{{ item.securityId }} · {{ item.buyableMarket || 'A股账户可买' }}</small></td><td><span :class="['grade-pill', recommendationGradeClass(item)]">{{ item.grade }}</span></td><td><strong>{{ item.totalScore }}</strong></td><td><span :class="['trade-pill', item.tradingSystem?.isT0 ? 't0' : 't1']">{{ item.tradingSystem?.label || '--' }}</span></td><td>{{ item.coreLogic }}</td><td>{{ item.buyTrigger }}</td><td>{{ item.stopLoss }}<br>{{ item.takeProfit }}</td><td>{{ item.maxPosition }}</td></tr></tbody></table></div></div>
        <div v-else class="dock-grid"><div><h2>{{ activeTab === 'paper' ? '手动账户评估' : activeTab === 'risk' ? '风险雷达' : activeTab === 'strategy' ? '策略验证' : '市场总览' }}</h2><p>{{ activeTab === 'paper' ? (accountAssessment.summary || '尚未录入账户数据。点击顶部账户输入。') : selected ? `当前标的：${selected.security_id} · ${selected.name}` : '输入代码后查看完整分析。' }}</p></div><div><h2>指标</h2><p>策略：{{ strategy.mode_label || '--' }}<br>预期：{{ forecast.expected_return_range || '--' }}<br>回测：{{ backtest.total_return || '--' }}</p></div><div><h2>证据</h2><p>{{ operation.abstain_reason || '数据、策略、回测和风险证据将在此汇总。' }}</p></div></div>
      </section>
    </main>
  </div>
</template>
