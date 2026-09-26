import assert from "node:assert/strict";
import { test } from "node:test";
import { safeReturnPath } from "./pairing.ts";

test("keeps a same-origin app route with query and hash", () => {
  assert.equal(
    safeReturnPath("/demo/agents/ops?tab=runs#latest"),
    "/demo/agents/ops?tab=runs#latest",
  );
});

test("rejects external, protocol-relative, backslash and control-character redirects", () => {
  for (const path of [
    "https://evil.example/",
    "//evil.example/",
    "/\\evil.example/",
    "/\nevil.example/",
    "javascript:alert(1)",
  ]) {
    assert.equal(safeReturnPath(path), "/", path);
  }
});

test("rejects pairing and API paths as return targets", () => {
  for (const path of ["/pair", "/pair?again=1", "/api/agents", "/artifacts/runs/x"]) {
    assert.equal(safeReturnPath(path), "/", path);
  }
});
