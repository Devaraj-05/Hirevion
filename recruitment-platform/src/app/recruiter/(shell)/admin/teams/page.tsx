import { guardedPage, routeMetadata } from "@/auth/guarded-page";

export const generateMetadata = routeMetadata("/admin/teams");
export default guardedPage("/admin/teams");
