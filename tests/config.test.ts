import { describe, expect, it } from "vitest";
import { ConfigError, parseConfig } from "@/lib/config";

const valid = {
  DATABASE_URL: "postgresql://u@localhost:5433/db",
  DATA_MODE: "mock",
  R6_DISSECT_BIN: "./vendor/bin/r6-dissect",
  UPLOAD_DIR: "./uploads",
  MAX_UPLOAD_MB: "200",
  MIN_SNAPSHOT_ROUNDS: "50",
  SNAPSHOT_DEBOUNCE_SECONDS: "10",
  ADMIN_TOKEN: "x".repeat(32),
};

describe("parseConfig", () => {
  it("accepts a valid config and converts numbers", () => {
    const cfg = parseConfig(valid);
    expect(cfg.DATA_MODE).toBe("mock");
    expect(cfg.MIN_SNAPSHOT_ROUNDS).toBe(50);
  });

  it("rejects an unsupported data mode instead of falling back", () => {
    expect(() => parseConfig({ ...valid, DATA_MODE: "scrape" })).toThrow(ConfigError);
  });

  it("rejects non-postgres database URLs", () => {
    expect(() => parseConfig({ ...valid, DATABASE_URL: "file:./dev.db" })).toThrow(/DATABASE_URL/);
  });

  it("rejects negative, fractional and non-numeric numbers", () => {
    for (const bad of ["-1", "1.5", "abc", ""]) {
      expect(() => parseConfig({ ...valid, MIN_SNAPSHOT_ROUNDS: bad })).toThrow(/MIN_SNAPSHOT_ROUNDS/);
    }
  });

  it("rejects a short admin token without echoing its value", () => {
    try {
      parseConfig({ ...valid, ADMIN_TOKEN: "secret123" });
      expect.unreachable();
    } catch (e) {
      expect(String(e)).toMatch(/ADMIN_TOKEN/);
      expect(String(e)).not.toContain("secret123");
    }
  });
});
