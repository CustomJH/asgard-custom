import type { Metadata } from "next";

const siteUrl = "https://vanadis.kr";

export const metadata: Metadata = {
  title: "Design System Builder — vanadis",
  description:
    "Build a project-owned DESIGN.md from 440 quality-graded company references. Preview confirmed colors, typography, spacing, components, and context while unresolved fields stay absent.",
  alternates: {
    canonical: `${siteUrl}/builder`,
  },
  openGraph: {
    title: "Design System Builder — vanadis",
    description:
      "Build a project-owned DESIGN.md from 440 quality-graded company references. Confirmed evidence stays visible; unresolved fields stay absent.",
    type: "website",
    url: `${siteUrl}/builder`,
    siteName: "vanadis",
    images: [
      {
        url: "/og-image.png",
        width: 1200,
        height: 630,
        alt: "vanadis — Design System Builder",
      },
    ],
  },
  twitter: {
    card: "summary_large_image",
    title: "Design System Builder — vanadis",
    description:
      "Preview and export a project-owned DESIGN.md from 440 quality-graded company references.",
    images: ["/og-image.png"],
  },
};

export default function BuilderLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return children;
}
