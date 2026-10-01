import { guardedPage, routeMetadata } from "@/auth/guarded-page";

export const generateMetadata = routeMetadata("/reports/interview");
export default guardedPage("/reports/interview");
