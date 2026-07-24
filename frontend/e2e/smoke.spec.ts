import { expect, test } from "@playwright/test";

test("Vue workbench renders without a hard refresh", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("量化策略工作台").first()).toBeVisible();
  await expect(page.getByPlaceholder("代码 / 名称")).toBeVisible();
  await expect(page.getByRole("button", { name: "回测曲线" })).toBeVisible();
  await expect(page.getByText("当前策略")).toBeVisible();

  const scrollbarVisibility = await page.evaluate(() => {
    const sidebar = document.querySelector(".sidebar");
    return {
      page: getComputedStyle(document.documentElement, "::-webkit-scrollbar").display,
      body: getComputedStyle(document.body, "::-webkit-scrollbar").display,
      sidebar: sidebar ? getComputedStyle(sidebar, "::-webkit-scrollbar").display : "missing",
    };
  });
  expect(scrollbarVisibility).toEqual({ page: "none", body: "none", sidebar: "none" });
});

test("行情图同时展示价格、单日涨跌幅和成交量", async ({ page }) => {
  await page.route("**/api/quote?**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        ok: true,
        quote: {
          security_id: "SSE:513300",
          latest_price: 2.564,
          previous_close: 2.567,
          open_price: 2.57,
          high_price: 2.58,
          low_price: 2.55,
          volume: 1_900_000,
          amount: 4_871_600,
          provider: "fixture",
          source_time: "2026-07-20T10:00:03+08:00",
        },
        latestChangePct: 2.564 / 2.567 - 1,
        quoteState: { status: "LIVE", label: "实时行情" },
        cache: { status: "MISS" },
      }),
    });
  });
  await page.route("**/api/analyze", async (route) => {
    const fixture = await page.evaluate(() => localStorage.getItem("chinaQuantVue:lastAnalysis"));
    const payload = route.request().postDataJSON() || {};
    const result = JSON.parse(fixture || "{}");
    const backtestActive = Boolean(payload.chartBacktestActive);
    result.chart = {
      ...(result.chart || {}),
      chartBacktestActive: backtestActive,
      overlays: payload.overlays || result.chart?.overlays || [],
      signals: backtestActive ? [
        { trade_date: "2026-07-03", action: "BUY", price: 2.61, label: "B", detail: "最大利润买入" },
        { trade_date: "2026-07-08", action: "SELL", price: 2.73, label: "S", detail: "最大利润卖出" },
      ] : [],
    };
    const account = payload.accountContext;
    result.accountAssessment = account ? {
      connected: true,
      accountAdvice: "建议减仓",
      riskProfile: account.riskProfile === "conservative" ? "保守" : "标准",
      currentWeight: "75.0%",
      targetWeight: "5.0%",
      personalizedTargetWeight: "3.0%",
      unrealizedPnl: "-120.00 元",
      unrealizedReturn: "-1.5%",
      suggestedAmount: "建议减仓约2,000.00 元",
      suggestedQuantity: "700 股/份",
      reason: "当前短线策略为观察，账户仓位高于个性化目标，因此只建议降低超出部分。",
      summary: "建议减仓：当前仓位75.0%，个性化目标3.0%。",
    } : {
      connected: false,
      accountAdvice: "未录入",
      summary: "尚未录入账户数据。",
    };
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(result) });
  });
  await page.route("**/api/market-overview", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        ok: true,
        marketOverview: {
          indices: [
            { security_id: "SSE:000001", name: "上证指数", latest_value: "3000.00", change_pct: "+1.00%", source_time: "2026-07-11T09:30:00+08:00" },
            { security_id: "SZSE:399001", name: "深证成指", latest_value: "10000.00", change_pct: "-0.50%", source_time: "2026-07-11T09:30:00+08:00" },
          ],
          data_health_text: "HEALTHY",
          as_of: "2026-07-11T09:30:00+08:00",
        },
      }),
    });
  });
  await page.route("**/api/recommendations", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        ok: true,
        summary: { candidateCount: 1, strongCount: 1, observeCount: 0 },
        marketState: "RISK_ON",
        candidates: [{
          securityId: "SSE:513300",
          symbol: "513300",
          name: "纳斯达克ETF",
          grade: "强候选",
          totalScore: 88.5,
          buyableMarket: "境内ETF",
          tradingSystem: { isT0: false, label: "T+1" },
          coreLogic: "趋势和资金强度通过",
          buyTrigger: "放量突破",
          stopLoss: "跌破止损线",
          takeProfit: "分批止盈",
          maxPosition: "10%",
        }],
      }),
    });
  });
  await page.addInitScript(() => {
    const closes = [2.60, 2.63, 2.61, 2.68, 2.72, 2.70, 2.75, 2.73, 2.78, 2.76];
    const points = closes.map((close, index) => ({
      time_label: `2026-07-${String(index + 1).padStart(2, "0")}`,
      open_price: close,
      high_price: close + 0.01,
      low_price: close - 0.01,
      close_price: close,
      volume: 1_000_000 + index * 100_000,
      amount: close * 1_000_000,
      reference_price: index ? closes[index - 1] : 2.58,
    }));
    localStorage.setItem("chinaQuantVue:lastAnalysis", JSON.stringify({
      ok: true,
      selectedSecurity: { security_id: "SSE:513300", symbol: "513300", name: "纳斯达克ETF" },
      strategyControls: { mode: "short_term", max_trades_per_year: 12 },
      chart: { interval: "1d", range: "1m", adjustment: "NONE", overlays: ["VOLUME", "FORECAST"], chartBacktestActive: false, points, signals: [] },
      analysis: {
        strategy: { mode_label: "短线策略", strategy_id: "test", horizon_label: "21个交易日", asset_scope: "ETF", sample_count: points.length, model_version: "test" },
        forecast: { horizon: 5, horizon_label: "5个交易日终点", direction_label: "震荡偏强", probability_summary: "上涨50% / 横盘20% / 下跌30%", expected_return_range: "-3.0% to 6.0%; p50 1.2%", expected_drawdown: "-4.0%" },
        operation: { final_signal: "WATCH", grade: "B", target_position_limit: "5%" },
      },
      decision: { execution_status: "仅研究观察", final_signal: "WATCH", confidence: "60%" },
      backtest: { total_return: "3.2%", max_drawdown: "-2.1%", trade_count: 2, win_rate: "50%" },
      dataHealth: { status: "HEALTHY" },
    }));
  });
  await page.goto("/");
  const chartCanvas = page.locator(".chart-canvas[data-chart-layers='price,change,volume']");
  await expect(page.locator(".kpi.accent-blue")).toContainText("2.564");
  await expect(page.locator(".kpi.accent-blue")).toContainText("↓ -0.12%");
  await expect(page.locator(".kpi.accent-blue")).toContainText("实时行情");
  await expect(page.getByText("上证指数")).toBeVisible();
  await expect(page.getByText("+1.00%")).toBeVisible();
  await expect(page.locator(".history-item")).toHaveCount(1);
  await expect(chartCanvas).toHaveAttribute("data-forecast-points", "5");
  await expect(chartCanvas.locator("canvas")).toBeVisible();
  await expect(page.getByText("第5个交易日终点区间 · 虚线仅为插值，非逐日预测")).toBeVisible();
  const nonzeroPixels = await page.evaluate(() => {
    const canvas = document.querySelector(".chart-canvas canvas") as HTMLCanvasElement | null;
    if (!canvas) return 0;
    const pixels = canvas.getContext("2d")?.getImageData(0, 0, canvas.width, canvas.height).data || [];
    let count = 0;
    for (let index = 3; index < pixels.length; index += 4) if (pixels[index] > 0) count += 1;
    return count;
  });
  expect(nonzeroPixels).toBeGreaterThan(100);
  await page.getByRole("button", { name: "回测曲线" }).click();
  await expect(page.getByRole("button", { name: "正常显示" })).toBeVisible();
  await expect(page.getByLabel("回测信号")).toBeChecked();
  await expect(chartCanvas).toHaveAttribute("data-backtest-markers", "2");
  await page.getByLabel("回测信号").uncheck();
  await expect(page.getByRole("button", { name: "回测曲线" })).toBeVisible();
  await expect(chartCanvas).toHaveAttribute("data-backtest-markers", "0");
  await page.getByRole("button", { name: "账户输入" }).click();
  await expect(page.getByText("手动账户 / 仓位评估")).toBeVisible();
  await page.getByLabel("计划总资金").fill("10000");
  await page.getByLabel("可用现金").fill("2000");
  await page.getByLabel("持仓数量").fill("3000");
  await page.getByLabel("成本价").fill("2.60");
  await page.getByLabel("风险偏好").selectOption("conservative");
  await page.getByRole("button", { name: "按当前策略评估" }).click();
  await expect(page.locator(".kpi.accent-red")).toContainText("账户建议");
  await expect(page.locator(".kpi.accent-red")).toContainText("建议减仓");
  await expect(page.locator(".kpi.accent-red")).toContainText("市场策略 观察");
  const riskCard = page.getByRole("heading", { name: "操作与风险" }).locator("..");
  await expect(riskCard.getByText("75.0%", { exact: true })).toBeVisible();
  await expect(riskCard.getByText("3.0%", { exact: true })).toBeVisible();
  const savedAccount = await page.evaluate(() => localStorage.getItem("chinaQuantVue:account:513300"));
  expect(JSON.parse(savedAccount || "{}")).toMatchObject({
    plannedCapital: 10000,
    holdingQuantity: 3000,
    averageCost: 2.6,
    riskProfile: "conservative",
  });
  await page.locator("select.control").nth(2).selectOption("light");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await expect.poll(() => page.locator(".chart-wrap").evaluate((element) => getComputedStyle(element).backgroundColor)).toBe("rgb(13, 20, 31)");
  await page.getByRole("button", { name: "加入" }).click();
  await expect(page.locator(".watchlist-item")).toHaveCount(1);
  await page.reload();
  await expect(page.locator(".watchlist-item")).toHaveCount(1);
  await expect(page.locator(".history-item")).toHaveCount(1);
  await page.locator(".nav-item").filter({ hasText: "荐股池" }).click();
  await expect(page.getByText("短线荐股候选池")).toBeVisible();
  await expect(page.locator(".table-scroll").getByText("513300 纳斯达克ETF")).toBeVisible();
  await page.locator(".table-scroll tbody tr").first().click();
  await expect(page.locator(".search-input")).toHaveValue("SSE:513300");
  await page.locator(".nav-item").filter({ hasText: "策略验证" }).click();
  await expect(page.getByRole("heading", { name: "策略验证" })).toBeVisible();
  await page.locator(".nav-item").filter({ hasText: "模拟账户" }).click();
  await expect(page.getByRole("heading", { name: "手动账户评估" })).toBeVisible();
  await page.locator(".nav-item").filter({ hasText: "风险雷达" }).click();
  await expect(page.getByRole("heading", { name: "风险雷达" })).toBeVisible();
});
