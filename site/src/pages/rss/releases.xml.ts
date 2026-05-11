import rss from '@astrojs/rss';
import type { APIContext } from 'astro';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

interface Release {
  version: string;
  date: string;
  summary: string;
  details: string;
}

interface Category {
  name: string;
  icon: string;
  releases: Release[];
}

interface ReleaseData {
  updated_at: string;
  categories: Category[];
}

export function GET(context: APIContext) {
  let data: ReleaseData = { updated_at: '', categories: [] };

  try {
    const dataPath = resolve(process.cwd(), '..', 'data', 'release-radar.json');
    data = JSON.parse(readFileSync(dataPath, 'utf-8'));
  } catch {
    // data file not found — use empty defaults
  }

  const items = data.categories.flatMap((category) =>
    category.releases.map((release) => ({
      title: `${category.name} ${release.version}`,
      description: release.summary,
      pubDate: new Date(release.date),
      link: `${context.site}`,
    }))
  );

  return rss({
    title: 'Tech Bytes — Release Radar',
    description: 'Latest version updates across frameworks, runtimes, and languages',
    site: context.site!.toString(),
    items,
  });
}
