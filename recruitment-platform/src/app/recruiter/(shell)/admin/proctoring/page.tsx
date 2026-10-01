import { guardedPage, routeMetadata } from "@/auth/guarded-page";

export const generateMetadata = routeMetadata("/admin/proctoring");
export default guardedPage("/admin/proctoring");
