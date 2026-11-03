import os

from setuptools import Extension, setup


extension = Extension(
    "dopplergeist._native_ridge",
    ["src/dopplergeist/_native_ridge.c"],
    optional=True,
    extra_compile_args=["/O2"] if os.name == "nt" else ["-O3"],
    libraries=[] if os.name == "nt" else ["m"],
)

setup(ext_modules=[extension])
