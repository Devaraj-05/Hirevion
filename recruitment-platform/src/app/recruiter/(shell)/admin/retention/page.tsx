import { guardedPage, routeMetadata } from "@/auth/guarded-page";

export const generateMetadata = routeMetadata("/admin/retention");
export default guardedPage("/admin/retention");
