import { useEffect, useState } from "react";

export type Role = "visitor" | "admin" | "superadmin";
export type Access = {
  authenticated: boolean;
  role: Role | null;
  account?: { id: string; label: string; role: Role } | null;
  demo: boolean;
  keyless: boolean;
  csrf: string;
  limits: {
    seconds: number;
    file_mb: number;
    jobs_per_visitor: number;
    jobs_daily: number;
  };
};
export const roleLabels = {
  visitor: "방문자",
  admin: "관리자",
  superadmin: "운영 관리자",
};
let csrf = "";
export function accessHeaders(): Record<string, string> {
  const key = sessionStorage.getItem("stt-token");
  return {
    ...(key ? { Authorization: `Bearer ${key}` } : {}),
    ...(csrf ? { "X-CSRF-Token": csrf } : {}),
  };
}
const pending = new Map<string, Promise<Access>>();
function fetchAccess(credential: string): Promise<Access> {
  const existing = pending.get(credential);
  if (existing) return existing;
  const request = fetch("/api/access/session", {
    headers: credential ? { Authorization: `Bearer ${credential}` } : {},
  })
    .then(async (response) => {
      if (!response.ok)
        throw new Error("접속 정보를 확인하지 못했습니다. 새로고침해 주세요.");
      return response.json() as Promise<Access>;
    })
    .finally(() => pending.delete(credential));
  pending.set(credential, request);
  return request;
}
export function useAccess(credential: string) {
  const [access, setAccess] = useState<Access | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let alive = true;
    setAccess(null);
    setError("");
    fetchAccess(credential)
      .then((value) => {
        if (alive) {
          csrf = value.csrf;
          setAccess(value);
        }
      })
      .catch((e) => {
        if (alive) setError(String(e));
      });
    return () => {
      alive = false;
    };
  }, [credential]);
  return { access, error };
}
