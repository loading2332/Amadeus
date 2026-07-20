import { createTheme } from "@mui/material/styles";

export const amadeusTheme = createTheme({
  cssVariables: {
    colorSchemeSelector: "data-amadeus-color-scheme",
  },
  colorSchemes: {
    light: {
      palette: {
        primary: { main: "#176b75" },
        background: { default: "#f7f8fa", paper: "#ffffff" },
      },
    },
    dark: {
      palette: {
        primary: { main: "#63c5cf" },
        background: { default: "#14191f", paper: "#1b222a" },
      },
    },
  },
  shape: { borderRadius: 10 },
  typography: {
    fontFamily:
      '"Inter Variable", "Noto Sans SC", "Microsoft YaHei UI", "PingFang SC", sans-serif',
    allVariants: { letterSpacing: 0 },
    button: { textTransform: "none", fontWeight: 600 },
    body1: { lineHeight: 1.75 },
    body2: { lineHeight: 1.6 },
  },
  components: {
    MuiButton: {
      defaultProps: { disableElevation: true },
    },
    MuiCssBaseline: {
      styleOverrides: {
        "html, body, #root": { minHeight: "100%" },
        body: { margin: 0 },
        "*": { boxSizing: "border-box" },
      },
    },
  },
});
