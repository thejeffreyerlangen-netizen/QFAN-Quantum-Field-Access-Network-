# Client

Install dependencies with `INSTALL.bat`, then run `START_CLIENT.bat`. The client and host need a reachable transport; for the optional shared-folder carrier, configure both to use the same mailbox path. Alternatively, pass the host address with `--hub` to `python -m qfan`. The prototype does not provide cryptographic transport security; see `../docs/SPEC.md`.