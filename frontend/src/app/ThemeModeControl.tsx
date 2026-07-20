import DarkModeOutlined from "@mui/icons-material/DarkModeOutlined";
import LightModeOutlined from "@mui/icons-material/LightModeOutlined";
import IconButton from "@mui/material/IconButton";
import { useColorScheme } from "@mui/material/styles";

export function ThemeModeControl() {
  const { mode, setMode } = useColorScheme();
  const currentMode = mode === "light" ? "light" : "dark";
  const nextMode = currentMode === "dark" ? "light" : "dark";
  const nextLabel = nextMode === "dark" ? "深色" : "浅色";
  const actionLabel = `切换为${nextLabel}主题`;
  const icon = currentMode === "dark" ? <DarkModeOutlined fontSize="small" /> : <LightModeOutlined fontSize="small" />;
  const toggleMode = () => setMode(nextMode);

  return (
    <IconButton
      data-testid="theme-mode-control"
      aria-label={actionLabel}
      onClick={toggleMode}
      sx={{ width: 44, height: 44, color: "inherit" }}
    >
      {icon}
    </IconButton>
  );
}
