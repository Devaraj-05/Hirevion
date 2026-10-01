import { NotificationsBody } from "@/page/bodies";
import { guardedPage, routeMetadata } from "@/page/guarded-page";

export const generateMetadata = routeMetadata("/notifications");
export default guardedPage("/notifications", NotificationsBody);
