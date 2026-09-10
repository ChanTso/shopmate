import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import PortalPage from "./app/page";
import "./app/globals.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <PortalPage />
  </StrictMode>,
);
