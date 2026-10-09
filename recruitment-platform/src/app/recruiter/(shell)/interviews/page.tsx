import { InterviewsBody } from "@/interviews/bodies";
import { guardedPage, routeMetadata } from "@/page/guarded-page";

export const generateMetadata = routeMetadata("/interviews");
export default guardedPage("/interviews", InterviewsBody);
