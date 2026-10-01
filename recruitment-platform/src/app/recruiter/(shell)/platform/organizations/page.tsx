import { guardedPage, routeMetadata } from "@/auth/guarded-page";

export const generateMetadata = routeMetadata("/platform/organizations");
export default guardedPage("/platform/organizations");
