import { guardedPage, routeMetadata } from "@/page/guarded-page";

export const generateMetadata = routeMetadata("/admin/integrations");
export default guardedPage("/admin/integrations");
