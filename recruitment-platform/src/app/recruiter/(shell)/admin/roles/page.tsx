import { guardedPage, routeMetadata } from "@/auth/guarded-page";

export const generateMetadata = routeMetadata("/admin/roles");
export default guardedPage("/admin/roles");
