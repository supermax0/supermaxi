import { describe, expect, it } from "vitest";
import { buildApp } from "../src/app.js";

describe("health route", () => {
  it("returns service status", async () => {
    const app = buildApp();
    const response = await app.inject({ method: "GET", url: "/health" });
    expect(response.statusCode).toBe(200);
    const json = response.json();
    expect(json.success).toBe(true);
    expect(json.status).toBe("ok");
    await app.close();
  });
});
