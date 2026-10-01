import { guardedPage, routeMetadata } from "@/auth/guarded-page";

export const generateMetadata = routeMetadata("/reports/proctoring");
export default guardedPage("/reports/proctoring");
