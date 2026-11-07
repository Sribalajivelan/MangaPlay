"""Static audit of a PyTorch .pt checkpoint: list every global the pickle would import.

Nothing is unpickled or executed; pickletools only decodes opcodes.
Usage: python audit_pt.py <file.pt>
"""
from __future__ import annotations

import pickletools
import sys
import zipfile
from collections import Counter

# Modules/names that a plain ultralytics/torch weights file legitimately references.
EXPECTED_PREFIXES = (
    "ultralytics.", "torch.", "torch._utils", "collections.", "torch.nn.", "torchvision.",
    "numpy.", "numpy._core", "_codecs", "builtins.set", "builtins.getattr",
)
# Anything that can run arbitrary commands or load arbitrary code.
DANGEROUS = (
    "os.", "posix.", "nt.", "subprocess.", "sys.", "socket.", "shutil.", "importlib.",
    "builtins.eval", "builtins.exec", "builtins.compile", "builtins.__import__",
    "builtins.open", "pickle.", "marshal.", "ctypes.", "runpy.", "webbrowser.", "requests.", "urllib.",
)


def globals_in(data: bytes) -> list[str]:
    found, strings = [], []
    for op, arg, _ in pickletools.genops(data):
        if op.name in {"UNICODE", "BINUNICODE", "SHORT_BINUNICODE", "BINUNICODE8"}:
            strings.append(arg)
        elif op.name == "GLOBAL":
            found.append(str(arg).replace(" ", "."))
        elif op.name == "STACK_GLOBAL" and len(strings) >= 2:
            found.append(f"{strings[-2]}.{strings[-1]}")
    return found


def main(path: str) -> int:
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        pkls = [n for n in names if n.endswith(".pkl")]
        print(f"zip entries: {len(names)}; pickle files: {pkls}")
        non_data = [n for n in names if not n.split("/")[-2:][0].endswith("data") and not n.endswith((".pkl", "version", ".format_version", ".storage_alignment", "byteorder"))]
        allg: list[str] = []
        for n in pkls:
            allg += globals_in(z.read(n))
    counts = Counter(allg)
    print(f"distinct globals: {len(counts)}")
    bad = [g for g in counts if g.startswith(DANGEROUS)]
    odd = [g for g in counts if not g.startswith(EXPECTED_PREFIXES) and g not in bad]
    for g, c in sorted(counts.items()):
        flag = "DANGEROUS" if g in bad else ("unexpected" if g in odd else "ok")
        print(f"  [{flag:<10}] {c:>4}x {g}")
    print()
    print("VERDICT:", "REJECT - dangerous imports present" if bad else ("REVIEW - unexpected imports" if odd else "no dangerous or unexpected imports found"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
