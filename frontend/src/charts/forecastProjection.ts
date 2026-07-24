export interface ForecastRange {
  p05: number;
  p50: number;
  p95: number;
}

export interface ForecastProjection {
  lower: number[];
  median: number[];
  upper: number[];
}

export function projectTerminalRange(
  latestPrice: number,
  range: ForecastRange,
  steps: number,
): ForecastProjection {
  if (!Number.isFinite(latestPrice) || latestPrice <= 0) {
    throw new Error("latestPrice must be positive");
  }
  if (!Number.isInteger(steps) || steps < 1) {
    throw new Error("steps must be a positive integer");
  }
  if (range.p05 > range.p50 || range.p50 > range.p95) {
    throw new Error("forecast quantiles must be ordered");
  }

  const project = (terminalReturn: number) => (
    Array.from(
      { length: steps },
      (_value, index) => latestPrice * (1 + terminalReturn * ((index + 1) / steps)),
    )
  );
  return {
    lower: project(range.p05),
    median: project(range.p50),
    upper: project(range.p95),
  };
}

export function formatForecastEndpoint(
  quantile: string,
  price: number,
  terminalReturn: number,
) {
  const sign = terminalReturn >= 0 ? "+" : "";
  return `${quantile} ${price.toFixed(3)}\n${sign}${(terminalReturn * 100).toFixed(1)}%`;
}
