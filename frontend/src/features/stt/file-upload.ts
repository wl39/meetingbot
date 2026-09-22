import { api } from "./api";

// Read top-level MP4 atom headers using small local slices. A moov atom after
// mdat must arrive first so the server can seek while audio is still uploading.
export async function uploadOrder(
  file: File,
  chunkBytes: number,
): Promise<number[]> {
  const count = Math.ceil(file.size / chunkBytes);
  const priority = new Set<number>([0, count - 1]);
  if (/\.m4a$/i.test(file.name)) {
    let offset = 0;
    for (let atoms = 0; offset + 8 <= file.size && atoms < 1024; atoms++) {
      const buffer = await file.slice(offset, offset + 16).arrayBuffer();
      const view = new DataView(buffer);
      let length = view.getUint32(0);
      const type = String.fromCharCode(...new Uint8Array(buffer, 4, 4));
      if (length === 1) {
        if (buffer.byteLength < 16) break;
        length = Number(view.getBigUint64(8));
      } else if (length === 0) length = file.size - offset;
      if (
        !Number.isSafeInteger(length) ||
        length < 8 ||
        offset + length > file.size
      )
        break;
      if (type === "moov") {
        for (
          let i = Math.floor(offset / chunkBytes);
          i <= Math.floor((offset + length - 1) / chunkBytes);
          i++
        )
          priority.add(i);
        break;
      }
      offset += length;
    }
  }
  return [
    ...priority,
    ...Array.from({ length: count }, (_, i) => i).filter(
      (i) => !priority.has(i),
    ),
  ].filter((i) => i >= 0);
}

export async function uploadFileChunks(
  file: File,
  sid: string,
  chunkBytes: number,
  signal: AbortSignal,
  onProgress: (value: number) => void,
) {
  let sent = 0;
  for (const index of await uploadOrder(file, chunkBytes)) {
    const chunk = file.slice(index * chunkBytes, (index + 1) * chunkBytes);
    await api(`/files/${sid}/chunks/${index}`, {
      method: "PUT",
      body: chunk,
      signal,
      headers: { "Content-Type": "application/octet-stream" },
    });
    sent += chunk.size;
    onProgress(Math.round((sent / file.size) * 100));
  }
  await api(`/files/${sid}/finish`, { method: "POST", signal });
}
