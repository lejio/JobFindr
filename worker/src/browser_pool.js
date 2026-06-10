const puppeteer = require("puppeteer-extra");
const StealthPlugin = require("puppeteer-extra-plugin-stealth");
const { buildUpstreamProxyUrl } = require("./utils");

puppeteer.use(StealthPlugin());

const USER_AGENTS = [
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
  "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
  "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
];

function pickUserAgent() {
  return USER_AGENTS[Math.floor(Math.random() * USER_AGENTS.length)];
}

class BrowserPool {
  constructor(maxPages = 3) {
    this._maxPages = maxPages;
    this._browser = null;
    this._anonymizedProxyUrl = null;
    this._proxyEnabled = false;
    this._launchPromise = null;
    this._activePages = 0;
    this._waitQueue = [];
    this._shuttingDown = false;
  }

  getStats() {
    return {
      ready: Boolean(this._browser),
      active_pages: this._activePages,
      max_pages: this._maxPages,
      queued: this._waitQueue.length,
      proxy_enabled: this._proxyEnabled,
    };
  }

  async _ensureBrowser() {
    if (this._shuttingDown) {
      throw new Error("Browser pool is shutting down");
    }
    if (this._browser) {
      return this._browser;
    }
    if (!this._launchPromise) {
      this._launchPromise = this._launchBrowser().finally(() => {
        this._launchPromise = null;
      });
    }
    await this._launchPromise;
    return this._browser;
  }

  async _launchBrowser() {
    const upstreamProxyUrl = buildUpstreamProxyUrl();
    const args = [
      "--no-sandbox",
      "--disable-setuid-sandbox",
      "--disable-blink-features=AutomationControlled",
      "--window-size=1280,800",
    ];

    if (upstreamProxyUrl) {
      const proxyChain = await import("proxy-chain");
      this._anonymizedProxyUrl = await proxyChain.anonymizeProxy(upstreamProxyUrl);
      args.push(`--proxy-server=${this._anonymizedProxyUrl}`);
    }

    this._proxyEnabled = Boolean(upstreamProxyUrl);
    this._browser = await puppeteer.launch({
      headless: process.env.HEADLESS !== "false",
      args,
    });

    this._browser.on("disconnected", () => {
      this._browser = null;
    });

    return this._browser;
  }

  async _waitForSlot() {
    if (this._activePages < this._maxPages) {
      return;
    }
    await new Promise((resolve) => {
      this._waitQueue.push(resolve);
    });
  }

  _releaseSlot() {
    this._activePages = Math.max(0, this._activePages - 1);
    const next = this._waitQueue.shift();
    if (next) {
      next();
    }
  }

  async acquirePage() {
    await this._ensureBrowser();
    await this._waitForSlot();
    this._activePages += 1;

    try {
      const page = await this._browser.newPage();
      await page.setUserAgent(pickUserAgent());
      await page.setViewport({ width: 1280, height: 800 });
      return page;
    } catch (error) {
      this._releaseSlot();
      throw error;
    }
  }

  async releasePage(page) {
    try {
      if (page && !page.isClosed()) {
        await page.close();
      }
    } catch {
      // Page may already be closed after navigation errors.
    } finally {
      this._releaseSlot();
    }
  }

  async withPage(fn) {
    const page = await this.acquirePage();
    try {
      return await fn(page);
    } finally {
      await this.releasePage(page);
    }
  }

  async shutdown() {
    this._shuttingDown = true;

    while (this._waitQueue.length > 0) {
      const resolve = this._waitQueue.shift();
      resolve();
    }

    if (this._browser) {
      try {
        await this._browser.close();
      } catch {
        // Browser may already be gone.
      }
      this._browser = null;
    }

    if (this._anonymizedProxyUrl) {
      try {
        const proxyChain = await import("proxy-chain");
        await proxyChain.closeAnonymizedProxy(this._anonymizedProxyUrl, true);
      } catch {
        // Best-effort proxy cleanup.
      }
      this._anonymizedProxyUrl = null;
    }
  }
}

const poolSize = Number(process.env.BROWSER_POOL_SIZE || 3);
const browserPool = new BrowserPool(poolSize);

function getBrowserPool() {
  return browserPool;
}

module.exports = {
  BrowserPool,
  getBrowserPool,
};
