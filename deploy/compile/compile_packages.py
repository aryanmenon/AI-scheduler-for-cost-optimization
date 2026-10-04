"""Compile installed Python packages to native extension modules and delete
their source, so a shipped image contains no readable .py source.

Run inside the Docker build after `pip install`, against the site-packages
directory holding the product's packages:

  python compile_packages.py /usr/local/lib/python3.12/site-packages \\
      telemetry_collector [more_packages ...]

Every module except a package's __init__.py (version string only) is
Cython-compiled to a stripped .so; the .py, generated .c, and __pycache__
are then removed. Fails loudly if any compiled module is missing or any
.py other than __init__.py survives, so a build can never silently ship
source. See docs/IP_PROTECTION.md for what this does and doesn't protect.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile


def _modules(site: str, package: str) -> list[str]:
    root = os.path.join(site, package)
    if not os.path.isdir(root):
        raise SystemExit(f"package {package!r} not found in {site}")
    found = []
    for dirpath, _, files in os.walk(root):
        for name in files:
            if name.endswith(".py") and name != "__init__.py":
                found.append(os.path.relpath(os.path.join(dirpath, name), site))
    return sorted(found)


def compile_packages(site: str, packages: list[str]) -> None:
    from Cython.Build import cythonize
    from Cython.Compiler import Options
    from setuptools import Extension, setup

    # Leave docstrings out of the binaries; comments never reach them.
    Options.docstrings = False

    sources = [m for p in packages for m in _modules(site, p)]
    extensions = [
        Extension(
            src[:-3].replace(os.sep, "."),
            [src],
            extra_compile_args=["-O2", "-g0"],
            extra_link_args=["-s"],  # strip symbol tables
        )
        for src in sources
    ]
    build_tmp = tempfile.mkdtemp(prefix="cython-build-")
    cwd = os.getcwd()
    os.chdir(site)
    try:
        setup(
            name="compiled",
            script_args=["-q", "build_ext", "--inplace", "--build-temp", build_tmp,
                         "--build-lib", os.path.join(build_tmp, "lib")],
            ext_modules=cythonize(
                extensions,
                build_dir=build_tmp,
                compiler_directives={
                    "language_level": 3,
                    # Keep plain Python semantics: don't turn annotations
                    # like `x: float` into C types with stricter behavior.
                    "annotation_typing": False,
                    "binding": True,
                },
                quiet=True,
            ),
        )
    finally:
        os.chdir(cwd)
        shutil.rmtree(build_tmp, ignore_errors=True)

    for src in sources:
        os.remove(os.path.join(site, src))
    for package in packages:
        for dirpath, dirnames, files in os.walk(os.path.join(site, package)):
            for d in [d for d in dirnames if d == "__pycache__"]:
                shutil.rmtree(os.path.join(dirpath, d))
            for name in files:
                if name.endswith(".c"):
                    os.remove(os.path.join(dirpath, name))
    verify(site, packages, sources)


def verify(site: str, packages: list[str], sources: list[str]) -> None:
    leftover = [m for p in packages for m in _modules(site, p)]
    if leftover:
        raise SystemExit(f"source still present after compiling: {leftover}")
    for src in sources:
        stem = os.path.join(site, src[:-3])
        directory, base = os.path.split(stem)
        if not any(f.startswith(base + ".") and f.endswith(".so") for f in os.listdir(directory)):
            raise SystemExit(f"no compiled module for {src}")
    print(f"compiled {len(sources)} modules in {', '.join(packages)}; no .py source left")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    compile_packages(sys.argv[1], sys.argv[2:])
