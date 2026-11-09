"""Compatibility entry point; application implementation lives in qfan.app."""
from qfan.app import QFANApp, main

__all__ = ["QFANApp", "main"]

if __name__ == "__main__":
    main()
