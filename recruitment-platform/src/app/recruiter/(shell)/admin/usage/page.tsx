import { guardedPage, routeMetadata } from "@/auth/guarded-page";

export const generateMetadata = routeMetadata("/admin/usage");
export default guardedPage("/admin/usage");
