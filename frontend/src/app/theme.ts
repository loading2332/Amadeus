import { createTheme } from "@mui/material/styles";

export const amadeusTheme = createTheme({
  cssVariables: {
    colorSchemeSelector: "data-amadeus-color-scheme",
  },
  colorSchemes: {
    light: {
      palette: {
        primary: { main: "#176b75" },
        background: { default: "#f4f6f9", paper: "#ffffff" },
        divider: "rgba(24, 45, 51, 0.1)",
        text: { primary: "#1c2b30", secondary: "#5a6b70" },
      },
    },
    dark: {
      palette: {
        primary: { main: "#63c5cf" },
        background: { default: "#12171d", paper: "#1a212a" },
        divider: "rgba(148, 186, 192, 0.14)",
        text: { primary: "#e4ebee", secondary: "#93a4ab" },
      },
    },
  },
  shape: { borderRadius: 10 },
  typography: {
    fontFamily:
      '"Inter Variable", "Noto Sans SC", "Microsoft YaHei UI", "PingFang SC", sans-serif',
    allVariants: { letterSpacing: 0 },
    button: { textTransform: "none", fontWeight: 600 },
    h5: { fontWeight: 700 },
    h6: { fontWeight: 700 },
    body1: { lineHeight: 1.75 },
    body2: { lineHeight: 1.6 },
  },
  components: {
    MuiButton: {
      defaultProps: { disableElevation: true },
    },
    MuiTooltip: {
      styleOverrides: {
        tooltip: {
          fontSize: 12,
          borderRadius: 8,
          paddingInline: 10,
          paddingBlock: 5,
        },
      },
    },
    MuiCssBaseline: {
      styleOverrides: {
        "html, body, #root": { minHeight: "100%" },
        body: { margin: 0 },
        "*": {
          boxSizing: "border-box",
          scrollbarWidth: "thin",
          scrollbarColor: "var(--mui-palette-divider) transparent",
        },
        "*::-webkit-scrollbar": { width: 8, height: 8 },
        "*::-webkit-scrollbar-track": { background: "transparent" },
        "*::-webkit-scrollbar-thumb": {
          borderRadius: 8,
          backgroundColor: "var(--mui-palette-divider)",
        },
        "*::-webkit-scrollbar-thumb:hover": {
          backgroundColor: "rgba(var(--mui-palette-primary-mainChannel) / 0.35)",
        },
        "::selection": {
          backgroundColor: "rgba(var(--mui-palette-primary-mainChannel) / 0.25)",
        },
      },
    },
  },
});
