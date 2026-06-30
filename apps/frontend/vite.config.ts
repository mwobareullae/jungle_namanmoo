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
        originalAqua: resolve(rootDir, "original-design/beauty-commerce-aqua-glass.html"),
        originalSearch: resolve(rootDir, "original-design/beauty-commerce-search.html"),
        originalProductDetail: resolve(
          rootDir,
          "original-design/beauty-commerce-product-detail.html"
        ),
        originalCheckout: resolve(rootDir, "original-design/beauty-commerce-checkout.html"),
        originalPaymentComplete: resolve(
          rootDir,
          "original-design/beauty-commerce-payment-complete.html"
        )
      }
    }
  }
});
