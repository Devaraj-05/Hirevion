import { guardedPage, routeMetadata } from "@/page/guarded-page";
import { QuestionsBody } from "@/questions/bodies";

export const generateMetadata = routeMetadata("/questions");
export default guardedPage("/questions", QuestionsBody);
