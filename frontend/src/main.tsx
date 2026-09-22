import React from "react";
import ReactDOM from "react-dom/client";
import "./styles.css";
import Workspace from "./workspace/Workspace";
import { installTelemetry } from "./workspace/telemetry";
installTelemetry();
document.documentElement.dataset.textSize =
  localStorage.getItem("meetingbot-text-size") || "standard";
document.documentElement.dataset.density =
  localStorage.getItem("meetingbot-density") || "standard";
const params = new URLSearchParams(location.hash.slice(1));
const credential = params.get("token");
if (credential) {
  sessionStorage.setItem("stt-token", credential);
  params.delete("token");
  window.history.replaceState(
    null,
    "",
    location.pathname + location.search + (params.size ? `#${params}` : ""),
  );
}
ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <Workspace />
  </React.StrictMode>,
);
