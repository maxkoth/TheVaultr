# Vaultr — Marketing Site

A modern, production-ready marketing landing page for **Vaultr**, an iOS app that scans your sports cards, shows their real market value, and recommends what to do with them (sell, grade, hold, or bulk).

## Overview

- **Single self-contained file** — everything lives in `index.html` (embedded CSS + JS).
- **No build step** — only external dependencies are Google Fonts (Inter) and Lucide icons via CDN.
- **Fully responsive** — mobile-first, polished on phone and desktop.
- Light theme, purple accent (`#5B5BD6`), soft shadows, rounded corners, and tasteful scroll fade-in animations.

## Sections

Navigation · Hero (with CSS phone mockup) · The Problem · Features · How It Works · Who It's For · FAQ (accordion) · Waitlist CTA · Footer.

## Deploy to Vercel

This is a static site. Deploy in seconds:

```bash
npx vercel
```

Or connect the repo in the Vercel dashboard — no framework preset or build command needed (output is the repo root).

## Local preview

Just open `index.html` in a browser, or:

```bash
python3 -m http.server 8000
# then visit http://localhost:8000
```
