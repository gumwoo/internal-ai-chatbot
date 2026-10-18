import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// API는 같은 출처로 보이게 프록시한다(세션 쿠키 Path=/api/v1, SameSite=Strict, Origin 검사).
const api = process.env.API_ORIGIN ?? "http://127.0.0.1:8010";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5190,
    strictPort: true,
    proxy: { "/api": { target: api, changeOrigin: false } },
  },
  preview: { host: "127.0.0.1", port: 5190, strictPort: true, proxy: { "/api": { target: api } } },
});
