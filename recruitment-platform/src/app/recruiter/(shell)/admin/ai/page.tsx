import { guardedPage, routeMetadata } from "@/page/guarded-page";

export const generateMetadata = routeMetadata("/admin/ai");
export default guardedPage("/admin/ai");
