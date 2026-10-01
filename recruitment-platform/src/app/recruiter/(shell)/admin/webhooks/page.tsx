import { guardedPage, routeMetadata } from "@/page/guarded-page";

export const generateMetadata = routeMetadata("/admin/webhooks");
export default guardedPage("/admin/webhooks");
