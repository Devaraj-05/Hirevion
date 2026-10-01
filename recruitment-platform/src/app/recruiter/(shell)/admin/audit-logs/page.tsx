import { guardedPage, routeMetadata } from "@/page/guarded-page";

export const generateMetadata = routeMetadata("/admin/audit-logs");
export default guardedPage("/admin/audit-logs");
