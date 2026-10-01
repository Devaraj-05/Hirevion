import { guardedPage, routeMetadata } from "@/auth/guarded-page";

export const generateMetadata = routeMetadata("/admin/audit-logs");
export default guardedPage("/admin/audit-logs");
