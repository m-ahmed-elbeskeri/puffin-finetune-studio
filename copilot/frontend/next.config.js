/** @type {import('next').NextConfig} */
const backend =
  process.env.PUFFIN_COPILOT_BACKEND || "http://127.0.0.1:8765";

// `finetune-copilot build` sets PUFFIN_COPILOT_STATIC=1 to produce a static
// export (out/) that the FastAPI backend serves single-origin — no Node at
// runtime. In that mode Next forbids rewrites (there's no dev proxy), and the
// browser talks to /api on the same origin as the page, so none are needed.
const STATIC = process.env.PUFFIN_COPILOT_STATIC === "1";

/** @type {import('next').NextConfig} */
const nextConfig = STATIC
  ? {
      reactStrictMode: true,
      output: "export",
      // Emit route/index.html so a static file server (and deep links) resolve
      // /train → /train/ → train/index.html without extra routing config.
      trailingSlash: true,
      // No image optimizer server exists behind a static export.
      images: { unoptimized: true },
    }
  : {
      reactStrictMode: true,
      experimental: {
        // The chat SSE stream can go silent for minutes while a tool (eval run,
        // smoke train) executes. Default dev-proxy timeout is 30s — raise it so
        // the rewrite proxy doesn't sever quiet streams mid-conversation.
        proxyTimeout: 600_000,
      },
      // Proxy /api and SSE endpoints to the FastAPI backend in dev so the
      // browser sees a same-origin app and we sidestep CORS.
      async rewrites() {
        return [
          { source: "/api/:path*", destination: `${backend}/api/:path*` },
          { source: "/healthz", destination: `${backend}/healthz` },
        ];
      },
    };

module.exports = nextConfig;
