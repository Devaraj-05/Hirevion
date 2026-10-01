import { AccountBody } from "@/account/account-body";
import { guardedPage, routeMetadata } from "@/page/guarded-page";

export const generateMetadata = routeMetadata("/account");
export default guardedPage("/account", AccountBody);
