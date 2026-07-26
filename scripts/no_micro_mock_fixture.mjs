import { writeFile } from "node:fs/promises";

const outputPath = process.env.CAS_NO_MICRO_FIXTURE_RESULT;
if (!outputPath) throw new Error("CAS_NO_MICRO_FIXTURE_RESULT is required");

const Module = process.getBuiltinModule("module");
const stub = Module._load("@worklouder/device-kit-oai", undefined, false);
if (stub?.__codexMicroDisabledLocal !== true) {
  throw new Error("target module was not replaced by the No Micro stub");
}
if (globalThis.__CODEX_MICRO_DISABLED_LOCAL__ !== true) {
  throw new Error("global No Micro marker is missing");
}

// Resolve Worker only after the startup hook has run. A static ESM import is bound during
// module instantiation, before the first user call frame where --inspect-brk lets us inject.
// The No Micro mitigation is specifically about workers created through the post-hook builtin.
const Worker = process.getBuiltinModule("worker_threads").Worker;
const workerExecArgv = await new Promise((resolve, reject) => {
  const worker = new Worker(
    `const { parentPort } = require('node:worker_threads'); parentPort.postMessage(process.execArgv);`,
    { eval: true },
  );
  worker.once("message", resolve);
  worker.once("error", reject);
});

const inspectorArgs = workerExecArgv.filter(
  (arg) => typeof arg === "string" && /^--inspect(?:-brk)?(?:=|$)/.test(arg),
);
if (inspectorArgs.length !== 0) {
  throw new Error(`worker inherited inspector args: ${JSON.stringify(inspectorArgs)}`);
}

await writeFile(
  outputPath,
  `${JSON.stringify({
    ok: true,
    stub: stub.__codexMicroDisabledLocal,
    globalMarker: globalThis.__CODEX_MICRO_DISABLED_LOCAL__,
    workerExecArgv,
  })}\n`,
  "utf8",
);

// Give the parent launcher enough time to perform its post-resume alive check.
await new Promise((resolve) => setTimeout(resolve, 1800));
