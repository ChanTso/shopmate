"""Container entry point; the host never imports or executes the submitted program."""

import json
import sys


def main():
    payload = json.load(sys.stdin)
    table = payload["table"]
    namespace = {
        "__name__": "__main__",
        "table": table,
        "columns": table["columns"],
        "rows": table["rows"],
    }
    # This entry point executes only inside the disposable, restricted container.
    exec(compile(payload["code"], "<analysis>", "exec"), namespace)  # noqa: S102


if __name__ == "__main__":
    main()
