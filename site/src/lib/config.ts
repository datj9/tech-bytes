/**
 * Site config + data-dir helpers.
 *
 * Branding (title/tagline/url/accent) is read from config/techbytes.config.yml
 * at build time, with PUBLIC_* env overrides for CI deployments. The data
 * directory defaults to ../data (relative to the site/ cwd) but is overridable
 * via DATA_DIR for the GitHub Actions / S3-download paths.
 */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { load as yamlLoad } from 'js-yaml';

export interface SiteConfig {
  title: string;
  tagline: string;
  url: string;
  accent: string;
}

const DEFAULT_CONFIG: SiteConfig = {
  title: 'Tech Bytes',
  tagline: 'Daily developer digest',
  url: '',
  accent: 'emerald',
};

let cached: SiteConfig | null = null;

/**
 * Load site branding. Resolution order per field:
 *   PUBLIC_SITE_TITLE / PUBLIC_SITE_TAGLINE / PUBLIC_SITE_URL / PUBLIC_SITE_ACCENT env
 *   > config/techbytes.config.yml
 *   > baked-in default
 */
export function getSiteConfig(): SiteConfig {
  if (cached) return cached;

  let fromYaml: Partial<SiteConfig> = {};
  const candidates = [
    resolve(process.cwd(), '..', 'config', 'techbytes.config.yml'),
    resolve(process.cwd(), '..', 'config', 'techbytes.config.example.yml'),
  ];
  for (const path of candidates) {
    try {
      const raw = readFileSync(path, 'utf-8');
      const parsed = yamlLoad(raw) as { site?: Record<string, string> } | null;
      if (parsed?.site) {
        fromYaml = { ...parsed.site };
        break;
      }
    } catch {
      // try the next candidate
    }
  }

  cached = {
    title: process.env.PUBLIC_SITE_TITLE || fromYaml.title || DEFAULT_CONFIG.title,
    tagline: process.env.PUBLIC_SITE_TAGLINE || fromYaml.tagline || DEFAULT_CONFIG.tagline,
    url: process.env.PUBLIC_SITE_URL || fromYaml.url || DEFAULT_CONFIG.url,
    accent: process.env.PUBLIC_SITE_ACCENT || fromYaml.accent || DEFAULT_CONFIG.accent,
  };
  return cached;
}

/**
 * Resolve the data directory. Defaults to <cwd>/../data (the repo layout).
 * Override with DATA_DIR for Actions/S3-download layouts.
 */
export function getDataDir(): string {
  return process.env.DATA_DIR || resolve(process.cwd(), '..', 'data');
}

/** Resolve a data file path (filename relative to the data dir). */
export function dataPath(filename: string): string {
  if (filename.startsWith('/')) return filename;
  return resolve(getDataDir(), filename);
}

/** Read a JSON data file; returns the parsed value or null on any failure. */
export function readDataJson<T = unknown>(filename: string): T | null {
  try {
    return JSON.parse(readFileSync(dataPath(filename), 'utf-8')) as T;
  } catch {
    return null;
  }
}
