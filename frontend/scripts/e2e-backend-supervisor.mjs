import { mkdirSync, readFileSync, unlinkSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { spawn } from "node:child_process";

const frontendRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const repositoryRoot = resolve(frontendRoot, "..");
const runtimeDir = resolve(frontendRoot, ".e2e-runtime");
const restartSignal = resolve(runtimeDir, "restart-backend");
const generationFile = resolve(runtimeDir, "backend-generation");
const workspaceDb = resolve(runtimeDir, "workspace.sqlite3");
let child;
let generation = 0;
let restarting = false;

mkdirSync(runtimeDir, { recursive: true });
for (const runtimeFile of [
  restartSignal,
  workspaceDb,
  `${workspaceDb}-shm`,
  `${workspaceDb}-wal`
]) {
  try {
    unlinkSync(runtimeFile);
  } catch {
    // Runtime files only exist after a previous test suite.
  }
}

function startBackend() {
  generation += 1;
  writeFileSync(generationFile, String(generation), "utf8");
  child = spawn(
    resolve(repositoryRoot, ".venv/bin/open-novel"),
    ["serve", "--host", "127.0.0.1", "--port", "8875"],
    {
      cwd: repositoryRoot,
      env: {
        ...process.env,
        OPEN_NOVEL_DB_PATH: workspaceDb,
        OPEN_NOVEL_INCLUDE_TEMP_PROJECTS: "1"
      },
      stdio: "inherit"
    }
  );
}

async function stopBackend() {
  if (!child || child.exitCode !== null) return;
  const stopped = new Promise((resolveStopped) => child.once("exit", resolveStopped));
  child.kill("SIGTERM");
  await stopped;
}

async function restartBackend() {
  if (restarting) return;
  restarting = true;
  try {
    unlinkSync(restartSignal);
    await stopBackend();
    startBackend();
  } finally {
    restarting = false;
  }
}

startBackend();
const watcher = setInterval(() => {
  try {
    if (readFileSync(restartSignal, "utf8").trim()) void restartBackend();
  } catch {
    // The signal file only exists while a restart is requested.
  }
}, 100);

async function shutdown() {
  clearInterval(watcher);
  await stopBackend();
  process.exit(0);
}

process.once("SIGINT", () => void shutdown());
process.once("SIGTERM", () => void shutdown());
