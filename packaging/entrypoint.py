from multiprocessing import freeze_support

from probe.cli import main

if __name__ == "__main__":
    freeze_support()
    main()
