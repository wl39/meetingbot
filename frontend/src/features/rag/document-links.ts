// Resolve links within the document's workspace, never an arbitrary local file.
export function documentLink(basePath: string, href: string): string | null {
  if (/^(?:[a-z][\w+.-]*:|\/|#)/i.test(href)) return null;
  let target: string;
  try {
    target = decodeURIComponent(href.split(/[?#]/)[0]);
  } catch {
    return null;
  }
  if (!/\.(?:md|txt)$/i.test(target) || /[\\\x00-\x1f]/.test(target))
    return null;
  const parts = basePath.split("/").slice(0, -1);
  for (const part of target.split("/")) {
    if (!part || part === ".") continue;
    if (part === "..") {
      if (!parts.length) return null;
      parts.pop();
    } else parts.push(part);
  }
  return parts.join("/");
}
