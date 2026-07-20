import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "@fontsource-variable/inter";
import CssBaseline from "@mui/material/CssBaseline";
import InitColorSchemeScript from "@mui/material/InitColorSchemeScript";
import { ThemeProvider } from "@mui/material/styles";
import { QueryClientProvider } from "@tanstack/react-query";

import { App } from "./app/App";
import { queryClient } from "./app/queryClient";
import { amadeusTheme } from "./app/theme";
import { readThemeMode, THEME_MODE_STORAGE_KEY } from "./app/themeMode";

const root = document.getElementById("root");

if (root === null) {
  throw new Error("Missing #root element");
}

const defaultThemeMode = readThemeMode();
try {
  window.localStorage.setItem(THEME_MODE_STORAGE_KEY, defaultThemeMode);
} catch {
  // MUI still uses the dark default when browser storage is unavailable.
}

createRoot(root).render(
  <StrictMode>
    <InitColorSchemeScript
      attribute="data-amadeus-color-scheme"
      defaultMode={defaultThemeMode}
      modeStorageKey={THEME_MODE_STORAGE_KEY}
    />
    <ThemeProvider
      theme={amadeusTheme}
      defaultMode={defaultThemeMode}
      modeStorageKey={THEME_MODE_STORAGE_KEY}
    >
        <CssBaseline />
        <QueryClientProvider client={queryClient}>
          <App />
        </QueryClientProvider>
      </ThemeProvider>
  </StrictMode>,
);
