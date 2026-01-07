const { app, BrowserWindow, dialog } = require("electron");
const path = require("path");
const http = require("http");
const fs = require("fs");
const url = require("url");
const fetch = require("node-fetch");
const { spawn } = require("child_process");

// HTTP server to serve model files
let modelServer = null;
const MODEL_SERVER_PORT = 8766;
const MODELS_DIR = path.join(__dirname, "..", "models");

// Python API server URL (same as in index.html)
// Use 127.0.0.1 instead of localhost to force IPv4 and avoid IPv6 issues
const PYTHON_API_URL = "http://127.0.0.1:5000";

// Global reference to API server process
let apiServerProcess = null;

// Function to check if API server is running (using Node's http as fallback)
async function checkApiServer() {
  // Try using node-fetch first
  try {
    const timeoutPromise = new Promise((_, reject) => {
      setTimeout(() => reject(new Error("Timeout")), 2000);
    });

    const fetchPromise = fetch(`${PYTHON_API_URL}/health`);
    const response = await Promise.race([fetchPromise, timeoutPromise]);
    if (response.ok) {
      return true;
    }
  } catch (fetchError) {
    console.log(`⚠️ Fetch check failed: ${fetchError.message}`);
    if (fetchError.code) {
      console.log(`   Error code: ${fetchError.code}`);
    }
    if (fetchError.errno) {
      console.log(`   Error number: ${fetchError.errno}`);
    }

    // Fallback: Try using Node's http module with explicit IPv4
    try {
      const http = require("http");
      const url = require("url");
      const parsedUrl = url.parse(`${PYTHON_API_URL}/health`);

      return await new Promise((resolve) => {
        const req = http.request(
          {
            hostname: "127.0.0.1", // Force IPv4
            port: parsedUrl.port || 5000,
            path: parsedUrl.path,
            method: "GET",
            timeout: 2000,
            family: 4, // Force IPv4
          },
          (res) => {
            resolve(res.statusCode === 200);
          }
        );

        req.on("error", (error) => {
          console.log(`⚠️ HTTP check failed: ${error.message}`);
          if (error.code) {
            console.log(`   Error code: ${error.code}`);
          }
          resolve(false);
        });

        req.on("timeout", () => {
          console.log(`⚠️ HTTP check timed out`);
          req.destroy();
          resolve(false);
        });

        req.end();
      });
    } catch (httpError) {
      console.log(`⚠️ HTTP fallback also failed: ${httpError.message}`);
      return false;
    }
  }

  return false;
}

// Function to start the API server
function startApiServer() {
  return new Promise((resolve, reject) => {
    const apiServerPath = path.join(__dirname, "..", "api_server.py");

    if (!fs.existsSync(apiServerPath)) {
      reject(new Error(`API server file not found at: ${apiServerPath}`));
      return;
    }

    console.log("🚀 Starting FunctionGemma API server...");

    // Determine Python command (python3 or python)
    const pythonCmd = process.platform === "win32" ? "python" : "python3";

    apiServerProcess = spawn(pythonCmd, [apiServerPath], {
      cwd: path.join(__dirname, ".."),
      stdio: ["ignore", "pipe", "pipe"],
    });

    let serverReady = false;
    const maxWaitTime = 30000; // 30 seconds max wait
    const startTime = Date.now();

    // Check for server ready message
    apiServerProcess.stdout.on("data", (data) => {
      const output = data.toString();
      console.log(`[API Server] ${output.trim()}`);
      if (output.includes("Starting server") || output.includes("Running on")) {
        // Give it a moment to actually start
        setTimeout(() => {
          if (!serverReady) {
            serverReady = true;
            resolve();
          }
        }, 2000);
      }
    });

    apiServerProcess.stderr.on("data", (data) => {
      const output = data.toString();
      console.error(`[API Server Error] ${output.trim()}`);

      // Check for port conflict error
      if (output.includes("Port") && output.includes("in use")) {
        if (!serverReady) {
          serverReady = false;
          reject(
            new Error(
              "Port 5000 is already in use. Please:\n" +
              "1. Stop the other application using port 5000, OR\n" +
              "2. On macOS: Disable 'AirPlay Receiver' in System Settings > General > AirDrop & Handoff, OR\n" +
              "3. Manually start api_server.py on a different port"
            )
          );
        }
      }
    });

    apiServerProcess.on("error", (error) => {
      console.error("❌ Failed to start API server:", error);
      reject(error);
    });

    apiServerProcess.on("exit", (code) => {
      if (code !== 0 && !serverReady) {
        reject(new Error(`API server exited with code ${code}`));
      }
    });

    // Poll to check if server is ready
    const checkInterval = setInterval(async () => {
      if (Date.now() - startTime > maxWaitTime) {
        clearInterval(checkInterval);
        if (!serverReady) {
          reject(new Error("API server failed to start within timeout"));
        }
        return;
      }

      const isReady = await checkApiServer();
      if (isReady && !serverReady) {
        clearInterval(checkInterval);
        serverReady = true;
        console.log("✅ API server is ready!");
        resolve();
      }
    }, 1000); // Check every second
  });
}

// Cleanup API server on app quit
app.on("before-quit", () => {
  if (apiServerProcess) {
    console.log("🛑 Stopping API server...");
    apiServerProcess.kill();
    apiServerProcess = null;
  }
});

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

  win.loadFile("links.html");


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
