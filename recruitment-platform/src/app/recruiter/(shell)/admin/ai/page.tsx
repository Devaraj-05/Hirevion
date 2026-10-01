import { guardedPage, routeMetadata } from "@/auth/guarded-page";

export const generateMetadata = routeMetadata("/admin/ai");
export default guardedPage("/admin/ai");
