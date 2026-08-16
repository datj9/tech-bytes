import rss from '@astrojs/rss';
import type { APIContext } from 'astro';
import { dataPath, getSiteConfig } from '../../lib/config';
import { loadTrending, type Repo } from '../../lib/trending';

export function GET(context: APIContext) {
  const data = loadTrending(dataPath('gh-trending.json'));
  const site = getSiteConfig();

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

  const siteUrl = context.site?.toString() || site.url || 'https://example.com';

  return rss({
    title: `${site.title} — GitHub Trending`,
    description: 'Trending GitHub repositories, summarized weekly',
    site: siteUrl,
    items,
  });
}
