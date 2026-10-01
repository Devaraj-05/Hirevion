import { guardedPage, routeMetadata } from "@/page/guarded-page";

export const generateMetadata = routeMetadata("/admin/departments");
export default guardedPage("/admin/departments");
