import { guardedPage, routeMetadata } from "@/auth/guarded-page";

export const generateMetadata = routeMetadata("/reports/candidate");
export default guardedPage("/reports/candidate");
