"""Report what makes the packaged app big.

    python tools/bundle_size.py [dist/UnitRegTimetable] [--top 25]

Prints the total size, the largest top-level items in _internal/, and the
largest single files, so changes to build_exe.py can be measured.
"""

import argparse
import os
import sys


def size_of(path):
    if os.path.isfile(path):
        return os.path.getsize(path)
    total = 0
    for folder, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(folder, name))
            except OSError:
                pass
    return total


def mb(value):
    return f"{value / 1024 / 1024:8.1f} MB"


def main():
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("folder", nargs="?", default=os.path.join(root_dir, "dist", "UnitRegTimetable"))
    parser.add_argument("--top", type=int, default=20)
    args = parser.parse_args()
    if not os.path.isdir(args.folder):
        sys.exit(f"Not found: {args.folder} (build it with python build_exe.py)")

    total = size_of(args.folder)
    print(f"Total: {mb(total)}  ({args.folder})\n")
    internal = os.path.join(args.folder, "_internal")
    base = internal if os.path.isdir(internal) else args.folder
    items = sorted(((size_of(os.path.join(base, name)), name) for name in os.listdir(base)), reverse=True)
    print(f"Largest items in {os.path.basename(base)}/:")
    for size, name in items[:args.top]:
        print(f"  {mb(size)}  {size / total * 100:5.1f}%  {name}")

    files = []
    for folder, _dirs, names in os.walk(args.folder):
        for name in names:
            path = os.path.join(folder, name)
            try:
                files.append((os.path.getsize(path), os.path.relpath(path, args.folder)))
            except OSError:
                pass
    print("\nLargest files:")
    for size, name in sorted(files, reverse=True)[:args.top]:
        print(f"  {mb(size)}  {name}")


if __name__ == "__main__":
    main()
