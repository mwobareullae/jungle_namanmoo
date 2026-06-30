import { useEffect, useState } from "react";

const originalHomeUrl = "/original-design/beauty-commerce-aqua-glass.html";

const rewriteOriginalAssetPaths = (value: string) =>
  value
    .split("./Design_system/")
    .join("/original-design/Design_system/")
    .split("./system_design/")
    .join("/original-design/system_design/")
    .split("./beauty-commerce-")
    .join("/original-design/beauty-commerce-");

const extractOriginalDocument = (html: string) => {
  const parser = new DOMParser();
  const doc = parser.parseFromString(html, "text/html");
  const headNodes = Array.from(doc.head.querySelectorAll("style, link[rel='stylesheet']"));
  const scripts = Array.from(doc.body.querySelectorAll("script"));

  scripts.forEach((script) => script.remove());

  return {
    bodyHtml: rewriteOriginalAssetPaths(doc.body.innerHTML),
    headHtml: headNodes.map((node) => rewriteOriginalAssetPaths(node.outerHTML)).join("\n"),
    scripts: scripts.map((script) => rewriteOriginalAssetPaths(script.textContent ?? ""))
  };
};

function App() {
  const [bodyHtml, setBodyHtml] = useState("");

  useEffect(() => {
    let isMounted = true;
    const injectedNodes: HTMLElement[] = [];

    const loadOriginalHome = async () => {
      const response = await fetch(originalHomeUrl);
      const html = await response.text();
      const originalDocument = extractOriginalDocument(html);

      if (!isMounted) {
        return;
      }

      document.documentElement.dataset.appMode =
        import.meta.env.VITE_APP_MODE === "community" ? "community" : "commerce";
      setBodyHtml(originalDocument.bodyHtml);

      const headContainer = document.createElement("div");
      headContainer.innerHTML = originalDocument.headHtml;
      Array.from(headContainer.children).forEach((node) => {
        document.head.appendChild(node);
        injectedNodes.push(node as HTMLElement);
      });

      window.setTimeout(() => {
        originalDocument.scripts.forEach((scriptText) => {
          const script = document.createElement("script");
          script.textContent = scriptText;
          document.body.appendChild(script);
          injectedNodes.push(script);
        });
      }, 0);
    };

    void loadOriginalHome();

    return () => {
      isMounted = false;
      injectedNodes.forEach((node) => node.remove());
    };
  }, []);

  return (
    <main
      className="spa-origin-shell"
      dangerouslySetInnerHTML={{ __html: bodyHtml }}
    />
  );
}

export default App;
