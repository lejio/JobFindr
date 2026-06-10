const BLOCKED_RESOURCE_TYPES = new Set([
  "image",
  "stylesheet",
  "font",
  "media",
  "texttrack",
  "manifest",
]);

const BLOCKED_URL_PATTERN =
  /\.(png|jpe?g|gif|webp|svg|ico|bmp|css|woff2?|ttf|otf|eot|mp4|webm|mp3|m4a)(\?|#|$)/i;

function shouldBlockRequest(request) {
  if (BLOCKED_RESOURCE_TYPES.has(request.resourceType())) {
    return true;
  }

  const url = request.url().toLowerCase();
  if (BLOCKED_URL_PATTERN.test(url)) {
    return true;
  }

  if (url.includes("google.com") && (url.includes("/images/") || url.includes("gstatic.com"))) {
    return true;
  }

  return false;
}

const globalStats = {
  started_at: new Date().toISOString(),
  requests: 0,
  requests_blocked: 0,
  bytes_downloaded: 0,
  bytes_uploaded: 0,
  search_calls: 0,
  scrape_calls: 0,
};

function isLeanLoadingEnabled() {
  return process.env.BLOCK_CSS_IMAGES !== "false";
}

function createSessionTraffic() {
  return {
    requests: 0,
    requests_blocked: 0,
    bytes_downloaded: 0,
    bytes_uploaded: 0,
  };
}

async function attachTrafficListeners(page, session) {
  const lean = isLeanLoadingEnabled();

  if (lean) {
    await page.setRequestInterception(true);
  }

  page.on("request", (request) => {
    const postData = request.postData();
    const uploadBytes = postData ? Buffer.byteLength(postData) : 0;

    session.requests += 1;
    session.bytes_uploaded += uploadBytes;
    globalStats.requests += 1;
    globalStats.bytes_uploaded += uploadBytes;

    if (!lean) {
      return;
    }

    if (shouldBlockRequest(request)) {
      session.requests_blocked += 1;
      globalStats.requests_blocked += 1;
      request.abort();
      return;
    }

    request.continue();
  });

  page.on("response", (response) => {
    try {
      const contentLength = response.headers()["content-length"];
      const downloadBytes = contentLength ? parseInt(contentLength, 10) : 0;
      if (!downloadBytes || Number.isNaN(downloadBytes)) {
        return;
      }

      session.bytes_downloaded += downloadBytes;
      globalStats.bytes_downloaded += downloadBytes;
    } catch {
      // Ignore header read failures.
    }
  });
}

function recordSearch(sessionTraffic) {
  globalStats.search_calls += 1;
  return finalizeSessionTraffic(sessionTraffic);
}

function recordScrape(sessionTraffic) {
  globalStats.scrape_calls += 1;
  return finalizeSessionTraffic(sessionTraffic);
}

function finalizeSessionTraffic(sessionTraffic) {
  return {
    requests: sessionTraffic.requests,
    requests_blocked: sessionTraffic.requests_blocked,
    bytes_downloaded: sessionTraffic.bytes_downloaded,
    bytes_uploaded: sessionTraffic.bytes_uploaded,
    lean_loading: isLeanLoadingEnabled(),
  };
}

function getGlobalStats() {
  return { ...globalStats };
}

module.exports = {
  createSessionTraffic,
  attachTrafficListeners,
  recordSearch,
  recordScrape,
  getGlobalStats,
};
