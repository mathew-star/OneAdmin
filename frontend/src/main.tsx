import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App, createApp } from "@/app";
import { readConfig } from "@/config";
import "./styles.css";

const root = document.getElementById("root");
if (!root) throw new Error("oneadmin: #root element missing from index.html");

const app = createApp(readConfig());

createRoot(root).render(
  <StrictMode>
    <App app={app} />
  </StrictMode>,
);
