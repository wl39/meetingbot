import { describe, expect, it } from "vitest";
import { modelReady, type Health } from "./api";

const health: Health = {
  engine: "real",
  default_model: "large-v3-turbo",
  active_session: null,
  limits: { file_mb: 4096, file_seconds: 18000, live_seconds: 300 },
  workers: {
    asr: {
      ready: true,
      models: { small: { ready: true }, "large-v3-turbo": { ready: false } },
    },
  },
  environment: { machine: "test", system: "test" },
};

describe("selected transcription model readiness", () => {
  it("does not offer a pending or missing model just because another model is ready", () => {
    expect(modelReady(health, "small")).toBe(true);
    expect(modelReady(health, "large-v3-turbo")).toBe(false);
    expect(
      modelReady(
        { ...health, workers: { asr: { ready: true, models: {} } } },
        "small",
      ),
    ).toBe(false);
  });
  it("blocks new jobs while managed installation or activation is running", () => {
    expect(modelReady({ ...health, management_busy: true }, "small")).toBe(
      false,
    );
    expect(modelReady(null, "small")).toBe(false);
  });
  it("preserves fake-engine compatibility without per-model readiness", () => {
    expect(
      modelReady(
        { ...health, engine: "fake", workers: { asr: { ready: true } } },
        "large-v3-turbo",
      ),
    ).toBe(true);
    expect(
      modelReady({ ...health, workers: { asr: { ready: false } } }, "small"),
    ).toBe(false);
  });
});
