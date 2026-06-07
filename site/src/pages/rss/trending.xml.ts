import rss from '@astrojs/rss';
import type { APIContext } from 'astro';
import { resolve } from 'node:path';
import { loadTrending, type Repo } from '../../lib/trending';

export function GET(context: APIContext) {
  const dataPath = resolve(process.cwd(), '..', 'data', 'gh-trending.json');
  const data = loadTrending(dataPath);

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
