import { guardedPage, routeMetadata } from "@/auth/guarded-page";

export const generateMetadata = routeMetadata("/reports/analytics");
export default guardedPage("/reports/analytics");
