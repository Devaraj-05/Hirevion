import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { installCrashReporting } from "./native/crash";
import "./styles.css";

installCrashReporting();

const container = document.getElementById("root");
if (!container) {
  throw new Error("index.html is missing the #root element");
}
createRoot(container).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
