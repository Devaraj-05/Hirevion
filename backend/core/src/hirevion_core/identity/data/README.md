# common-passwords.txt

The local half of the breached-password check (SP-02 spec, "Passwords"). It always applies, even
when Have I Been Pwned can't be reached, and it is the only check in CI.

- **Source:** SecLists, `Passwords/Common-Credentials/xato-net-10-million-passwords-100000.txt`, at
  commit `c205c36a445bff37f8e58a9ec829105cd4975c58`
  (<https://github.com/danielmiessler/SecLists>).
- **Licence:** MIT, Copyright (c) 2018 Daniel Miessler.
- **Filter:** entries of 8 or more characters (the lowest minimum the policy will ever use, once
  MFA allows it), lower-cased, de-duplicated, in the original order: 38,451 entries.
