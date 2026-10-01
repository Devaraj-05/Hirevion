import { guardedPage, routeMetadata } from "@/auth/guarded-page";

export const generateMetadata = routeMetadata("/platform/audit");
export default guardedPage("/platform/audit");
