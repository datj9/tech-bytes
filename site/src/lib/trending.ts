/**
 * Trending data loader + schema normalizer.
 *
 * The gh_trending Lambda historically wrote two different shapes:
 *   - Legacy: `weekly`/`monthly` are objects `{ period, repos: Repo[] }` and
 *     repos have no `stars_this_period`.
 *   - Current: `weekly`/`monthly` are flat `Repo[]` arrays with `stars_this_period`.
 *
 * Archive pages render historical files, so both shapes must be tolerated or the
 * static build crashes on old data (e.g. `data.weekly.map is not a function`).
 * This module coerces either shape into the current flat `TrendingData`.
 */
import { readFileSync } from 'node:fs';

export interface Repo {
  name: string;
  url: string;
  description: string;
  language: string;
  stars: number;
  stars_this_period: number;
  summary: string;
}

export interface TrendingData {
  updated_at: string;
  weekly: Repo[];
  monthly: Repo[];
}

const EMPTY: TrendingData = { updated_at: '', weekly: [], monthly: [] };

function normalizeRepo(raw: unknown): Repo {
  const r = (raw ?? {}) as Record<string, unknown>;
  return {
    name: typeof r.name === 'string' ? r.name : '',
    url: typeof r.url === 'string' ? r.url : '',
    description: typeof r.description === 'string' ? r.description : '',
    language: typeof r.language === 'string' ? r.language : '',
    stars: typeof r.stars === 'number' ? r.stars : 0,
    stars_this_period: typeof r.stars_this_period === 'number' ? r.stars_this_period : 0,
    summary: typeof r.summary === 'string' ? r.summary : '',
  };
}

/** Coerce a `weekly`/`monthly` field from either schema into `Repo[]`. */
function normalizeBucket(value: unknown): Repo[] {
  if (Array.isArray(value)) {
    return value.map(normalizeRepo);
  }
  // Legacy shape: { period, repos: Repo[] }
  if (value && typeof value === 'object' && Array.isArray((value as { repos?: unknown }).repos)) {
    return ((value as { repos: unknown[] }).repos).map(normalizeRepo);
  }
  return [];
}

/** Normalize a parsed trending JSON object (either schema) into `TrendingData`. */
export function normalizeTrending(raw: unknown): TrendingData {
  if (!raw || typeof raw !== 'object') {
    return { ...EMPTY };
  }
  const obj = raw as Record<string, unknown>;
  const updated_at =
    typeof obj.updated_at === 'string'
      ? obj.updated_at
      : typeof obj.generated_at === 'string'
        ? obj.generated_at
        : '';
  return {
    updated_at,
    weekly: normalizeBucket(obj.weekly),
    monthly: normalizeBucket(obj.monthly),
  };
}

/** Read a trending JSON file and normalize it; returns empty data if missing/invalid. */
export function loadTrending(path: string): TrendingData {
  try {
    return normalizeTrending(JSON.parse(readFileSync(path, 'utf-8')));
  } catch {
    return { ...EMPTY };
  }
}
