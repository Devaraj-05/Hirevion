import { guardedPage, routeMetadata } from "@/page/guarded-page";

export const generateMetadata = routeMetadata("/admin/retention");
export default guardedPage("/admin/retention");
