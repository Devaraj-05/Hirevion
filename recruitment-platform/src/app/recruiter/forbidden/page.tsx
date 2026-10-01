import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { Forbidden } from "@/auth/forbidden";

// The proxy rewrites here, with status 403, when a session asks for a page it may not open.
export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("forbidden");
  return { title: t("title") };
}

export default function ForbiddenPage() {
  return (
    <main id="main" className="px-6">
      <Forbidden />
    </main>
  );
}
