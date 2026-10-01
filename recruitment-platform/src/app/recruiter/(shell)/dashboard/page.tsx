import { guardedPage, routeMetadata } from "@/auth/guarded-page";

export const generateMetadata = routeMetadata("/dashboard");
export default guardedPage("/dashboard");
