import rss from '@astrojs/rss';
import type { APIContext } from 'astro';
import { getSiteConfig, readDataJson } from '../../lib/config';

interface Story {
  title: string;
  url: string;
  score: number;
  comments: number;
  hn_url: string;
  summary: string;
}

interface HNData {
  date?: string;
  generated_at?: string;
  stories: Story[];
}

export function GET(context: APIContext) {
  const data = readDataJson<HNData>('hn-digest.json') ?? { stories: [] };
  const site = getSiteConfig();

  const pubDate = data.date || data.generated_at ? new Date(data.date || data.generated_at!) : new Date();

  const items = data.stories.map((story) => ({
    title: story.title,
    description: story.summary,
    link: story.url,
    pubDate,
  }));

  const siteUrl = context.site?.toString() || site.url || 'https://example.com';

  return rss({
    title: `${site.title} — HN Daily Digest`,
    description: 'Top Hacker News stories, summarized daily',
    site: siteUrl,
    items,
  });
}
