import { readFileSync } from "node:fs";

const required = readFileSync(
  new URL("../.node-version", import.meta.url),
  "utf8",
).trim();
const current = process.versions.node;

if (current !== required) {
  console.error(`Node.js ${required} is required; found ${current}.`);
  process.exitCode = 1;
} else {
  console.log(`Node.js ${current} matches .node-version.`);
}
