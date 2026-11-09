# QFAN smoke tests

Run from the repository root with:

```bash
python -m unittest discover -s tests -v
```

These tests cover local frame serialization and BLE fragmentation/reassembly helpers. They do not test physical BLE hardware or production network security.
