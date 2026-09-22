import { afterEach, expect, it, vi } from "vitest";
import { setCsrf, uploadFile } from "./api";

vi.mock("../../workspace/access", () => ({
  accessHeaders: () => ({ "X-CSRF-Token": "visitor-session-csrf" }),
}));
afterEach(() => {
  vi.unstubAllGlobals();
  setCsrf("");
});

it("sends one CSRF header for a cookie-authenticated visitor upload", async () => {
  const headers: [string, string][] = [];
  class UploadRequest {
    upload = {};
    status = 200;
    onload = () => {};
    open() {}
    setRequestHeader(name: string, value: string) {
      headers.push([name, value]);
    }
    send() {
      this.onload();
    }
    abort() {}
  }
  vi.stubGlobal("XMLHttpRequest", UploadRequest);
  setCsrf("rag-session-csrf");
  await uploadFile(
    "/uploads/test/files/test",
    { size: 4 } as File,
    new AbortController().signal,
    () => {},
  );
  expect(headers.filter(([name]) => name === "X-CSRF-Token")).toEqual([
    ["X-CSRF-Token", "rag-session-csrf"],
  ]);
});
