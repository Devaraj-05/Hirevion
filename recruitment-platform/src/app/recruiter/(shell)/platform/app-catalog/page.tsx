import { guardedPage, routeMetadata } from "@/auth/guarded-page";

export const generateMetadata = routeMetadata("/platform/app-catalog");
export default guardedPage("/platform/app-catalog");
