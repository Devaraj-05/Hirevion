import { guardedPage, routeMetadata } from "@/page/guarded-page";

export const generateMetadata = routeMetadata("/platform/app-catalog");
export default guardedPage("/platform/app-catalog");
