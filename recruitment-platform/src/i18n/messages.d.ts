import type catalogue from "../../messages/en-IN.json";
import type { Locale } from "./locales";

// Type-checks every translation key against the default catalogue; a test keeps en-US in step.
declare module "next-intl" {
  interface AppConfig {
    Locale: Locale;
    Messages: typeof catalogue;
  }
}
