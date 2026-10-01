import { guardedPage, routeMetadata } from "@/page/guarded-page";

export const generateMetadata = routeMetadata("/admin/api-keys");
export default guardedPage("/admin/api-keys");
