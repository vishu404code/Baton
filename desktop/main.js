// Baton desktop app (Electron).
// Starts the Baton backend on this computer (127.0.0.1 only), then shows its UI in a window.
// Everything lives in one SQLite file inside the app's data folder. No Docker, no database server.

const { app, BrowserWindow, Menu, shell, dialog } = require('electron');
const { spawn, execFileSync } = require('child_process');
const fs = require('fs');
const http = require('http');
const net = require('net');
const os = require('os');
const path = require('path');

app.setName('Baton');
// Testing aid: BATON_DEBUG_PORT opens Chromium's remote-debugging port (localhost only) so the window can be inspected.
if (process.env.BATON_DEBUG_PORT) {
  app.commandLine.appendSwitch('remote-debugging-port', process.env.BATON_DEBUG_PORT);
  app.commandLine.appendSwitch('remote-debugging-address', '127.0.0.1');
}
const PREFERRED_PORT = 8765; // stable, so MCP configs given to other tools keep working
const START_TIMEOUT_MS = 5 * 60 * 1000; // the first launch installs Python packages

let win = null;
let backend = null;
let port = null;
let quitting = false;
const logTail = [];

if (!app.requestSingleInstanceLock()) {
  app.quit();
}
app.on('second-instance', () => {
  if (win) {
    if (win.isMinimized()) win.restore();
    win.focus();
  }
});

// --- Where things are -----------------------------------------------------------------------------------
const packaged = app.isPackaged;
const resources = packaged ? process.resourcesPath : path.resolve(__dirname, '..');
const uiDir = packaged ? path.join(resources, 'ui') : path.join(resources, 'frontend', 'dist');
const userData = app.getPath('userData');
const dataDir = path.join(userData, 'data');
const logDir = path.join(userData, 'logs');
const logFile = path.join(logDir, 'backend.log');

function backendDir() {
  if (!packaged) return path.join(resources, 'backend');
  // Packaged: run a writable copy (uv builds the project and its environment next to it).
  const src = path.join(resources, 'backend');
  const dst = path.join(userData, 'backend');
  const stamp = path.join(dst, '.baton-version');
  const want = app.getVersion();
  const have = fs.existsSync(stamp) ? fs.readFileSync(stamp, 'utf8').trim() : '';
  if (have !== want) {
    fs.rmSync(dst, { recursive: true, force: true });
    fs.cpSync(src, dst, { recursive: true });
    fs.writeFileSync(stamp, want);
  }
  return dst;
}

function findUv() {
  const candidates = [
    process.env.BATON_UV,
    path.join(os.homedir(), '.local', 'bin', 'uv'),
    '/opt/homebrew/bin/uv',
    '/usr/local/bin/uv',
    path.join(os.homedir(), '.cargo', 'bin', 'uv'),
  ].filter(Boolean);
  for (const c of candidates) if (fs.existsSync(c)) return c;
  try {
    const out = execFileSync('/bin/zsh', ['-lc', 'command -v uv'], { encoding: 'utf8', timeout: 5000 }).trim();
    if (out && fs.existsSync(out)) return out;
  } catch (_) {}
  return null;
}

function isPortFree(p) {
  return new Promise((resolve) => {
    const s = net.createServer();
    s.once('error', () => resolve(false));
    s.listen(p, '127.0.0.1', () => s.close(() => resolve(true)));
  });
}

async function pickPort() {
  if (await isPortFree(PREFERRED_PORT)) return PREFERRED_PORT;
  return new Promise((resolve, reject) => {
    const s = net.createServer();
    s.once('error', reject);
    s.listen(0, '127.0.0.1', () => {
      const p = s.address().port;
      s.close(() => resolve(p));
    });
  });
}

function healthy(p) {
  return new Promise((resolve) => {
    const req = http.get({ host: '127.0.0.1', port: p, path: '/health', timeout: 1500 }, (res) => {
      res.resume();
      resolve(res.statusCode === 200);
    });
    req.on('error', () => resolve(false));
    req.on('timeout', () => { req.destroy(); resolve(false); });
  });
}

function status(text, isError = false) {
  if (win && !win.isDestroyed()) {
    win.webContents.executeJavaScript(`window.setStatus && window.setStatus(${JSON.stringify(text)}, ${isError})`).catch(() => {});
  }
}

// --- Backend --------------------------------------------------------------------------------------------
function startBackend(uv, dir) {
  fs.mkdirSync(dataDir, { recursive: true });
  fs.mkdirSync(logDir, { recursive: true });
  const log = fs.createWriteStream(logFile, { flags: 'a' });
  log.write(`\n=== ${new Date().toISOString()} starting Baton backend on :${port}\n`);

  const env = {
    ...process.env,
    PATH: [path.dirname(uv), '/opt/homebrew/bin', '/usr/local/bin', '/usr/bin', '/bin', process.env.PATH || ''].join(':'),
    BATON_LOCAL_MODE: '1',
    BATON_STATIC_DIR: uiDir,
    BATON_DATA_DIR: dataDir,
    BATON_PUBLIC_URL: `http://127.0.0.1:${port}`,
    PYTHONUNBUFFERED: '1',
  };
  if (packaged) env.UV_PROJECT_ENVIRONMENT = path.join(userData, 'venv');

  const args = ['run', '--python', '3.12', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', String(port), '--log-level', 'info'];
  backend = spawn(uv, args, { cwd: dir, env, stdio: ['ignore', 'pipe', 'pipe'], detached: true });

  const onData = (buf) => {
    const text = buf.toString();
    log.write(text);
    text.split('\n').filter(Boolean).forEach((l) => {
      logTail.push(l);
      if (logTail.length > 25) logTail.shift();
    });
  };
  backend.stdout.on('data', onData);
  backend.stderr.on('data', onData);
  backend.on('exit', (code, signal) => {
    log.write(`=== backend exited (code ${code}, signal ${signal})\n`);
    backend = null;
    if (!quitting) {
      status(`Baton's engine stopped unexpectedly.\n\n${logTail.slice(-8).join('\n')}\n\nFull log: ${logFile}`, true);
    }
  });
}

function stopBackend() {
  if (backend && backend.pid) {
    try {
      process.kill(-backend.pid, 'SIGTERM'); // the whole group: uv and uvicorn
    } catch (_) {
      try { backend.kill('SIGTERM'); } catch (_) {}
    }
  }
}

async function waitUntilReady() {
  const t0 = Date.now();
  let shown = 0;
  while (Date.now() - t0 < START_TIMEOUT_MS) {
    if (await healthy(port)) return true;
    if (!backend) return false;
    const secs = Math.floor((Date.now() - t0) / 1000);
    if (secs >= 8 && secs - shown >= 4) {
      shown = secs;
      status(`Setting up Baton (first launch installs its Python packages; this can take a minute)…\n${secs}s\n\n${logTail.slice(-2).join('\n')}`);
    }
    await new Promise((r) => setTimeout(r, 400));
  }
  return false;
}

// --- Window ---------------------------------------------------------------------------------------------
function createWindow() {
  win = new BrowserWindow({
    width: 1440,
    height: 900,
    minWidth: 1000,
    minHeight: 640,
    backgroundColor: '#0B0C0F',
    title: 'Baton',
    webPreferences: { contextIsolation: true, nodeIntegration: false, sandbox: true },
  });
  win.loadFile(path.join(__dirname, 'loading.html'));
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https?:/i.test(url)) shell.openExternal(url);
    return { action: 'deny' };
  });
  win.webContents.on('will-navigate', (event, url) => {
    if (!url.startsWith(`http://127.0.0.1:${port}`) && !url.startsWith('file:')) {
      event.preventDefault();
      if (/^https?:/i.test(url)) shell.openExternal(url);
    }
  });
  win.on('closed', () => { win = null; });
}

function buildMenu() {
  const template = [
    { label: 'Baton', submenu: [{ role: 'about' }, { type: 'separator' }, { role: 'hide' }, { role: 'hideOthers' }, { role: 'unhide' }, { type: 'separator' }, { role: 'quit' }] },
    { role: 'editMenu' }, // copy / paste (needed to paste API keys)
    { label: 'View', submenu: [{ role: 'reload' }, { role: 'forceReload' }, { type: 'separator' }, { role: 'resetZoom' }, { role: 'zoomIn' }, { role: 'zoomOut' }, { type: 'separator' }, { role: 'toggleDevTools' }, { role: 'togglefullscreen' }] },
    { role: 'windowMenu' },
    {
      label: 'Help',
      submenu: [
        { label: 'Open data folder', click: () => shell.openPath(dataDir) },
        { label: 'Show engine log', click: () => shell.showItemInFolder(logFile) },
      ],
    },
  ];
  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

async function main() {
  buildMenu();
  createWindow();

  const uv = findUv();
  if (!uv) {
    status("Baton needs 'uv' (a small Python launcher) and couldn't find it.\n\nInstall it once in Terminal:\ncurl -LsSf https://astral.sh/uv/install.sh | sh\n\nthen open Baton again.", true);
    return;
  }
  if (!fs.existsSync(path.join(uiDir, 'index.html'))) {
    status(`The Baton interface isn't built yet (missing ${uiDir}).\nRun: npm run ui`, true);
    return;
  }

  try {
    port = await pickPort();
    startBackend(uv, backendDir());
  } catch (e) {
    status(`Couldn't start Baton: ${e.message}`, true);
    return;
  }

  if (await waitUntilReady()) {
    if (win) win.loadURL(`http://127.0.0.1:${port}/`);
  } else if (!quitting) {
    status(`Baton didn't start.\n\n${logTail.slice(-10).join('\n')}\n\nFull log: ${logFile}`, true);
  }
}

app.whenReady().then(main);
app.on('window-all-closed', () => app.quit());
app.on('before-quit', () => {
  quitting = true;
  stopBackend();
});
process.on('exit', stopBackend);
