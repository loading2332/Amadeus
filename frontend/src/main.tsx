import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import CssBaseline from "@mui/material/CssBaseline";
import InitColorSchemeScript from "@mui/material/InitColorSchemeScript";
import { ThemeProvider } from "@mui/material/styles";
import { QueryClientProvider } from "@tanstack/react-query";

import { App } from "./app/App";
import { queryClient } from "./app/queryClient";
import { amadeusTheme } from "./app/theme";
import { THEME_MODE_STORAGE_KEY } from "./app/themeMode";

const root = document.getElementById("root");

if (root === null) {
  throw new Error("Missing #root element");
}

createRoot(root).render(
  <StrictMode>
    <InitColorSchemeScript
      attribute="data-amadeus-color-scheme"
      defaultMode="system"
      modeStorageKey={THEME_MODE_STORAGE_KEY}
    />
    <ThemeProvider
      theme={amadeusTheme}
      defaultMode="system"
      modeStorageKey={THEME_MODE_STORAGE_KEY}
    >
        <CssBaseline />
        <QueryClientProvider client={queryClient}>
          <App />
        </QueryClientProvider>
      </ThemeProvider>
  </StrictMode>,
);
