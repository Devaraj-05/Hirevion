import { guardedPage, routeMetadata } from "@/auth/guarded-page";

export const generateMetadata = routeMetadata("/platform/desktop-releases");
export default guardedPage("/platform/desktop-releases");
