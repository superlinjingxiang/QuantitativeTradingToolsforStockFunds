export function overlaysForBacktest(overlays: string[], enabled: boolean): string[] {
  const next = new Set(overlays);
  if (enabled) next.add("SIGNALS");
  else next.delete("SIGNALS");
  return [...next];
}

export function buildBacktestMarkPoints(
  signals: Record<string, any>[],
  axisLabels: string[],
  colors: { buy: string; sell: string },
) {
  return signals.flatMap((signal) => {
    const rawDate = String(signal.trade_date || signal.time_label || signal.time || "");
    const tradeDate = rawDate.slice(0, 10);
    const axisLabel = axisLabels.find((label) => String(label).slice(0, 10) === tradeDate);
    const price = Number(signal.price || signal.close_price || 0);
    if (!axisLabel || !Number.isFinite(price) || price <= 0) return [];

    const action = String(signal.action || signal.signal || "").toUpperCase();
    const isSell = action.includes("SELL");
    const marker = signal.label || (isSell ? "S" : "B");
    return [{
      name: signal.detail || (isSell ? "卖出" : "买入"),
      coord: [axisLabel, price],
      value: marker,
      symbol: "circle",
      symbolSize: 22,
      itemStyle: { color: isSell ? colors.sell : colors.buy },
      label: { show: true, formatter: marker, color: "#ffffff", fontSize: 9, fontWeight: "bold" },
      tooltip: { formatter: `${signal.detail || (isSell ? "卖出" : "买入")}<br/>${tradeDate} @ ${price.toFixed(3)}` },
    }];
  });
}
