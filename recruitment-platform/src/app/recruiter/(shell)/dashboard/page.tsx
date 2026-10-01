import { DashboardBody } from "@/page/feature-bodies";
import { guardedPage, routeMetadata } from "@/page/guarded-page";

export const generateMetadata = routeMetadata("/dashboard");
export default guardedPage("/dashboard", DashboardBody);
