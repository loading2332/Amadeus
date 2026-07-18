import { useId } from "react";
import DarkModeOutlined from "@mui/icons-material/DarkModeOutlined";
import FormControl from "@mui/material/FormControl";
import InputLabel from "@mui/material/InputLabel";
import MenuItem from "@mui/material/MenuItem";
import Select, { type SelectChangeEvent } from "@mui/material/Select";
import { useColorScheme } from "@mui/material/styles";

import type { ThemeMode } from "./themeMode";

export function ThemeModeControl() {
  const { mode, setMode } = useColorScheme();
  const labelId = useId();

  const onChange = (event: SelectChangeEvent) => {
    const next = event.target.value as ThemeMode;
    setMode(next);
  };

  return (
    <FormControl fullWidth size="small">
      <InputLabel id={labelId} sx={{ color: "rgba(255,255,255,0.7)" }}>主题</InputLabel>
      <Select
        labelId={labelId}
        value={mode ?? "system"}
        label="主题"
        onChange={onChange}
        startAdornment={<DarkModeOutlined fontSize="small" sx={{ mr: 1 }} />}
        sx={{ color: "inherit", ".MuiOutlinedInput-notchedOutline": { borderColor: "rgba(255,255,255,0.2)" }, ".MuiSvgIcon-root": { color: "inherit" } }}
      >
        <MenuItem value="system">跟随系统</MenuItem>
        <MenuItem value="light">浅色</MenuItem>
        <MenuItem value="dark">深色</MenuItem>
      </Select>
    </FormControl>
  );
}
