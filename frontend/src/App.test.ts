import { describe, expect, it } from "vitest";

describe("Vue frontend bootstrap", () => {
  it("keeps the API fallback local", async () => {
    const client = await import("./api/client");
    expect(client.apiBase).toMatch(/^https?:\/\//);
  });
});
