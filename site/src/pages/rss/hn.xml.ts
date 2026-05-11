import rss from '@astrojs/rss';
import type { APIContext } from 'astro';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

interface Story {
  title: string;
  url: string;
  score: number;
  comments: number;
  hn_url: string;
  summary: string;
}

interface HNData {
  date: string;
  stories: Story[];
}

export function GET(context: APIContext) {
  let data: HNData = { date: '', stories: [] };

  try {
    const dataPath = resolve(process.cwd(), '..', 'data', 'hn-digest.json');
    data = JSON.parse(readFileSync(dataPath, 'utf-8'));
  } catch {
    // data file not found — use empty defaults
  }

  const pubDate = data.date ? new Date(data.date) : new Date();

  const items = data.stories.map((story) => ({
    title: story.title,
    description: story.summary,
    link: story.url,
    pubDate,
  }));

  return rss({
    title: 'Tech Bytes — HN Daily Digest',
    description: 'Top Hacker News stories, summarized daily',
    site: context.site!.toString(),
    items,
  });
}
