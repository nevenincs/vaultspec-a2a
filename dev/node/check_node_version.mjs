import { readFileSync } from "node:fs";

// `.node-version` lives at the REPOSITORY ROOT, where the version managers that
// read it look. This script sits two directories down, so the pin is `../../`
// from here — `../` resolved to `dev/.node-version`, which has never existed,
// and the read threw ENOENT before any version was compared. A crash inside the
// check reads as a broken toolchain rather than as a version mismatch, which is
// what it looked like when it took the whole `ci` recipe down with it.
const pin = new URL("../../.node-version", import.meta.url);

let required;
try {
  required = readFileSync(pin, "utf8").trim();
} catch (error) {
  console.error(
    `cannot read the Node.js pin at ${pin.pathname}: ${error.message}`,
  );
  process.exitCode = 1;
}

if (required !== undefined) {
  const current = process.versions.node;
  if (current !== required) {
    console.error(`Node.js ${required} is required; found ${current}.`);
    process.exitCode = 1;
  } else {
    console.log(`Node.js ${current} matches .node-version.`);
  }
}
