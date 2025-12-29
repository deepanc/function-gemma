const { app, BrowserWindow } = require("electron");
const path = require("path");
const http = require("http");
const fs = require("fs");
const url = require("url");

// HTTP server to serve model files
let modelServer = null;
const MODEL_SERVER_PORT = 8766;
const MODELS_DIR = path.join(__dirname, "..", "models");

function startModelServer() {
  modelServer = http.createServer((req, res) => {
    // Handle CORS preflight
    if (req.method === "OPTIONS") {
      res.writeHead(200, {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type",
      });
      res.end();
      return;
    }

    // Parse the URL
    const parsedUrl = url.parse(req.url);
    let requestPath = parsedUrl.pathname;

    // Handle HuggingFace-style paths (e.g., /resolve/main/config.json -> /config.json)
    if (requestPath.includes("/resolve/main/")) {
      requestPath = requestPath.replace("/resolve/main/", "/");
    }

    // Remove leading slash for path joining
    const relativePath = requestPath.startsWith("/")
      ? requestPath.slice(1)
      : requestPath;
    let filePath = path.join(MODELS_DIR, relativePath);

    console.log(`📥 Request: ${req.url} -> ${filePath}`);

    // Security: ensure we're only serving from models directory
    const resolvedPath = path.resolve(filePath);
    const resolvedModelsDir = path.resolve(MODELS_DIR);
    if (!resolvedPath.startsWith(resolvedModelsDir)) {
      res.writeHead(403);
      res.end("Forbidden");
      return;
    }

    // Check if file exists
    fs.stat(filePath, (statErr, stats) => {
      if (statErr) {
        // If file doesn't exist, try without the path modification
        const altPath = path.join(MODELS_DIR, requestPath);
        fs.stat(altPath, (altErr, altStats) => {
          if (altErr) {
            console.log(`❌ File not found: ${filePath} or ${altPath}`);
            res.writeHead(404);
            res.end("File not found");
            return;
          }
          serveFile(altPath, res);
        });
        return;
      }

      // If directory, try index.html
      if (stats.isDirectory()) {
        filePath = path.join(filePath, "index.html");
      }

      serveFile(filePath, res);
    });
  });

  function serveFile(filePath, res) {
    // Read and serve the file
    fs.readFile(filePath, (err, data) => {
      if (err) {
        res.writeHead(404);
        res.end("File not found");
        return;
      }

      // Set appropriate content type
      const ext = path.extname(filePath);
      const contentTypes = {
        ".json": "application/json",
        ".txt": "text/plain",
        ".bin": "application/octet-stream",
        ".safetensors": "application/octet-stream",
        ".model": "application/octet-stream",
        ".jinja": "text/plain",
      };

      res.writeHead(200, {
        "Content-Type": contentTypes[ext] || "application/octet-stream",
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type",
      });
      res.end(data);
    });
  }

  modelServer.listen(MODEL_SERVER_PORT, () => {
    console.log(
      `📦 Model server started on http://localhost:${MODEL_SERVER_PORT}`
    );
  });

  // Cleanup on app quit
  app.on("before-quit", () => {
    if (modelServer) {
      modelServer.close();
    }
  });
}

function createWindow() {
  // Get absolute path to preload script
  const preloadPath = path.resolve(__dirname, "preload.js");

  // Verify preload file exists
  if (!fs.existsSync(preloadPath)) {
    console.error(`❌ Preload script not found at: ${preloadPath}`);
  } else {
    console.log(`✅ Preload script found at: ${preloadPath}`);
  }

  const win = new BrowserWindow({
    width: 600,
    height: 750,
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: true,
      preload: preloadPath,
    },
    backgroundColor: "#0f1419",
    titleBarStyle: "hiddenInset",
    resizable: true,
    minWidth: 450,
    minHeight: 600,
  });

  win.loadFile("index.html");
}

app.whenReady().then(() => {
  startModelServer();
  createWindow();
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});

app.on("activate", () => {
  if (BrowserWindow.getAllWindows().length === 0) {
    createWindow();
  }
});
