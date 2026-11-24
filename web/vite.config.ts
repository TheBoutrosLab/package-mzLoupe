import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

/**
 * Build the embedded dashboard and route development API calls to the local
 * server.
 */
export default defineConfig({
  plugins: [react()],
  // Keep embedded attribution comments from prebuilt vendor libraries.
  esbuild: { legalComments: "eof" },
  // Run mzloupe serve separately when using the Vite development server.
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8766"
    }
  },
  // These compiled assets are included in the Python wheel.
  build: {
    outDir: "../mzloupe/static",
    emptyOutDir: true,
    // Vite collects license texts for dependency modules in the final bundle.
    // Keep the report under assets so the server and Python wheel include it.
    license: { fileName: "assets/THIRD_PARTY_NOTICES.txt" }
  }
});
