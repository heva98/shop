# Shop ERP Design System

A calm, clear blue interface for a multi-branch shop ERP (Duka ERP): staff move fast between the till, stock, customers, reports and settings, so every screen is light, roomy and easy to scan. Inherited unchanged from the Pharmacy ERP design system (Dashboard, Analytics, Reports, Settings, Admin), with the brand mark swapped.

**For coding agents (Claude Code):** apply this system to the existing app without changing features, routes or data. Restyle what is there: replace colors, type, spacing, radii and shadows with the tokens below, and rebuild the shell (sidebar + top bar) and the components listed under *Components*. When something isn't covered, pick the closest existing pattern rather than inventing a new one.

## Voice and content

- Plain, operational English from the shopkeeper's side: "Review batches", "Save supplier", "Download report". Buttons say exactly what happens.
- Page titles are one word or a short noun ("Dashboard", "Reports"). Every page title gets a one-line subtitle in `muted` explaining scope ("Overview across all stores in your entity.").
- Money is always prefixed with the currency, set smaller and muted: `TZS 184.2M`. Store names follow `Store #003 — Kilimani`.
- Warnings name the count and the action: "4 batches are nearing expiry or already expired" + "Review the stock module for batches that need action."
- Empty states say what's missing and how to fix it: "No stores yet — Add your first store below to start recording stock and sales."
- No emoji, no exclamation marks, no jokes.

## Visual foundations

**Color.** Brand blue (`blue-600` #0B5ED7) is the identity: it fills the sidebar and the login panel. Actions are deep navy (`navy-800` #0B3D7A), never bright blue, so primary buttons read as heavier than links. Content sits on white cards (`surface-card`) over a cool off-white page (`surface-page` #F3F6FB). Tints (`tint-blue`) mark selection; semantic colors (success, warning, entity) are only used for state.

**Type.** One family: **Poppins** (Google Fonts, weights 400/500/600/700/800). Load it with:
`<link href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;500;600;700;800&display=swap" rel="stylesheet">`
Base text is 14px. Hierarchy comes from weight and size, not color: `page-title` 28/700, `section-title` 20/600, `card-title` 16/600, `body` 14/400, `small` 13, `label` 12/500, `overline` 11/600 uppercase with 1.2px tracking.

**Shape.** Rounded but not bubbly: 8px for controls, 10px for nav items and icon tiles, 16px for cards, 999px for chips and switches.

**Depth.** No borders on cards: separation comes from `shadow-card` (soft, blue-tinted). Inputs have no border either — they are filled `surface-input` boxes. Only primary buttons and the active nav pill get their own shadows.

**The circle motif.** Blue panels (sidebar, login) carry 2–3 overlapping solid circles in `blue-500` / `blue-650`, bleeding off the edge, sometimes with a soft inner shadow. This is the brand's signature; use it only on blue panels, never on white content.

**Layout.** App shell = blue sidebar (240px basis) + column with a white 72px top bar and a `main` area padded 32px, max-width ~1240px. Settings and Admin use a white sub-nav card (220px) beside the content. Grids use `repeat(auto-fit, minmax(220px, 1fr))` for stat cards and `minmax(300px, 1fr)` for chart cards. Everything wraps: at phone width the sidebar stacks on top and grids go to one column. Tables scroll inside their card (`overflow-x: auto`), never the page.

**Don'ts.** No gradients (except the soft shadows on decorative circles), no left-border accent cards, no emoji icons, no grey-on-grey text below 4.5:1, no bright-blue filled buttons, no borders around cards.

## Iconography

Simple 24×24 stroke icons, 2px stroke, round caps and joins (Lucide-style; `lucide-react` is a good match). Size 18px in nav and buttons, 16px in pills, 22px in icon tiles. Color: `currentColor` in nav; `blue-600` inside `tint-blue` tiles; `orange-fg` inside `orange-tint` tiles. Brand mark: a shopping-bag icon in `blue-600` inside a 40px white rounded square (radius 11px).

## Components

| Component | Key rules |
| --- | --- |
| **AppShell / Sidebar** | `blue-600` panel with circle motif at the bottom. Brand row (logo tile + "Duka ERP" 17/700 + 44px collapse button on `rgba(255,255,255,.12)`). Section labels in `overline` + `on-blue-label`. Items: 44px tall, radius-md, white text 14/500, 18px icon. Active: white pill, `navy-800` text 600, `shadow-nav-active`, `aria-current="page"`. |
| **TopBar** | White, 72px, bottom `border`. Left: store picker (filled `surface-input` button, store icon in blue, chevron) + role text in `muted`. Right: online pill (`success-bg`/`success-fg`, 8px `success-dot`) + 44px `navy-800` avatar with initials. |
| **Button** | Primary: `navy-800` fill, white 14/600, height 46, radius-sm, `shadow-button`. Secondary: white with 1.5px `navy-800` border and navy text. Neutral: white, 1.5px `outline-strong` border, `ink-2` text 500. Icon+label gap 8px. |
| **Input / Select** | Label above (`label` style, `ink-2`), 6px gap. Field: height 48, radius-sm, `surface-input`, no border, 14px text, placeholder `placeholder`. Focus: 2px `blue-600` outline offset 1px. Required: red `danger` asterisk after the label. Optional leading 18px icon inside the field. |
| **Card** | `surface-card`, radius-lg, padding 22–24px, `shadow-card`, no border. |
| **StatCard** | Card with label (13/500 muted) + 38px icon tile (radius-md, `tint-blue` or `orange-tint`) on the top row, value in `kpi` style `navy-800`, caption in `small` muted. Units (TZS, "of 14") smaller and muted inside the value. |
| **Alert banner** | Warning: `warning-bg`, 1px `warning-border`, radius-lg, 40px `warning-icon` disc with white "!", title 15/600 `warning-ink`, body 13 `warning-ink-2`, optional primary action on the right. `role="alert"`. |
| **Chip / Status pill** | radius-pill, 26px tall, 12/600. Scope "Per store": `tint-blue` + `navy-800`. Scope "Entity": `entity-tint` + `entity-fg`. Online: `success-bg` + `success-fg` with dot. |
| **Switch** | Real `<button role="switch" aria-checked>`, 44px hit area, 44×24 track, 18px white knob. On: `blue-600`. Off: `switch-off`. |
| **Table** | Inside a Card with `overflow-x: auto`. Header row `surface-thead`, `overline` labels in `muted`. Rows 16px padding, `border` top divider, first column 600 `ink`, others `ink-2`, emails as links. Empty state: centered 56px `tint-blue` disc with icon, 15/600 title, 13 muted hint. |
| **Sub-nav (Settings/Admin)** | White card, radius-lg, 10px padding. Items 44px min, radius-md, `ink-2` 14px. Active: `tint-blue` bg, `navy-800` text 600. |
| **ChartCard** | See *Charts* below. |
| **Report row** | Card row: 48px `tint-blue` icon tile, title + description, then "PDF" (secondary) and "Excel" (primary) download buttons with a download icon. |

## Charts

Charts are clean, bright and soft: smooth lines with small round points, rounded bars, roomy doughnuts, legends with round markers at the bottom. Library: **Chart.js 4** (any library is fine if it follows these rules).

**Chart card.** A Card with no padding of its own:
- Header: `card-title` (16/600 `ink`) + optional meta line in `small` `muted` ("TZS · by week"), optional 44px "⋯" options button on the right. Padding 18px 22px, then a 1px `border` divider.
- Body: padding 22px, chart height 260–300px (doughnut/pie 240px, centered).
- Grid of chart cards: `repeat(auto-fit, minmax(320px, 1fr))`, 20px gap.

**Series palette, in order:** `chart-1` blue → `chart-2` amber → `chart-3` purple → `chart-4` green → `chart-5` coral. Single-series charts are always `chart-1`. Two series: blue + amber. Never more than five series; group the rest as "Other" in `muted`. Use the same color for the same thing everywhere (e.g. Pageviews always blue).

**Type-by-type rules**
- **Line:** 2px stroke, `tension: 0.4`, points 3px filled with a 2px white ring (6px on hover). Single line may get a `chart-1-fill` area. Horizontal gridlines only.
- **Bar:** rounded top corners 6px, `maxBarThickness` 36, gap ~30% of the slot. Highlight the latest/current period in `navy-800` when it matters. Horizontal gridlines only.
- **Stacked bar:** 2px white border between segments (`borderColor: '#fff'`), only the top segment rounded. Order bottom → top from smallest to largest category.
- **Pie / doughnut:** prefer doughnut (`cutout: '62%'`) with the total in the hole (`kpi` style in `navy-800` + `small` muted label). 2px white separators. Percent labels inside slices only if ≥10%. ≤5 slices.
- **Radar:** `chart-1` and `chart-3` with their `-fill` tints, grid in `chart-grid`, point labels 12px `muted`.
- **Bubble / scatter:** solid series colors at 80% opacity, no outlines.

**Axes, labels, legend, tooltip.** Font Poppins 12px `muted` for ticks and legends. Grid `chart-grid`, baseline `chart-axis`, no vertical gridlines, no axis borders. Y axis starts at 0 for bars. Money ticks abbreviated (`TZS 1.2M`). Legend at the bottom, centered, round markers (`usePointStyle`), 16px spacing. Tooltip: `chart-tooltip` background, white text, radius 8, padding 10, no color box border. No chart titles inside the canvas — the card header is the title.

**Chart.js theme (drop-in)**

```js
import { Chart } from 'chart.js/auto';
export const chartColors = ['#0B5ED7', '#F59E0B', '#6E5BD0', '#22A45D', '#E5484D'];
Chart.defaults.font.family = 'Poppins, system-ui, sans-serif';
Chart.defaults.font.size = 12;
Chart.defaults.color = '#5B6472';
Chart.defaults.borderColor = '#EEF1F5';
Chart.defaults.maintainAspectRatio = false;
Chart.defaults.plugins.legend.position = 'bottom';
Chart.defaults.plugins.legend.labels.usePointStyle = true;
Chart.defaults.plugins.legend.labels.pointStyle = 'circle';
Chart.defaults.plugins.legend.labels.boxWidth = 8;
Chart.defaults.plugins.legend.labels.padding = 16;
Object.assign(Chart.defaults.plugins.tooltip, {
  backgroundColor: '#1B2333', padding: 10, cornerRadius: 8, boxPadding: 4,
  titleFont: { weight: '600' }, usePointStyle: true,
});
Object.assign(Chart.defaults.elements.line, { borderWidth: 2, tension: 0.4 });
Object.assign(Chart.defaults.elements.point, {
  radius: 3, hoverRadius: 6, borderWidth: 2, borderColor: '#FFFFFF',
});
Object.assign(Chart.defaults.elements.bar, {
  borderRadius: { topLeft: 6, topRight: 6 }, borderSkipped: 'bottom', maxBarThickness: 36,
});
Object.assign(Chart.defaults.elements.arc, { borderWidth: 2, borderColor: '#FFFFFF' });
// per chart: scales.x.grid.display = false; scales.y.border.display = false; scales.y.beginAtZero = true
```

## Accessibility

- All text meets 4.5:1 on its intended ground (white on `blue-600` = 5.9:1; `muted` on `surface-page` ≈ 5.5:1). Keep it that way.
- Every clickable thing is ≥ 44px and a real `<button>` or `<a href>`. Icon-only buttons get `aria-label`.
- Inputs always have a visible `<label for>`.
- Focus is visible: 2px `blue-600` outline.

## CSS variables (drop-in)

```css
:root {
  --blue-500:#1A74EE; --blue-600:#0B5ED7; --blue-650:#0E64DC; --blue-700:#0A5BCC;
  --navy-800:#0B3D7A; --link-hover:#083F94; --tint-blue:#E7F0FD; --on-blue-label:#DCE8FB;
  --surface-page:#F3F6FB; --surface-card:#FFFFFF; --surface-input:#EEF1F5; --surface-thead:#F6F8FB; --surface-subtle:#FAFBFD;
  --ink:#1B2333; --ink-2:#3C4555; --muted:#5B6472; --placeholder:#636C7B;
  --border:#E3E8EF; --divider:#D5DAE2; --outline-strong:#4A5363; --switch-off:#C3CBD6;
  --success-bg:#E6F6EE; --success-fg:#13693F; --success-dot:#1E9E5A;
  --warning-bg:#FFF6E0; --warning-border:#F3D58C; --warning-ink:#3D2A00; --warning-ink-2:#5C4510; --warning-icon:#E0660F;
  --orange-tint:#FDECDD; --orange-fg:#B4500B; --entity-tint:#FFF1DC; --entity-fg:#8A4B00; --danger:#C62828;
  --chart-1:#0B5ED7; --chart-2:#F59E0B; --chart-3:#6E5BD0; --chart-4:#22A45D; --chart-5:#E5484D;
  --chart-1-fill:rgba(11,94,215,.14); --chart-3-fill:rgba(110,91,208,.16);
  --chart-grid:#EEF1F5; --chart-axis:#D5DAE2; --chart-tooltip:#1B2333;
  --font-sans: Poppins, system-ui, -apple-system, "Segoe UI", sans-serif;
  --radius-sm:8px; --radius-md:10px; --radius-lg:16px; --radius-xl:20px; --radius-pill:999px;
  --shadow-card:0 10px 30px rgba(11,61,122,.08); --shadow-button:0 8px 18px rgba(11,61,122,.25);
  --shadow-nav-active:0 6px 16px rgba(4,30,80,.18); --shadow-login:0 30px 60px rgba(4,30,80,.35);
  --control-height:48px; --button-height:46px; --touch-min:44px; --topbar-height:72px; --sidebar-width:240px;
}
body { margin:0; font-family:var(--font-sans); font-size:14px; color:var(--ink); background:var(--surface-page); }
a { color:var(--blue-600); } a:hover { color:var(--link-hover); }
```

If the app uses Tailwind, MUI, Ant Design or similar, map these tokens into its theme config instead of hard-coding values in components.
