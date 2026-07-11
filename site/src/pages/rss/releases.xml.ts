import rss from '@astrojs/rss';
import type { APIContext } from 'astro';
import { getSiteConfig, readDataJson } from '../../lib/config';

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
  const data = readDataJson<ReleaseData>('release-radar.json') ?? { updated_at: '', categories: [] };
  const site = getSiteConfig();

  const items = data.categories.flatMap((category) =>
    category.releases.map((release) => ({
      title: `${category.name} ${release.version}`,
      description: release.summary,
      pubDate: new Date(release.date),
      link: `${context.site}`,
    }))
  );

  const siteUrl = context.site?.toString() || site.url || 'https://example.com';

  return rss({
    title: `${site.title} — Release Radar`,
    description: 'Latest version updates across frameworks, runtimes, and languages',
    site: siteUrl,
    items,
  });
}
