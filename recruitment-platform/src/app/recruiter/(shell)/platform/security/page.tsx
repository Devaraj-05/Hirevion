import { guardedPage, routeMetadata } from "@/auth/guarded-page";

export const generateMetadata = routeMetadata("/platform/security");
export default guardedPage("/platform/security");
