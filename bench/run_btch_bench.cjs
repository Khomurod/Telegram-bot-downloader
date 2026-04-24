const fs = require('fs');
const path = require('path');
const btch = require('btch-downloader');

const configPath = path.join(__dirname, 'compare_config.json');
const outPath = path.join(__dirname, 'btch_results.json');
const config = JSON.parse(fs.readFileSync(configPath, 'utf8'));

function asArray(v) {
  if (v == null) return [];
  return Array.isArray(v) ? v : [v];
}

function pickPlatformDownloadLinks(platform, result) {
  if (!result || typeof result !== 'object') return [];

  const links = [];
  const add = (v) => {
    if (typeof v === 'string' && /^https?:\/\//i.test(v)) links.push(v);
  };

  switch (platform) {
    case 'threads': {
      add(result?.result?.video);
      break;
    }
    case 'youtube': {
      add(result?.mp3);
      add(result?.mp4);
      break;
    }
    case 'igdl': {
      for (const item of asArray(result?.result)) add(item?.url);
      break;
    }
    case 'ttdl': {
      for (const item of asArray(result?.video)) add(item);
      for (const item of asArray(result?.audio)) add(item);
      break;
    }
    case 'fbdown': {
      add(result?.Normal_video);
      add(result?.HD);
      break;
    }
    case 'twitter': {
      for (const item of asArray(result?.url)) {
        if (typeof item === 'string') add(item);
        else if (item && typeof item === 'object') {
          add(item.hd);
          add(item.sd);
          add(item.url);
        }
      }
      break;
    }
    case 'soundcloud': {
      add(result?.result?.audio);
      break;
    }
    case 'spotify': {
      for (const fmt of asArray(result?.result?.formats)) add(fmt?.url);
      break;
    }
    case 'gdrive': {
      add(result?.result?.data?.downloadUrl);
      break;
    }
    case 'mediafire': {
      add(result?.result?.url);
      add(result?.url);
      break;
    }
    case 'pinterest': {
      add(result?.result?.result?.image);
      for (const key of Object.keys(result?.result?.result?.videos || {})) {
        add(result.result.result.videos[key]?.url);
      }
      break;
    }
    case 'capcut': {
      add(result?.originalVideoUrl);
      add(result?.video);
      break;
    }
    default: {
      // conservative fallback: do not auto-pass unknown platforms
      break;
    }
  }

  return [...new Set(links)];
}

function normalizeStatus(result) {
  if (!result || typeof result !== 'object') return false;

  if (typeof result.status === 'boolean') return result.status;
  if (typeof result.status === 'string') {
    const s = result.status.toLowerCase();
    if (['ok', 'success', 'true'].includes(s)) return true;
    if (['error', 'failed', 'fail', 'false'].includes(s)) return false;
  }

  if (result.result && typeof result.result === 'object') {
    if (typeof result.result.status === 'boolean') return result.result.status;
    if (typeof result.result.status === 'string') {
      const s = result.result.status.toLowerCase();
      if (['ok', 'success', 'true'].includes(s)) return true;
      if (['error', 'failed', 'fail', 'false'].includes(s)) return false;
    }
  }

  return true;
}

(async () => {
  const rows = [];

  for (let round = 1; round <= config.rounds; round++) {
    for (const t of config.tests) {
      const fn = btch[t.platform];
      const started = Date.now();
      let ok = false;
      let error = null;
      let downloadLinks = [];
      let resultPreview = null;

      if (typeof fn !== 'function') {
        rows.push({
          tool: 'btch',
          round,
          id: t.id,
          platform: t.platform,
          url: t.url,
          ok: false,
          duration_ms: Date.now() - started,
          media_link_count: 0,
          media_link_sample: [],
          error: `Function not found: ${t.platform}`,
          result_preview: null,
        });
        continue;
      }

      try {
        const result = await fn(t.url);
        const statusOk = normalizeStatus(result);
        downloadLinks = pickPlatformDownloadLinks(t.platform, result);
        ok = statusOk && downloadLinks.length > 0;

        const preview = JSON.stringify(result);
        resultPreview = preview.length > 800 ? preview.slice(0, 800) + '…' : preview;

        if (!ok && !error) {
          error = statusOk
            ? `No usable download links returned for platform ${t.platform}`
            : 'Function returned error status';
        }
      } catch (e) {
        ok = false;
        error = e && e.message ? e.message : String(e);
      }

      rows.push({
        tool: 'btch',
        round,
        id: t.id,
        platform: t.platform,
        url: t.url,
        ok,
        duration_ms: Date.now() - started,
        media_link_count: downloadLinks.length,
        media_link_sample: downloadLinks.slice(0, 5),
        error,
        result_preview: resultPreview,
      });
    }
  }

  fs.writeFileSync(outPath, JSON.stringify({ generated_at: new Date().toISOString(), rows }, null, 2));
  console.log(`Wrote ${rows.length} rows to ${outPath}`);
})();
