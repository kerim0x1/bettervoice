"""`python -m bettervoice` starts the app (see bettervoice.app for options)."""

if __name__ == "__main__":  # not in the recognition process, which imports this too
    import multiprocessing

    multiprocessing.freeze_support()  # the packaged app starts that process as itself

    from bettervoice.cli import main

    main()
