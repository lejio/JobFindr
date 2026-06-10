function randomBetween(min, max) {
  return min + Math.random() * (max - min);
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function humanDelay(minMs = 800, maxMs = 2200) {
  await sleep(randomBetween(minMs, maxMs));
}

async function humanScroll(page) {
  const scrolls = Math.floor(randomBetween(1, 4));
  for (let i = 0; i < scrolls; i += 1) {
    await page.evaluate(() => {
      const amount = 120 + Math.random() * 360;
      window.scrollBy(0, amount);
    });
    await humanDelay(400, 1200);
  }
}

async function humanMouseMove(page) {
  const width = 1280;
  const height = 800;
  const x = randomBetween(80, width - 80);
  const y = randomBetween(80, height - 80);
  await page.mouse.move(x, y, { steps: Math.floor(randomBetween(8, 20)) });
}

function pickDecodoPort() {
  const start = Number(process.env.DECODO_START_PORT || process.env.SMARTPROXY_PORT || 10001);
  const end = Number(process.env.DECODO_END_PORT || start);
  if (Number.isNaN(start) || Number.isNaN(end)) {
    return 10001;
  }
  const min = Math.min(start, end);
  const max = Math.max(start, end);
  return Math.floor(randomBetween(min, max + 1));
}

function getProxyCredentials() {
  if (process.env.PROXY_URL) {
    const parsed = new URL(process.env.PROXY_URL.trim());
    return {
      host: parsed.hostname,
      port: parsed.port || "7000",
      username: decodeURIComponent(parsed.username),
      password: decodeURIComponent(parsed.password),
    };
  }

  const decodoUser = process.env.DECODO_USERNAME?.trim();
  const decodoPass = process.env.DECODO_PASSWORD?.trim();
  if (decodoUser && decodoPass) {
    return {
      host: (process.env.DECODO_HOST || "gate.decodo.com").trim(),
      port: String(pickDecodoPort()),
      username: decodoUser,
      password: decodoPass,
    };
  }

  const username = process.env.SMARTPROXY_USERNAME?.trim();
  const password = process.env.SMARTPROXY_PASSWORD?.trim();
  if (!username || !password) {
    return null;
  }

  return {
    host: (process.env.SMARTPROXY_HOST || "gate.decodo.com").trim(),
    port: (process.env.SMARTPROXY_PORT || "7000").trim(),
    username,
    password,
  };
}

function buildUpstreamProxyUrl() {
  const creds = getProxyCredentials();
  if (!creds) {
    return null;
  }
  const user = encodeURIComponent(creds.username);
  const pass = encodeURIComponent(creds.password);
  return `http://${user}:${pass}@${creds.host}:${creds.port}`;
}

function isProxyEnabled() {
  return Boolean(getProxyCredentials());
}

module.exports = {
  randomBetween,
  sleep,
  humanDelay,
  humanScroll,
  humanMouseMove,
  getProxyCredentials,
  buildUpstreamProxyUrl,
  isProxyEnabled,
};
