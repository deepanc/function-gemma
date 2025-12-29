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

// Function schemas for FunctionGemma (same as in index.html)
const formFunctionSchemas = [
  {
    type: "function",
    function: {
      name: "set_user_name",
      description: "Sets the user's full name in the registration form.",
      parameters: {
        type: "object",
        properties: {
          name: { type: "string", description: "The user's full name." },
        },
        required: ["name"],
      },
    },
  },
  {
    type: "function",
    function: {
      name: "set_user_age",
      description: "Sets the user's age in the registration form.",
      parameters: {
        type: "object",
        properties: {
          age: {
            type: "string",
            description: "The user's age as a number string.",
          },
        },
        required: ["age"],
      },
    },
  },
  {
    type: "function",
    function: {
      name: "set_user_sex",
      description: "Sets the user's sex/gender in the registration form.",
      parameters: {
        type: "object",
        properties: {
          sex: {
            type: "string",
            description: "The user's sex: 'male', 'female', or 'other'.",
          },
        },
        required: ["sex"],
      },
    },
  },
  {
    type: "function",
    function: {
      name: "set_user_address",
      description: "Sets the user's address in the registration form.",
      parameters: {
        type: "object",
        properties: {
          address: { type: "string", description: "The user's address." },
        },
        required: ["address"],
      },
    },
  },
  {
    type: "function",
    function: {
      name: "set_user_pincode",
      description: "Sets the user's pincode in the registration form.",
      parameters: {
        type: "object",
        properties: {
          pincode: {
            type: "string",
            description: "The user's 6-digit pincode.",
          },
        },
        required: ["pincode"],
      },
    },
  },
  {
    type: "function",
    function: {
      name: "submit_form",
      description:
        "Submits the registration form. This should be called last after all fields are filled.",
      parameters: {
        type: "object",
        properties: {},
        required: [],
      },
    },
  },
];

// Run Selenium tests using FunctionGemma
async function runSeleniumTests() {
  try {
    // Show testing message
    const win = BrowserWindow.getFocusedWindow();
    if (win) {
      const response = await dialog.showMessageBox(win, {
        type: "info",
        title: "Testing Application",
        message: "Running Selenium tests with FunctionGemma...",
        detail:
          "The browser will open, perform test actions based on natural language test cases, and then close automatically.",
        buttons: ["OK", "Cancel"],
      });

      if (response.response === 1) {
        // User clicked Cancel
        console.log("❌ User cancelled test execution");
        return;
      }
    }

    // Load test cases from file or use default
    const testCasesPath = path.join(__dirname, "test-cases.json");
    let testCases = [];

    if (fs.existsSync(testCasesPath)) {
      try {
        const testCasesData = fs.readFileSync(testCasesPath, "utf-8");
        const testCasesJson = JSON.parse(testCasesData);
        testCases = testCasesJson.test_cases || [];
        console.log(
          `✅ Loaded ${testCases.length} test case(s) from test-cases.json`
        );
      } catch (error) {
        console.error("❌ Error reading test-cases.json:", error);
      }
    }

    // Default test case if file doesn't exist or is empty
    if (testCases.length === 0) {
      testCases = [
        {
          name: "Default Test",
          description: "Basic form fill test",
          natural_language:
            "My name is Test User, I am 25 years old, male, I live at 123 Test Street, pincode 12345, submit the form",
        },
      ];
      console.log("⚠️ No test cases found, using default test case");
    }

    // Check if API server is running, start it if not
    console.log(`🔍 Checking if API server is running at ${PYTHON_API_URL}...`);
    const isServerRunning = await checkApiServer();

    if (!isServerRunning) {
      console.log("⚠️ API server not running, attempting to start it...");

      try {
        await startApiServer();
        console.log("✅ API server started successfully");

        // Double-check it's actually accessible
        const doubleCheck = await checkApiServer();
        if (!doubleCheck) {
          throw new Error("API server started but health check still failing");
        }
      } catch (error) {
        const errorMsg = `Failed to start API server: ${error.message}\n\nPlease make sure:\n1. Python 3 is installed\n2. Dependencies are installed (pip install -r requirements.txt)\n3. api_server.py exists in the project root\n4. Port 5000 is not already in use by another application`;
        console.error(`❌ ${errorMsg}`);
        if (win) {
          dialog.showErrorBox("API Server Error", errorMsg);
        }
        return;
      }
    } else {
      console.log("✅ FunctionGemma API server is already running");
    }

    // Run each test case
    for (let i = 0; i < testCases.length; i++) {
      const testCase = testCases[i];
      console.log(
        `\n📝 Test Case ${i + 1}/${testCases.length}: ${testCase.name}`
      );
      console.log(`   Description: ${testCase.description}`);
      console.log(`   Natural Language: "${testCase.natural_language}"`);

      // Step 1: Send natural language to FunctionGemma API
      console.log("   🔄 Sending to FunctionGemma...");
      let processResponse;
      try {
        processResponse = await fetch(`${PYTHON_API_URL}/process`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            input: testCase.natural_language,
            function_schemas: formFunctionSchemas,
          }),
        });
      } catch (fetchError) {
        throw new Error(
          `Failed to connect to API server: ${fetchError.message}. Make sure the server is running at ${PYTHON_API_URL}`
        );
      }

      if (!processResponse.ok) {
        let errorMsg = `HTTP ${processResponse.status}: ${processResponse.statusText}`;
        try {
          const error = await processResponse.json();
          errorMsg = error.error || errorMsg;
        } catch (e) {
          // If response is not JSON, use status text
        }
        throw new Error(`FunctionGemma processing failed: ${errorMsg}`);
      }

      const processData = await processResponse.json();
      const functionCalls = processData.function_calls || [];

      console.log(
        `   ✅ FunctionGemma generated ${functionCalls.length} function call(s)`
      );
      console.log(`   📤 FunctionGemma output: ${processData.output}`);

      if (functionCalls.length === 0) {
        console.log("   ⚠️ No function calls generated, skipping execution");
        continue;
      }

      // Step 2: Execute function calls via Selenium
      console.log("   🔧 Executing function calls with Selenium...");
      let executeResponse;
      try {
        executeResponse = await fetch(`${PYTHON_API_URL}/execute`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            function_calls: functionCalls,
          }),
        });
      } catch (fetchError) {
        throw new Error(
          `Failed to connect to API server: ${fetchError.message}. Make sure the server is running at ${PYTHON_API_URL}`
        );
      }

      if (!executeResponse.ok) {
        let errorMsg = `HTTP ${executeResponse.status}: ${executeResponse.statusText}`;
        try {
          const error = await executeResponse.json();
          errorMsg = error.error || errorMsg;
        } catch (e) {
          // If response is not JSON, use status text
        }
        throw new Error(`Selenium execution failed: ${errorMsg}`);
      }

      const executeData = await executeResponse.json();
      console.log(`   ✅ Executed ${executeData.executed_count} function(s)`);

      // Wait a bit between test cases (except for the last one)
      if (i < testCases.length - 1) {
        console.log("   ⏳ Waiting 3 seconds before next test case...");
        await new Promise((resolve) => setTimeout(resolve, 3000));
      }
    }

    // Step 3: Close the browser after all tests
    console.log("\n🔒 Closing browser...");
    try {
      const closeResponse = await fetch(`${PYTHON_API_URL}/close_browser`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
      });

      if (closeResponse.ok) {
        console.log("✅ Browser closed successfully");
      }
    } catch (error) {
      console.error("⚠️ Error closing browser:", error);
    }

    // Show completion message
    if (win) {
      dialog.showMessageBox(win, {
        type: "info",
        title: "Tests Completed",
        message: `All test cases completed successfully!`,
        detail: `Executed ${testCases.length} test case(s). The browser has been closed.`,
        buttons: ["OK"],
      });
    }
  } catch (error) {
    console.error("❌ Test error:", error);
    const win = BrowserWindow.getFocusedWindow();
    if (win) {
      dialog.showErrorBox(
        "Test Error",
        `An error occurred during testing:\n\n${error.message}`
      );
    }
  }
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

  // Run Selenium tests after window is ready (optional - doesn't break existing functionality)
  win.webContents.once("did-finish-load", () => {
    // Small delay to ensure window is fully ready
    setTimeout(() => {
      runSeleniumTests();
    }, 1000);
  });
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
