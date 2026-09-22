export type BrowserItem = { path: string; attention?: boolean };

export function directoryEntries<T extends BrowserItem>(
  items: T[],
  directory: string,
) {
  const prefix = directory ? directory + "/" : "";
  const folders = new Map<string, { path: string; name: string; files: T[] }>();
  const files: T[] = [];
  for (const item of items) {
    if (!item.path.startsWith(prefix)) continue;
    const relative = item.path.slice(prefix.length);
    const slash = relative.indexOf("/");
    if (slash < 0) files.push(item);
    else {
      const name = relative.slice(0, slash);
      const path = prefix + name;
      if (!folders.has(path)) folders.set(path, { path, name, files: [] });
      folders.get(path)!.files.push(item);
    }
  }
  return {
    folders: [...folders.values()].sort(
      (a, b) =>
        Number(b.files.some((f) => f.attention)) -
          Number(a.files.some((f) => f.attention)) ||
        a.name.localeCompare(b.name, "ko"),
    ),
    files: sortFiles(files),
  };
}

export function sortFiles<T extends BrowserItem>(items: T[]) {
  return [...items].sort(
    (a, b) =>
      Number(!!b.attention) - Number(!!a.attention) ||
      a.path.localeCompare(b.path, "ko"),
  );
}
