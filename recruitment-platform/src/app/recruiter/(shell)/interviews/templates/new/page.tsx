import { NewTemplateBody } from "@/interviews/bodies";
import { guardedPage, routeMetadata } from "@/page/guarded-page";

export const generateMetadata = routeMetadata("/interviews/templates/new");
export default guardedPage("/interviews/templates/new", NewTemplateBody);
