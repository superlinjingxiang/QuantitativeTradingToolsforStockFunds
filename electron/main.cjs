const { app, BrowserWindow, Menu } = require("electron");
const { spawn } = require("node:child_process");
const net = require("node:net");
const path = require("node:path");
const fs = require("node:fs");

let backendProcess = null;
let mainWindow = null;

app.disableHardwareAcceleration();
app.commandLine.appendSwitch("disable-gpu");

function debugLog(rootDir, message) {
  try {
    const logPath = path.join(rootDir, "logs", "electron-main.log");
    fs.mkdirSync(path.dirname(logPath), { recursive: true });
    fs.appendFileSync(logPath, `${new Date().toISOString()} ${message}\n`, "utf8");
  } catch {
    // Logging must not block app startup.
  }
}

function findPython(rootDir) {
  if (process.env.CHINA_QUANT_PYTHON) {
    return process.env.CHINA_QUANT_PYTHON;
  }
  const localPython = path.join(rootDir, ".venv", "Scripts", "python.exe");
  if (fs.existsSync(localPython)) {
    return localPython;
  }
  return "python";
}

function findFreePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      const port = address.port;
      server.close(() => resolve(port));
    });
    server.on("error", reject);
  });
}

async function startBackend(rootDir) {
  const port = await findFreePort();
  const python = findPython(rootDir);
  const backendModule = process.env.CHINA_QUANT_BACKEND_MODULE || "china_quant_platform.api";
  const env = {
    ...process.env,
    PYTHONPATH: path.join(rootDir, "src"),
    PYTHONUTF8: "1"
  };
  backendProcess = spawn(
    python,
    ["-m", backendModule, "--host", "127.0.0.1", "--port", String(port)],
    {
      cwd: rootDir,
      env,
      windowsHide: true,
      stdio: ["ignore", "pipe", "pipe"]
    }
  );

  const apiBase = `http://127.0.0.1:${port}`;
  return new Promise((resolve, reject) => {
    let settled = false;
    const timeout = setTimeout(() => {
      if (!settled) {
        settled = true;
        reject(new Error("Python 后端启动超时"));
      }
    }, 30000);

    backendProcess.stdout.on("data", (chunk) => {
      const text = chunk.toString("utf8");
      process.stdout.write(text);
      if (!settled && text.includes("CHINA_QUANT_BACKEND_READY")) {
        settled = true;
        clearTimeout(timeout);
        resolve(apiBase);
      }
    });
    backendProcess.stderr.on("data", (chunk) => {
      process.stderr.write(chunk.toString("utf8"));
    });
    backendProcess.on("exit", (code) => {
      if (!settled) {
        settled = true;
        clearTimeout(timeout);
        reject(new Error(`Python 后端退出，code=${code}`));
      }
    });
  });
}

async function createWindow() {
  const rootDir = process.cwd();
  const apiBase = await startBackend(rootDir);
  const legacyFrontend = process.env.CQP_FRONTEND === "legacy";
  const devUrl = process.env.VITE_DEV_SERVER_URL;
  Menu.setApplicationMenu(null);
  mainWindow = new BrowserWindow({
    width: 1680,
    height: 1000,
    minWidth: 1180,
    minHeight: 760,
    show: false,
    backgroundColor: "#080c12",
    title: "中国股票与基金量化分析平台",
    webPreferences: {
      preload: path.join(rootDir, "electron", "preload.cjs"),
      additionalArguments: [`--api-base=${apiBase}`],
      contextIsolation: true,
      nodeIntegration: false
    }
  });
  mainWindow.once("ready-to-show", () => {
    mainWindow.show();
    mainWindow.focus();
  });
  const indexPath = legacyFrontend
    ? path.join(rootDir, "electron", "index.html")
    : path.join(rootDir, "frontend", "dist", "index.html");
  mainWindow.webContents.on("did-fail-load", (_event, code, description, url) => {
    debugLog(rootDir, `did-fail-load code=${code} description=${description} url=${url}`);
  });
  mainWindow.webContents.on("render-process-gone", (_event, details) => {
    debugLog(rootDir, `render-process-gone ${JSON.stringify(details)}`);
  });
  if (devUrl && !legacyFrontend) {
    await mainWindow.loadURL(devUrl);
  } else if (fs.existsSync(indexPath)) {
    await mainWindow.loadFile(indexPath);
  } else {
    debugLog(rootDir, `Vue build missing, falling back to legacy UI: ${indexPath}`);
    await mainWindow.loadFile(path.join(rootDir, "electron", "index.html"));
  }
}

app.whenReady().then(createWindow).catch((error) => {
  console.error(error);
  app.quit();
});

app.on("window-all-closed", () => {
  app.quit();
});

app.on("before-quit", () => {
  if (backendProcess && !backendProcess.killed) {
    backendProcess.kill();
  }
});
