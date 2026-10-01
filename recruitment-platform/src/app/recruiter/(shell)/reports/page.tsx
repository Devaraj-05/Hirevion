import { SectionIndexBody } from "@/page/bodies";
import { guardedPage, routeMetadata } from "@/page/guarded-page";

export const generateMetadata = routeMetadata("/reports");
export default guardedPage("/reports", SectionIndexBody);
