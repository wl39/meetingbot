import { useEffect, useRef, useState } from "react";
import { defaults, type Health, type Options } from "./api";

/** Apply a changed installation default between jobs; preserve per-recording choices. */
export function useTranscriptionOptions(health: Health | null, busy: boolean) {
  const [options, setOptions] = useState<Options>(() => ({
    ...defaults,
    model: health?.default_model ?? defaults.model,
  }));
  const appliedDefault = useRef(health?.default_model);
  const managedDefault = health?.default_model;
  useEffect(() => {
    if (!managedDefault || busy || managedDefault === appliedDefault.current)
      return;
    appliedDefault.current = managedDefault;
    setOptions((current) => ({ ...current, model: managedDefault }));
  }, [managedDefault, busy]);
  return [options, setOptions] as const;
}
