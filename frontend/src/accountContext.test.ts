import { describe, expect, it } from "vitest";
import { accountStorageKey, buildAccountContext, legacyAccountStorageKey } from "./accountContext";

const emptyForm = {
  plannedCapital: "",
  availableCash: "",
  holdingQuantity: "",
  averageCost: "",
  riskProfile: "standard",
};

describe("manual account context", () => {
  it("does not connect an account when only the default risk profile exists", () => {
    expect(buildAccountContext(emptyForm)).toBeNull();
  });

  it("sends holdings, cost and risk profile to the current analysis request", () => {
    expect(buildAccountContext({
      plannedCapital: "10000",
      availableCash: "2500",
      holdingQuantity: "2800",
      averageCost: "2.61",
      riskProfile: "conservative",
    })).toEqual({
      plannedCapital: 10000,
      availableCash: 2500,
      holdingQuantity: 2800,
      averageCost: 2.61,
      riskProfile: "conservative",
    });
  });

  it("uses one symbol key for plain and exchange-qualified searches", () => {
    expect(accountStorageKey("513300")).toBe("chinaQuantVue:account:513300");
    expect(accountStorageKey("SSE:513300")).toBe("chinaQuantVue:account:513300");
    expect(legacyAccountStorageKey("SSE:513300")).toBe("chinaQuantVue:account:SSE:513300");
  });
});
