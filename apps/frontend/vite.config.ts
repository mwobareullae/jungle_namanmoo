import react from "@vitejs/plugin-react";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";

const rootDir = fileURLToPath(new URL(".", import.meta.url));

export default defineConfig({
  plugins: [react()],
  server: {
    host: "0.0.0.0",
    port: 5173
  },
  build: {
    rollupOptions: {
      input: {
        main: resolve(rootDir, "index.html"),
        aqua: resolve(rootDir, "beauty-commerce-aqua-glass.html"),
        search: resolve(rootDir, "beauty-commerce-search.html"),
        productDetail: resolve(rootDir, "beauty-commerce-product-detail.html"),
        checkout: resolve(rootDir, "beauty-commerce-checkout.html"),
        paymentComplete: resolve(rootDir, "beauty-commerce-payment-complete.html")
      }
    }
  }
});
