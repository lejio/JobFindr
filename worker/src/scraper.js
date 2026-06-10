const { humanDelay, humanMouseMove, humanScroll } = require("./utils");
const {
  createSessionTraffic,
  attachTrafficListeners,
  recordSearch,
  recordScrape,
} = require("./traffic");
const { getBrowserPool } = require("./browser_pool");

function isInterestingNetworkUrl(responseUrl, contentType) {
  if (contentType.includes("json")) {
    return true;
  }
  return /jobvite\.com|icims\.com|myworkdayjobs\.com/i.test(responseUrl);
}

function resolveScrapeProfile(url, options = {}) {
  const isJobvite = /jobs\.jobvite\.com/i.test(url);
  const leanLoading = process.env.BLOCK_CSS_IMAGES !== "false" && !options.forceFullLoad;

  return {
    waitUntil:
      options.waitUntil ||
      (isJobvite ? "networkidle2" : leanLoading ? "domcontentloaded" : "networkidle2"),
    timeout: options.timeout || (isJobvite ? 60000 : 45000),
    waitForSelector:
      options.waitForSelector || (isJobvite ? 'a[href*="/job/"]' : null),
    waitForSelectorTimeout: options.waitForSelectorTimeout || 15000,
  };
}

function attachNetworkCapture(page, networkResponses, captureNetwork) {
  if (!captureNetwork) {
    return;
  }

  page.on("response", async (response) => {
    try {
      const responseUrl = response.url();
      const contentType = response.headers()["content-type"] || "";
      if (!isInterestingNetworkUrl(responseUrl, contentType)) {
        return;
      }

      const text = await response.text();
      if (!text || text.length > 500_000) {
        return;
      }

      networkResponses.push({
        url: responseUrl,
        status: response.status(),
        content_type: contentType,
        body: text,
      });
    } catch {
      // Response body may be unavailable after navigation.
    }
  });
}

async function scrapeUrl(url, options = {}) {
  const { captureNetwork = true } = options;
  const profile = resolveScrapeProfile(url, options);
  const pool = getBrowserPool();
  const sessionTraffic = createSessionTraffic();

  return pool.withPage(async (page) => {
    const networkResponses = [];
    await attachTrafficListeners(page, sessionTraffic);
    attachNetworkCapture(page, networkResponses, captureNetwork);

    await humanDelay(500, 1500);
    await page.goto(url, { waitUntil: profile.waitUntil, timeout: profile.timeout });

    if (profile.waitForSelector) {
      try {
        await page.waitForSelector(profile.waitForSelector, {
          timeout: profile.waitForSelectorTimeout,
        });
      } catch {
        // Some boards are empty or render without job anchors.
      }
    }

    await humanMouseMove(page);
    await humanScroll(page);
    await humanDelay(1000, 2500);

    const html = await page.content();
    const finalUrl = page.url();
    sessionTraffic.bytes_downloaded += Buffer.byteLength(html, "utf8");

    return {
      url: finalUrl,
      html,
      network_responses: networkResponses,
      traffic: recordScrape(sessionTraffic),
      proxy_enabled: pool.getStats().proxy_enabled,
    };
  });
}

function extractUrlsFromHtml(html, maxResults = 5) {
  const patterns = [
    /https?:\/\/boards\.greenhouse\.io\/[a-zA-Z0-9_-]+/g,
    /https?:\/\/jobs\.lever\.co\/[a-zA-Z0-9_-]+/g,
    /https?:\/\/jobs\.ashbyhq\.com\/[a-zA-Z0-9_-]+/g,
  ];

  const found = [];
  for (const pattern of patterns) {
    const matches = html.match(pattern) || [];
    for (const match of matches) {
      if (!found.includes(match)) {
        found.push(match);
      }
      if (found.length >= maxResults) {
        return found;
      }
    }
  }
  return found;
}

async function googleSearch(query, maxResults = 5) {
  const searchUrl = `https://www.google.com/search?q=${encodeURIComponent(query)}&num=${maxResults}`;
  const pool = getBrowserPool();
  const sessionTraffic = createSessionTraffic();

  return pool.withPage(async (page) => {
    await attachTrafficListeners(page, sessionTraffic);
    await humanDelay(500, 1500);
    await page.goto(searchUrl, { waitUntil: "domcontentloaded", timeout: 60000 });

    const consentButton = await page.$(
      'button[aria-label*="Accept"], button[aria-label*="Agree"], #L2AGLb, form[action*="consent"] button'
    );
    if (consentButton) {
      await consentButton.click();
      await humanDelay(800, 1500);
    }

    await humanMouseMove(page);
    await humanScroll(page);
    await humanDelay(800, 1800);

    const html = await page.content();
    const blocked =
      html.includes("unusual traffic") ||
      html.includes("captcha") ||
      html.includes("solveSimpleChallenge");

    const urls = await page.evaluate((limit) => {
      const links = [];
      const anchors = document.querySelectorAll("div#search a[href], div.g a[href], a[href]");

      for (const anchor of anchors) {
        let href = anchor.href;
        if (!href) continue;

        if (href.startsWith("/url?")) {
          const params = new URLSearchParams(href.replace("/url?", ""));
          href = params.get("q") || href;
        }

        if (
          href.startsWith("http") &&
          !href.includes("google.com") &&
          !href.includes("gstatic.com") &&
          !href.includes("youtube.com")
        ) {
          links.push(href);
        }

        if (links.length >= limit) break;
      }

      return [...new Set(links)];
    }, maxResults);

    const merged = [...new Set([...urls, ...extractUrlsFromHtml(html, maxResults)])].slice(
      0,
      maxResults
    );

    sessionTraffic.bytes_downloaded += Buffer.byteLength(html, "utf8");

    return {
      query,
      urls: merged,
      blocked,
      proxy_enabled: pool.getStats().proxy_enabled,
      traffic: recordSearch(sessionTraffic),
    };
  });
}

module.exports = {
  scrapeUrl,
  googleSearch,
};
