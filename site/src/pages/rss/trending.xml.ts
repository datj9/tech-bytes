import rss from '@astrojs/rss';
import type { APIContext } from 'astro';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

interface Repo {
  name: string;
  url: string;
  description: string;
  language: string;
  stars: number;
  stars_this_period: number;
  summary: string;
}

interface TrendingData {
  updated_at: string;
  weekly: Repo[];
  monthly: Repo[];
}

export function GET(context: APIContext) {
  let data: TrendingData = { updated_at: '', weekly: [], monthly: [] };

  try {
    const dataPath = resolve(process.cwd(), '..', 'data', 'gh-trending.json');
    data = JSON.parse(readFileSync(dataPath, 'utf-8'));
  } catch {
    // data file not found — use empty defaults
  }

  const pubDate = data.updated_at ? new Date(data.updated_at) : new Date();

  // Combine weekly and monthly, deduplicating by repo name (weekly takes priority)
  const seen = new Set<string>();
  const allRepos: Repo[] = [];

  for (const repo of [...data.weekly, ...data.monthly]) {
    if (!seen.has(repo.name)) {
      seen.add(repo.name);
      allRepos.push(repo);
    }
  }

  const items = allRepos.map((repo) => ({
    title: repo.name,
    description: repo.summary,
    link: repo.url,
    pubDate,
  }));

  return rss({
    title: 'Tech Bytes — GitHub Trending',
    description: 'Trending GitHub repositories, summarized weekly',
    site: context.site!.toString(),
    items,
  });
}
