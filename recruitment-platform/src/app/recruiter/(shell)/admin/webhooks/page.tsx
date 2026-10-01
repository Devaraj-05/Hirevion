import { guardedPage, routeMetadata } from "@/auth/guarded-page";

export const generateMetadata = routeMetadata("/admin/webhooks");
export default guardedPage("/admin/webhooks");
