export type UploadLimits = {
  extensions: string[];
  max_files: number;
  max_file_bytes: number;
  max_total_bytes: number;
  max_depth: number;
  session_hours: number;
};
export type PickedFile = { file: File; path: string; reason?: string };
const excluded = new Set([
  "node_modules",
  "venv",
  "__pycache__",
  "dist",
  "build",
  "target",
  "models",
  "credentials",
  "secrets",
  "id_rsa",
  "id_ed25519",
  "package-lock.json",
  "uv.lock",
  "admin-token",
  "local-token",
]);
export function selectFolder(
  files: File[],
  limits: UploadLimits,
  selected?: ReadonlySet<string>,
) {
  const folder = files[0]?.webkitRelativePath.split("/")[0] || "업로드 자료";
  const seen = new Set<string>();
  const picked: PickedFile[] = files.map((file) => {
    const full = file.webkitRelativePath;
    const path = full ? full.split("/").slice(1).join("/") : file.name;
    const parts = path.split("/");
    let reason: string | undefined;
    if (full && full.split("/")[0] !== folder)
      reason = "하나의 폴더를 선택하세요";
    if (parts.some((p) => !p || p === ".." || /[%\\:\x00-\x1f]/.test(p)))
      reason = "허용되지 않는 파일 경로";
    if (
      parts.some(
        (p) =>
          p.startsWith(".") ||
          p.startsWith("~") ||
          excluded.has(p.toLowerCase()) ||
          /^(credentials|secrets|token|auth)\./i.test(p),
      )
    )
      reason = "숨김·보호·임시 파일";
    if (
      !limits.extensions.includes(
        "." + file.name.split(".").pop()?.toLowerCase(),
      )
    )
      reason ||= "지원하지 않는 형식";
    if (parts.length > limits.max_depth) reason ||= "하위 폴더 깊이 제한 초과";
    if (file.size > limits.max_file_bytes) reason ||= "파일 크기 제한 초과";
    const canonical = path.normalize("NFC").toLowerCase();
    if (seen.has(canonical)) reason ||= "중복된 파일 이름";
    if (!reason) seen.add(canonical);
    return { file, path, reason };
  });
  const accepted = picked.filter(
    (f) => !f.reason && (!selected || selected.has(f.path)),
  );
  const bytes = accepted.reduce((n, f) => n + f.file.size, 0);
  const folders = new Set(
    accepted.flatMap((f) => {
      const parts = f.path.split("/");
      return parts.slice(0, -1).map((_, i) => parts.slice(0, i + 1).join("/"));
    }),
  );
  const error = !accepted.length
    ? selected
      ? "업로드할 파일을 선택하세요."
      : "업로드할 지원 파일이 없습니다."
    : accepted.length + folders.size > limits.max_files
      ? `파일과 하위 폴더를 합해 ${limits.max_files.toLocaleString()}개까지 올릴 수 있습니다.`
      : bytes > limits.max_total_bytes
        ? "폴더의 전체 업로드 크기 제한을 초과했습니다."
        : "";
  return { folder, picked, accepted, bytes, error };
}
export const formatBytes = (bytes: number) =>
  bytes >= 1024 * 1024
    ? `${(bytes / 1024 / 1024).toFixed(1)} MB`
    : `${(bytes / 1024).toFixed(1)} KB`;
