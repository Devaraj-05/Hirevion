import { UsersBody } from "@/admin/bodies";
import { guardedPage, routeMetadata } from "@/page/guarded-page";

export const generateMetadata = routeMetadata("/admin/users");
export default guardedPage("/admin/users", UsersBody);
