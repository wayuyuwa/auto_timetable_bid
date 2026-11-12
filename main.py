"""Desktop entry point for the Vue frontend and Python backend.

    main.py                      start the app
    main.py --test-real-server   log in to the real portal, read student info, stop
                                 (see src/real_server_test.py for options)
"""

import sys


if __name__ == "__main__":
    if "--test-real-server" in sys.argv[1:]:
        from src.real_server_test import run as run_real_server_test

        sys.exit(run_real_server_test(sys.argv[1:]))
    from src.web_backend import run

    run()
