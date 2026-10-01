import { z } from "zod";

// Zod 4 decides, as each schema is built, whether to compile its parser with `new Function`,
// which the CSP forbids; the probe alone logs a CSP violation. Importing z from here (a lint
// rule enforces it) guarantees the setting runs before any schema exists.
z.config({ jitless: true });

export { z };
