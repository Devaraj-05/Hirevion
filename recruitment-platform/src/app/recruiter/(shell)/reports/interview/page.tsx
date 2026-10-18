import { guardedPage, routeMetadata } from "@/page/guarded-page";
import { InterviewReportsBody } from "@/reports/bodies";

export const generateMetadata = routeMetadata("/reports/interview");
export default guardedPage("/reports/interview", InterviewReportsBody);
