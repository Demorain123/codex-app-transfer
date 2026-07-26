import { spawn, spawnSync } from "node:child_process";
import { rename, rm, writeFile } from "node:fs/promises";
import { createServer } from "node:net";
import path from "node:path";
import { fileURLToPath } from "node:url";

const MODE = "micro-disabled-worker-safe";
const EXPECTED_MARKER = "codex-micro-disabled-worker-safe";
const fixDirectory = path.dirname(fileURLToPath(import.meta.url));
const statusPath = process.env.CAS_NO_MICRO_STATUS_PATH || path.join(fixDirectory, "last-launch.json");
const packageVersion = process.env.CAS_NO_MICRO_PACKAGE_VERSION || "unknown";
const executable = process.argv[2];
const extraArguments = process.argv.slice(3);

if (!executable) {
  throw new Error("Usage: node codex_no_micro_launcher.mjs <Codex executable> [extra arguments]");
}

const startedAt = new Date().toISOString();
let phase = "preflight";
let child = null;
let inspectorPort = null;

try {
  inspectorPort = await reservePort();
  phase = "spawn-child-with-inspector";
  child = await spawnCodex(executable, inspectorPort, extraArguments);

  phase = "inspector-connected";
  const inspectorUrl = await waitForInspector(inspectorPort, child, 15_000);

  phase = "stub-evaluated";
  const evaluation = await installStub(inspectorUrl, child.pid, executable);
  if (evaluation !== EXPECTED_MARKER) {
    throw new Error(`stub marker mismatch: ${String(evaluation)}`);
  }

  phase = "stub-marker-verified";
  await delay(700);
  if (!isPidAlive(child.pid)) {
    throw new Error(`Codex exited after resume (exit ${child.exitCode})`);
  }

  phase = "child-alive-verified";
  child.unref();
  const status = {
    schemaVersion: 1,
    mode: MODE,
    packageName: "OpenAI.Codex",
    packageVersion,
    startedAt,
    injectedAt: new Date().toISOString(),
    verifiedAliveAt: new Date().toISOString(),
    processId: child.pid,
    inspectorPort,
    executablePath: executable,
    nodeVersion: process.version,
    workerPolicy: "empty-execArgv-when-unspecified",
    injection: {
      status: "success",
      phase,
      evaluation,
      globalMarker: true,
    },
    cleanup: "not-needed",
    statusFile: { status: "success" },
  };
  const writeResult = await writeStatusBestEffort(status);
  if (!writeResult.ok) {
    status.statusFile = { status: "write-failed", error: writeResult.error };
  }
  process.stdout.write(`${JSON.stringify(status)}\n`);
  process.exitCode = 0;
} catch (error) {
  const cleanup = await cleanupOwnChild(child, executable);
  const status = {
    schemaVersion: 1,
    mode: MODE,
    packageName: "OpenAI.Codex",
    packageVersion,
    startedAt,
    failedAt: new Date().toISOString(),
    processId: child?.pid ?? null,
    inspectorPort,
    executablePath: executable,
    nodeVersion: process.version,
    workerPolicy: "empty-execArgv-when-unspecified",
    injection: {
      status: "failed",
      phase,
      error: safeError(error),
    },
    cleanup,
    statusFile: { status: "success" },
  };
  const writeResult = await writeStatusBestEffort(status);
  if (!writeResult.ok) {
    status.statusFile = { status: "write-failed", error: writeResult.error };
  }
  process.stdout.write(`${JSON.stringify(status)}\n`);
  process.exitCode = 1;
}

function normalizedExecutable(value) {
  return path.resolve(value).replaceAll("\\", "/").toLowerCase();
}

function safeError(error) {
  const text = error instanceof Error ? error.message : String(error);
  return text.replace(/(Bearer\s+)[A-Za-z0-9._~+\/-]{16,}={0,2}/gi, "$1***").slice(0, 1500);
}

function stubExpression(expectedPid, expectedExecutable) {
  const expectedPath = JSON.stringify(normalizedExecutable(expectedExecutable));
  return String.raw`
(() => {
  const actualPath = String(process.execPath || "").replaceAll("\\", "/").toLowerCase();
  if (process.pid !== ${expectedPid}) {
    throw new Error("No Micro inspector target PID mismatch");
  }
  if (actualPath !== ${expectedPath}) {
    throw new Error("No Micro inspector target executable mismatch");
  }

  const Module = process.getBuiltinModule("module");
  const originalLoad = Module._load;
  const isInspectorArgument = (argument) =>
    typeof argument === "string" && /^--inspect(?:-brk)?(?:=|$)/.test(argument);

  process.execArgv.splice(
    0,
    process.execArgv.length,
    ...process.execArgv.filter((argument) => !isInspectorArgument(argument)),
  );
  process.argv.splice(
    0,
    process.argv.length,
    ...process.argv.filter((argument) => !isInspectorArgument(argument)),
  );

  const workerThreads = process.getBuiltinModule("worker_threads");
  const NativeWorker = workerThreads.Worker;
  if (!NativeWorker.__codexNoInspectWrapper) {
    class CodexNoInspectWorker extends NativeWorker {
      constructor(filename, options = {}) {
        const safeOptions = options ?? {};
        super(filename, {
          ...safeOptions,
          execArgv: safeOptions.execArgv ?? [],
        });
      }
    }
    Object.defineProperty(CodexNoInspectWorker, "__codexNoInspectWrapper", {
      value: true,
    });
    workerThreads.Worker = CodexNoInspectWorker;
  }

  const stub = {
    __codexMicroDisabledLocal: true,
    ConnectionEventType: {
      CONNECTED: "CONNECTED",
      DISCONNECTED: "DISCONNECTED",
      ERROR: "ERROR",
    },
    DeviceType: { Project2077: "Project2077" },
    OAILightingEffect: { off: 0, breath: 1, solid: 2, snake: 3 },
    WLDeviceDiscovery: class NoCodexMicroDeviceDiscovery {
      findWLDevices() { return []; }
    },
    WLDeviceCommImpl: class NoCodexMicroDeviceComm {
      onConnectionEvent() { return () => {}; }
      async connect() {}
      async disconnect() {}
    },
    RPCApiOAI: class NoCodexMicroApi {
      onHidReceived() { return () => {}; }
      onJoystickMove() { return () => {}; }
      async sendLightingConfig() { return true; }
      async sendThreadsLighting() { return true; }
      async getDeviceStatus() { return {}; }
    },
  };

  Module._load = function codexMicroDisabledLoader(request, parent, isMain) {
    if (request === "@worklouder/device-kit-oai") return stub;
    return Reflect.apply(originalLoad, this, arguments);
  };

  globalThis.__CODEX_MICRO_DISABLED_LOCAL__ = true;
  setTimeout(() => {
    try { process.getBuiltinModule("inspector").close(); } catch {}
  }, 500);
  return "${EXPECTED_MARKER}";
})()
`;
}

async function reservePort() {
  const server = createServer();
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  const address = server.address();
  if (!address || typeof address === "string") {
    server.close();
    throw new Error("Could not reserve a loopback inspector port");
  }
  const selectedPort = address.port;
  await new Promise((resolve, reject) => {
    server.close((error) => (error ? reject(error) : resolve()));
  });
  return selectedPort;
}

async function spawnCodex(executablePath, port, args) {
  const spawned = spawn(
    executablePath,
    [`--inspect-brk=127.0.0.1:${port}`, ...args],
    {
      detached: true,
      env: process.env,
      stdio: "ignore",
      windowsHide: false,
    },
  );
  await new Promise((resolve, reject) => {
    const onError = (error) => {
      spawned.off("spawn", onSpawn);
      reject(new Error(`Codex spawn failed: ${safeError(error)}`));
    };
    const onSpawn = () => {
      spawned.off("error", onError);
      resolve();
    };
    spawned.once("error", onError);
    spawned.once("spawn", onSpawn);
  });
  if (!spawned.pid) throw new Error("Codex spawn succeeded without a PID");
  return spawned;
}

async function waitForInspector(portNumber, childProcess, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  let lastError = "inspector did not respond";

  while (Date.now() < deadline) {
    if (!isPidAlive(childProcess.pid)) {
      throw new Error(`Codex exited before the startup hook (exit ${childProcess.exitCode})`);
    }
    try {
      const response = await fetch(`http://127.0.0.1:${portNumber}/json/list`, {
        signal: AbortSignal.timeout(750),
      });
      if (response.ok) {
        const targets = await response.json();
        const candidates = Array.isArray(targets)
          ? targets.filter((entry) => typeof entry?.webSocketDebuggerUrl === "string")
          : [];
        if (candidates.length === 1) return candidates[0].webSocketDebuggerUrl;
        if (candidates.length > 1) lastError = `inspector returned ${candidates.length} targets`;
      } else {
        lastError = `inspector returned HTTP ${response.status}`;
      }
    } catch (error) {
      lastError = safeError(error);
    }
    await delay(100);
  }

  throw new Error(`Startup hook timed out: ${lastError}`);
}

async function installStub(webSocketUrl, expectedPid, expectedExecutable) {
  return await new Promise((resolve, reject) => {
    const socket = new WebSocket(webSocketUrl);
    let runtimeEnabled = false;
    let debuggerEnabled = false;
    let continuedToFirstLine = false;
    let callFrameId = null;
    let evaluationValue = null;
    let settled = false;

    const finishError = (error) => {
      if (settled) return;
      settled = true;
      clearTimeout(timeout);
      try { socket.close(); } catch {}
      reject(error instanceof Error ? error : new Error(String(error)));
    };
    const finishSuccess = () => {
      if (settled) return;
      settled = true;
      clearTimeout(timeout);
      resolve(evaluationValue);
      setTimeout(() => {
        try { socket.close(); } catch {}
      }, 150);
    };
    const timeout = setTimeout(() => {
      finishError(new Error("Startup hook WebSocket timed out"));
    }, 10_000);

    socket.addEventListener("error", () => {
      finishError(new Error("Startup hook WebSocket failed"));
    }, { once: true });
    socket.addEventListener("close", () => {
      if (!settled) finishError(new Error("Startup hook WebSocket closed before resume completed"));
    });

    socket.addEventListener("open", () => {
      socket.send(JSON.stringify({ id: 1, method: "Runtime.enable" }));
      socket.send(JSON.stringify({ id: 2, method: "Debugger.enable" }));
    }, { once: true });

    socket.addEventListener("message", (event) => {
      let message;
      try {
        message = JSON.parse(String(event.data));
      } catch (error) {
        finishError(new Error(`Invalid inspector JSON: ${safeError(error)}`));
        return;
      }
      if (message.error && message.id) {
        finishError(new Error(`Inspector command ${message.id} failed: ${safeError(message.error.message || message.error)}`));
        return;
      }
      if (message.id === 1) runtimeEnabled = true;
      if (message.id === 2) debuggerEnabled = true;

      if (runtimeEnabled && debuggerEnabled && !continuedToFirstLine) {
        continuedToFirstLine = true;
        socket.send(JSON.stringify({ id: 3, method: "Runtime.runIfWaitingForDebugger" }));
      }

      if (message.method === "Debugger.paused" && !callFrameId) {
        callFrameId = message.params?.callFrames?.[0]?.callFrameId ?? null;
        if (!callFrameId) {
          finishError(new Error("Startup hook did not receive a usable call frame"));
          return;
        }
        socket.send(JSON.stringify({
          id: 4,
          method: "Debugger.evaluateOnCallFrame",
          params: {
            callFrameId,
            expression: stubExpression(expectedPid, expectedExecutable),
            returnByValue: true,
            silent: false,
          },
        }));
        return;
      }

      if (message.id === 4) {
        const exception = message.result?.exceptionDetails;
        if (exception) {
          finishError(new Error(
            exception.exception?.description ?? exception.text ?? JSON.stringify(exception),
          ));
          return;
        }
        evaluationValue = message.result?.result?.value ?? null;
        if (evaluationValue !== EXPECTED_MARKER) {
          finishError(new Error(`stub evaluation returned unexpected marker: ${String(evaluationValue)}`));
          return;
        }
        socket.send(JSON.stringify({
          id: 5,
          method: "Debugger.evaluateOnCallFrame",
          params: {
            callFrameId,
            expression: "globalThis.__CODEX_MICRO_DISABLED_LOCAL__ === true",
            returnByValue: true,
            silent: true,
          },
        }));
        return;
      }

      if (message.id === 5) {
        if (message.result?.result?.value !== true) {
          finishError(new Error("global No Micro marker was not set"));
          return;
        }
        socket.send(JSON.stringify({ id: 6, method: "Debugger.resume" }));
        return;
      }

      if (message.id === 6) finishSuccess();
    });
  });
}

function isPidAlive(pid) {
  if (!Number.isInteger(pid) || pid <= 0) return false;
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

async function cleanupOwnChild(childProcess, expectedExecutable) {
  if (!childProcess?.pid) return "not-started";
  if (!isPidAlive(childProcess.pid)) return "already-exited";

  try {
    childProcess.kill("SIGKILL");
  } catch {}
  if (await waitForPidExit(childProcess.pid, 1200)) return "terminated-own-child";

  if (process.platform === "win32") {
    const ps = spawnSync(
      "powershell.exe",
      [
        "-NoLogo",
        "-NoProfile",
        "-NonInteractive",
        "-Command",
        [
          "$ErrorActionPreference = 'Stop'",
          "$pidToStop = [int]$env:CAS_NO_MICRO_CHILD_PID",
          "$expected = $env:CAS_NO_MICRO_EXPECTED_EXE",
          "$p = Get-CimInstance Win32_Process -Filter \"ProcessId=$pidToStop\"",
          "if ($null -eq $p) { exit 0 }",
          "if (-not $p.ExecutablePath) { exit 3 }",
          "if (-not [string]::Equals($p.ExecutablePath, $expected, [System.StringComparison]::OrdinalIgnoreCase)) { exit 4 }",
          "Stop-Process -Id $pidToStop -Force -ErrorAction Stop",
        ].join("; "),
      ],
      {
        stdio: "ignore",
        windowsHide: true,
        env: {
          ...process.env,
          CAS_NO_MICRO_CHILD_PID: String(childProcess.pid),
          CAS_NO_MICRO_EXPECTED_EXE: path.resolve(expectedExecutable),
        },
      },
    );
    if (ps.status === 0 && await waitForPidExit(childProcess.pid, 1600)) {
      return "terminated-own-child-powershell";
    }
  }

  return "cleanup-failed";
}

async function waitForPidExit(pid, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (!isPidAlive(pid)) return true;
    await delay(60);
  }
  return !isPidAlive(pid);
}

async function writeStatusBestEffort(status) {
  try {
    const temporaryPath = `${statusPath}.tmp`;
    await rm(temporaryPath, { force: true });
    await writeFile(temporaryPath, `${JSON.stringify(status, null, 2)}\n`, "utf8");
    try {
      await rename(temporaryPath, statusPath);
    } catch (error) {
      // Windows can reject rename-over-existing in some filesystem/AV combinations.
      // Status is diagnostic only, so replace the old breadcrumb and retry once.
      if (process.platform !== "win32") throw error;
      await rm(statusPath, { force: true });
      await rename(temporaryPath, statusPath);
    }
    return { ok: true };
  } catch (error) {
    return { ok: false, error: safeError(error) };
  }
}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
