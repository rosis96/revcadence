import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
// One stylesheet entry. tailwind.css pulls in Tailwind, the vendor CSS and
// styles.css in cascade layers — the order lives there, where it can be
// explained, rather than in an import list that has to be read in reverse.
import "./tailwind.css";

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode><App /></React.StrictMode>
);
