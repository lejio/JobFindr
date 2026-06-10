require("dotenv").config({ path: require("path").resolve(__dirname, "../../.env") });

const express = require("express");
const { scrapeUrl, googleSearch } = require("./scraper");
const { getBrowserPool } = require("./browser_pool");
const { isProxyEnabled } = require("./utils");
const { getGlobalStats } = require("./traffic");

const app = express();
app.use(express.json({ limit: "1mb" }));

const PORT = Number(process.env.WORKER_PORT || 3847);
const HOST = process.env.WORKER_HOST || "127.0.0.1";

app.get("/health", (_req, res) => {
  res.json({
    status: "ok",
    proxy_enabled: isProxyEnabled(),
    lean_loading: process.env.BLOCK_CSS_IMAGES !== "false",
    browser_pool: getBrowserPool().getStats(),
  });
});

app.get("/metrics", (_req, res) => {
  res.json({
    proxy_enabled: isProxyEnabled(),
    traffic: getGlobalStats(),
  });
});

app.post("/search", async (req, res) => {
  const { query, max_results: maxResults = 5 } = req.body || {};
  if (!query || typeof query !== "string") {
    return res.status(400).json({ error: "query is required" });
  }

  try {
    const result = await googleSearch(query, maxResults);
    return res.json(result);
  } catch (error) {
    console.error("Search failed:", error);
    return res.status(500).json({ error: error.message || "search failed" });
  }
});

app.post("/scrape", async (req, res) => {
  const {
    url,
    capture_network: captureNetwork = true,
    wait_until: waitUntil,
    wait_for_selector: waitForSelector,
    timeout,
    force_full_load: forceFullLoad,
  } = req.body || {};
  if (!url || typeof url !== "string") {
    return res.status(400).json({ error: "url is required" });
  }

  try {
    const result = await scrapeUrl(url, {
      captureNetwork,
      waitUntil,
      waitForSelector,
      timeout,
      forceFullLoad,
    });
    return res.json(result);
  } catch (error) {
    console.error("Scrape failed:", error);
    return res.status(500).json({ error: error.message || "scrape failed" });
  }
});

const server = app.listen(PORT, HOST, () => {
  const pool = getBrowserPool().getStats();
  console.log(`JobFindr worker listening on http://${HOST}:${PORT}`);
  console.log(`Proxy: ${isProxyEnabled() ? "enabled" : "disabled"}`);
  console.log(`Browser pool: up to ${pool.max_pages} concurrent pages (persistent browser)`);
});

async function shutdown(signal) {
  console.log(`${signal} received — closing browser pool...`);
  server.close();
  await getBrowserPool().shutdown();
  process.exit(0);
}

process.on("SIGINT", () => shutdown("SIGINT"));
process.on("SIGTERM", () => shutdown("SIGTERM"));
