import { useSyncExternalStore } from "react";

export const DEFAULT_THEME = "#b85c12";
let current = DEFAULT_THEME;
let revision = 0;
const listeners = new Set<() => void>();
export const validColor = (value: string) => /^#[\da-f]{6}$/i.test(value);

export function themeTokens(color: string) {
  const rgb = [1, 3, 5].map((i) => parseInt(color.slice(i, i + 2), 16) / 255);
  const max = Math.max(...rgb),
    min = Math.min(...rgb),
    delta = max - min;
  const light = (max + min) / 2;
  const saturation = delta ? delta / (1 - Math.abs(2 * light - 1)) : 0;
  const [r, g, b] = rgb;
  const hue =
    delta === 0
      ? 0
      : ((max === r
          ? (g - b) / delta
          : max === g
            ? (b - r) / delta + 2
            : (r - g) / delta + 4) *
          60 +
          360) %
        360;
  // Keep white button labels legible even when a very light accent is selected.
  const luminance = (channels: number[]) =>
    channels.reduce(
      (sum, channel, i) =>
        sum +
        (channel <= 0.04045
          ? channel / 12.92
          : ((channel + 0.055) / 1.055) ** 2.4) *
          [0.2126, 0.7152, 0.0722][i],
      0,
    );
  let shade = [...rgb];
  while (1.05 / (luminance(shade) + 0.05) < 4.5)
    shade = shade.map((v) => v * 0.96);
  const hex = (values: number[]) =>
    "#" +
    values
      .map((v) =>
        Math.floor(v * 255)
          .toString(16)
          .padStart(2, "0"),
      )
      .join("");
  return {
    "--theme-hue": String(hue),
    "--theme-chroma": String(Math.min(1, saturation / 0.82)),
    "--theme-primary": hex(shade),
    "--theme-primary-hover": hex(shade.map((v) => v * 0.82)),
  };
}

export function applyTheme(color: string) {
  if (!validColor(color)) return;
  current = color.toLowerCase();
  revision++;
  Object.entries(themeTokens(current)).forEach(([name, value]) =>
    document.documentElement.style.setProperty(name, value),
  );
  listeners.forEach((notify) => notify());
}

let pending: Promise<void> | null = null;
export function refreshTheme() {
  if (pending) return pending;
  const before = revision;
  pending = fetch("/api/system/theme")
    .then(async (response) => {
      if (!response.ok) throw new Error("테마 설정을 불러오지 못했습니다.");
      const value = await response.json();
      if (
        before === revision &&
        validColor(value.color) &&
        current !== value.color
      )
        applyTheme(value.color);
    })
    .finally(() => {
      pending = null;
    });
  return pending;
}

export function useThemeColor() {
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    () => current,
  );
}
