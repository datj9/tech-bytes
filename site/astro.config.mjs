// @ts-check
import { defineConfig } from 'astro/config';

import tailwindcss from '@tailwindcss/vite';

// Site URL: PUBLIC_SITE_URL env > config-driven default. Blank keeps paths relative.
const siteUrl = process.env.PUBLIC_SITE_URL || '';

// Base path: required for GitHub Pages project sites (/<repo-name>/). Auto-detected
// from GITHUB_REPOSITORY when not overridden via PUBLIC_BASE_PATH.
let base = process.env.PUBLIC_BASE_PATH || '/';
if (base === '/' && process.env.GITHUB_REPOSITORY) {
  const [, repo] = process.env.GITHUB_REPOSITORY.split('/');
  if (repo) base = `/${repo}/`;
}

const config = {
  output: 'static',
  base,
  vite: {
    plugins: [tailwindcss()],
  },
};

// Astro requires `site` to be a valid URL when set; omit it entirely when blank
// so RSS/absolute URLs fall back to relative resolution.
if (siteUrl) {
  config.site = siteUrl;
}

// https://astro.build/config
export default defineConfig(config);
