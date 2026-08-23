# Validation record

The package was validated in the Ubuntu sandbox on 2026-08-24.

| Check | Result |
| --- | --- |
| FastAPI lifecycle tests | 3 passed |
| Python bytecode compilation | Passed |
| Shell-script syntax check | Passed |
| HTTP `/healthz` smoke test | Passed |
| HTTP license creation smoke test | Passed |
| License hash not exposed in creation response | Passed |
| EX4/EX5 compilation | Not run; MetaEditor and Wine were not installed in the build environment |

The MQL source is ready for compilation by MetaEditor. Use `scripts/build_mql.sh` on an Ubuntu host with Wine and a real MetaEditor executable, or compile the `.mq4`/`.mq5` files in MetaEditor on Windows. The licensing API’s online behavior was verified against a real local HTTP process; production use should terminate TLS through the included reverse-proxy configuration.
