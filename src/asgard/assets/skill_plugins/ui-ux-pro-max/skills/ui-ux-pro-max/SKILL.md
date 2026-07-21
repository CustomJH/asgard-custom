---
name: ui-ux-pro-max
description: Search UI/UX evidence for product type, design-system direction, accessibility, typography, color, motion, charts, and framework-specific implementation. Use for new pages, broad redesigns, or focused UX/style/stack decisions; use 21st or Aceternity instead when the need is an existing component implementation.
triggers: ui, ux, interface, screen, page, website, landing, landing page, hero, redesign, dashboard, form, component, accessibility, color, typography, layout, responsive, animation, react, next.js, vue, swiftui, flutter, 디자인, 화면, 페이지, 신규 페이지, 웹사이트, 랜딩, 랜딩페이지, 랜딩 페이지, 히어로, 리디자인, 대시보드, 폼, 컴포넌트, 접근성, 색상, 타이포, 레이아웃, 반응형
agent: freyja, freyja-lead
agents: freyja, freyja-lead
---

# UI/UX Pro Max — Freyja resource skill

Use the bundled database as evidence for visual and interaction decisions. First identify the
product type, audience, page, and implementation stack. Preserve an existing project design system
unless the task explicitly asks to replace it.

For a new page or broad redesign, query a complete recommendation:

    asgard skills run ui-ux-pro-max "<product, audience, style, page>" --design-system -p "<project>"

For a focused decision, query only the relevant domain or stack:

    asgard skills run ui-ux-pro-max "<question>" --domain <style|color|chart|landing|product|ux|typography|google-fonts|icons|gsap|react|web>
    asgard skills run ui-ux-pro-max "<question>" --stack <react|nextjs|vue|svelte|astro|swiftui|react-native|flutter|nuxtjs|nuxt-ui|html-tailwind|shadcn|jetpack-compose|threejs|angular|laravel>

Treat results as recommendations, not a license to overwrite repository conventions. If a query
returns no match, retry once with broader terms; if it still misses, state that the database had no
match before using general design knowledge.

Before handoff, check keyboard access, visible focus, semantic controls, contrast, reduced motion,
responsive layout, loading/empty/error states, and whether the implemented hierarchy matches the
task's primary user action. Use the browser or rendered artifact when available; source inspection
alone is not a visual verdict.

This is the Asgard adapter for upstream ui-ux-pro-max v2.11.0 at revision
`5c0946f66120079258e1efc8e436d78ec793877c`. The complete upstream instructions are retained in
`references/upstream-skill.md`; this shorter contract keeps Freyja's prompt budget bounded.
