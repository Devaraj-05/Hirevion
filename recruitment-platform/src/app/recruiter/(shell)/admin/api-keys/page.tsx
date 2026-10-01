import { guardedPage, routeMetadata } from "@/auth/guarded-page";

export const generateMetadata = routeMetadata("/admin/api-keys");
export default guardedPage("/admin/api-keys");
