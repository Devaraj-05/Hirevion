"""The interview simulator (SP-09a; master plan §14 testing): a synthetic candidate that signs in
like the desktop app (a P-256 device key, a DPoP proof per request) and answers as one of six
personas: strong, partial, weak, silent, adversarial and cheating.

In CI it drives the API through ASGI in text mode on the mock AI; locally `hv interview-sim`
drives a running API over HTTP. Its data is synthetic.
"""
