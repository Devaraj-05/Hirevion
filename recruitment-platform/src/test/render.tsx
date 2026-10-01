import { TooltipProvider } from "@hirevion/ui";
import { render } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import type { ReactElement } from "react";
import messages from "../../messages/en-IN.json";

/** Renders with the en-IN catalogue and the providers the app's root layout supplies. */
export function renderWithIntl(ui: ReactElement) {
  return render(
    <NextIntlClientProvider locale="en-IN" messages={messages} timeZone="Asia/Kolkata">
      <TooltipProvider>{ui}</TooltipProvider>
    </NextIntlClientProvider>,
  );
}
