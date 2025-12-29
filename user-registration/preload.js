const { contextBridge } = require("electron");

contextBridge.exposeInMainWorld("electronAPI", {
  getModelPath: () => {
    // Return HTTP URL to access models via local server
    // The server runs on port 8766
    return "http://localhost:8766";
  },
  getModelServerPort: () => {
    return 8766;
  },
});
