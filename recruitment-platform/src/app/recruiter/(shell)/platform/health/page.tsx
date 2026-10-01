import { guardedPage, routeMetadata } from "@/page/guarded-page";

export const generateMetadata = routeMetadata("/platform/health");
export default guardedPage("/platform/health");
