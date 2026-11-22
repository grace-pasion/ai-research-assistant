import React from "react";
import ReactDOM from "react-dom/client";
import AdminApp from "./AdminApp";
import App from "./App";
import "./styles.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    {new URLSearchParams(window.location.search).get("portal") === "admin" ? (
      <AdminApp />
    ) : (
      <App />
    )}
  </React.StrictMode>,
);
