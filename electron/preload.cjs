const { contextBridge } = require("electron");

const apiArg = process.argv.find((arg) => arg.startsWith("--api-base="));
const apiBase = apiArg ? apiArg.slice("--api-base=".length) : "http://127.0.0.1:8765";

contextBridge.exposeInMainWorld("quant", {
  apiBase
});
