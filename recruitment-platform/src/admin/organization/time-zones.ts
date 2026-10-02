/**
 * Browsers list time zones by CLDR's names, which keep some IANA names the tz database has since
 * renamed (`Asia/Calcutta` for `Asia/Kolkata`). The API accepts both, but the profile should show
 * and store the current ones, and the organisation default (`Asia/Kolkata`) must stay choosable.
 */
const CURRENT_NAMES: Readonly<Record<string, string>> = {
  "Africa/Asmera": "Africa/Asmara",
  "America/Buenos_Aires": "America/Argentina/Buenos_Aires",
  "America/Catamarca": "America/Argentina/Catamarca",
  "America/Coral_Harbour": "America/Atikokan",
  "America/Cordoba": "America/Argentina/Cordoba",
  "America/Godthab": "America/Nuuk",
  "America/Indianapolis": "America/Indiana/Indianapolis",
  "America/Jujuy": "America/Argentina/Jujuy",
  "America/Louisville": "America/Kentucky/Louisville",
  "America/Mendoza": "America/Argentina/Mendoza",
  "Asia/Calcutta": "Asia/Kolkata",
  "Asia/Katmandu": "Asia/Kathmandu",
  "Asia/Rangoon": "Asia/Yangon",
  "Asia/Saigon": "Asia/Ho_Chi_Minh",
  "Atlantic/Faeroe": "Atlantic/Faroe",
  "Europe/Kiev": "Europe/Kyiv",
  "Pacific/Enderbury": "Pacific/Kanton",
  "Pacific/Ponape": "Pacific/Pohnpei",
  "Pacific/Truk": "Pacific/Chuuk",
};

/** The zones to offer, by their current names, sorted, with `current` always among them. */
export function timeZoneOptions(
  current: string,
  supported: readonly string[] = Intl.supportedValuesOf("timeZone"),
): string[] {
  const names = new Set([current, ...supported.map((zone) => CURRENT_NAMES[zone] ?? zone)]);
  return [...names].sort();
}
