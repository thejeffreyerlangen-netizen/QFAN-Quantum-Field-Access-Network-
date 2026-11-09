import sys
from qfan.main import main

if __name__ == "__main__":
    main(["--role", "client"] + sys.argv[1:])
