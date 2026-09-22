import { describe, expect, it } from "vitest";
import { themeTokens, validColor } from "./theme";

describe("global theme colors", () => {
  it("accepts only six-digit colors", () => {
    expect(validColor("#F57C00")).toBe(true);
    for (const color of ["red", "#fff", "#000000;display:none", "#12345678"])
      expect(validColor(color)).toBe(false);
  });
  it("keeps white button text readable across bright and dark custom colors", () => {
    for (const color of [
      "#ffffff",
      "#ffff00",
      "#00ff00",
      "#00ffff",
      "#b85c12",
      "#000000",
      "#ff00ff",
    ]) {
      const primary = themeTokens(color)["--theme-primary"];
      const channels = [1, 3, 5].map(
        (i) => parseInt(primary.slice(i, i + 2), 16) / 255,
      );
      const l = channels.reduce(
        (sum, x, i) =>
          sum +
          (x <= 0.04045 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4) *
            [0.2126, 0.7152, 0.0722][i],
        0,
      );
      expect(1.05 / (l + 0.05)).toBeGreaterThanOrEqual(4.5);
    }
  });
});
