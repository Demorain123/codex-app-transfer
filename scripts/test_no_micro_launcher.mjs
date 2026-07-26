import { spawn } from "node:child_process";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const launcher = path.join(root, "src-tauri", "resources", "codex_no_micro_launcher.mjs");
const fixture = path.join(root, "scripts", "no_micro_mock_fixture.mjs");
const tempDir = await mkdtemp(path.join(os.tmpdir(), "cas-no-micro-"));
const statusPath = path.join(tempDir, "last-launch.json");
const fixtureResult = path.join(tempDir, "fixture-result.json");

try {
  const result = await run(process.execPath, [launcher, process.execPath, fixture], {
    ...process.env,
    CAS_NO_MICRO_STATUS_PATH: statusPath,
    CAS_NO_MICRO_PACKAGE_VERSION: "mock",
    CAS_NO_MICRO_FIXTURE_RESULT: fixtureResult,
  });
  if (result.code !== 0) {
    throw new Error(`launcher failed (${result.code}): ${result.stderr || result.stdout}`);
  }

  const launch = JSON.parse(result.stdout.trim());
  if (launch?.injection?.status !== "success") {
    throw new Error(`launcher did not report success: ${result.stdout}`);
  }
  if (launch?.injection?.evaluation !== "codex-micro-disabled-worker-safe") {
    throw new Error(`unexpected marker: ${launch?.injection?.evaluation}`);
  }

  const status = JSON.parse(await readFile(statusPath, "utf8"));
  if (status?.injection?.status !== "success") {
    throw new Error("status file did not preserve successful injection");
  }

  const fixtureOutput = JSON.parse(await waitRead(fixtureResult, 3000));
  if (!fixtureOutput.ok || !fixtureOutput.stub || !fixtureOutput.globalMarker) {
    throw new Error(`fixture validation failed: ${JSON.stringify(fixtureOutput)}`);
  }
  if (fixtureOutput.workerExecArgv.some((arg) => /^--inspect(?:-brk)?(?:=|$)/.test(arg))) {
    throw new Error(`worker inherited inspector args: ${JSON.stringify(fixtureOutput.workerExecArgv)}`);
  }

  console.log("No Micro mock: injection marker, target-module stub and Worker execArgv all verified");
} finally {
  await rm(tempDir, { recursive: true, force: true });
}

async function waitRead(file, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  let lastError;
  while (Date.now() < deadline) {
    try {
      return await readFile(file, "utf8");
    } catch (error) {
      lastError = error;
      await new Promise((resolve) => setTimeout(resolve, 50));
    }
  }
  throw lastError ?? new Error(`timed out reading ${file}`);
}

function run(program, args, env) {
  return new Promise((resolve, reject) => {
    const child = spawn(program, args, {
      cwd: root,
      env,
      stdio: ["ignore", "pipe", "pipe"],
      windowsHide: true,
    });
    let stdout = "";
    let stderr = "";
    child.stdout.setEncoding("utf8");
    child.stderr.setEncoding("utf8");
    child.stdout.on("data", (chunk) => (stdout += chunk));
    child.stderr.on("data", (chunk) => (stderr += chunk));
    child.once("error", reject);
    child.once("exit", (code) => resolve({ code, stdout, stderr }));
  });
}
