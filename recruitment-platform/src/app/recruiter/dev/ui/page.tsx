import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { devToolsEnabled } from "@/config/environment";
import { Gallery } from "@/dev/gallery";

export const metadata: Metadata = { title: "Component gallery", robots: { index: false } };

/** Every design-system component in both themes, for review and the axe checks. Dev only. */
export default function GalleryPage() {
  if (!devToolsEnabled()) notFound();
  return <Gallery />;
}
