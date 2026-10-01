import { guardedPage, routeMetadata } from "@/page/guarded-page";

export const generateMetadata = routeMetadata("/admin/proctoring");
export default guardedPage("/admin/proctoring");
