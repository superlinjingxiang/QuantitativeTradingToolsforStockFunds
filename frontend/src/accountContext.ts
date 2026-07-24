export interface AccountFormState {
  plannedCapital: string;
  availableCash: string;
  holdingQuantity: string;
  averageCost: string;
  riskProfile: string;
}

const ACCOUNT_PREFIX = "chinaQuantVue:account:";

export function buildAccountContext(form: AccountFormState): Record<string, unknown> | null {
  const numericFields = [
    ["plannedCapital", form.plannedCapital],
    ["availableCash", form.availableCash],
    ["holdingQuantity", form.holdingQuantity],
    ["averageCost", form.averageCost],
  ] as const;
  if (!numericFields.some(([, value]) => String(value).trim() !== "")) return null;

  const result: Record<string, unknown> = {};
  for (const [key, value] of numericFields) {
    if (String(value).trim() !== "") result[key] = Number(value);
  }
  result.riskProfile = form.riskProfile || "standard";
  return result;
}

export function accountStorageKey(identifier: string): string {
  const normalized = String(identifier || "").trim().toUpperCase();
  if (!normalized) return "";
  const symbol = normalized.includes(":") ? normalized.split(":").at(-1) || normalized : normalized;
  return `${ACCOUNT_PREFIX}${symbol}`;
}

export function legacyAccountStorageKey(identifier: string): string {
  const normalized = String(identifier || "").trim().toUpperCase();
  return normalized ? `${ACCOUNT_PREFIX}${normalized}` : "";
}
