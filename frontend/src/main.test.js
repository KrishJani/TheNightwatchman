import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const currentDirectory = dirname(fileURLToPath(import.meta.url));
const mainSource = readFileSync(join(currentDirectory, "main.jsx"), "utf8");

test("renders a How it works tab with the latency diagram image", () => {
  assert.match(mainSource, /setActiveTab\("how-it-works"\)/);
  assert.match(mainSource, />\s*How it works\s*</);
  assert.match(mainSource, /<img[^>]+src="\/static\/latency-diagram\.png"/);
});
