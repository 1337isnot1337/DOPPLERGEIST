import os

from setuptools import Extension, setup


extension = Extension(
    "dopplergeist._native_ridge",
    ["src/dopplergeist/_native_ridge.c"],
    optional=True,
    extra_compile_args=["/O2", "/fp:strict"] if os.name == "nt" else
        ["-O3", "-ffp-contract=off", "-fno-fast-math"],
    libraries=[] if os.name == "nt" else ["m"],
)

acoustic_extension = Extension(
    "dopplergeist._native_acoustic",
    ["src/dopplergeist/_native_acoustic.c"],
    optional=True,
    extra_compile_args=["/O2", "/fp:strict"] if os.name == "nt" else
        ["-O3", "-ffp-contract=off", "-fno-fast-math"],
    libraries=[] if os.name == "nt" else ["m"],
)

cpa_extension = Extension(
    "dopplergeist._native_cpa",
    ["src/dopplergeist/_native_cpa.c"],
    optional=True,
    extra_compile_args=["/O2", "/fp:strict"] if os.name == "nt" else
        ["-O3", "-ffp-contract=off", "-fno-fast-math"],
    libraries=[] if os.name == "nt" else ["m"],
)

index_extension = Extension(
    "dopplergeist._native_index",
    ["src/dopplergeist/_native_index.c"],
    optional=True,
    extra_compile_args=["/O2"] if os.name == "nt" else ["-O3"],
)

setup(ext_modules=[extension, acoustic_extension, cpa_extension, index_extension])
