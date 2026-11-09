# Package layout

`qfan/` provides the supported `python -m qfan` entry point and import-compatible module names. At this stage the implementation modules remain in the repository root; the package files re-export them so older commands keep working while the layout is migrated incrementally.

The `adapter` implementation is UDP-based and therefore uses the host operating system's IP networking. Claims of an IP-free transport should be treated as a design goal, not a property of the current prototype.
