{
  description = "DOPPLERGEIST development environment (Python 3.12 + ffmpeg + geospatial/audio system libs)";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  };

  outputs = { self, nixpkgs }:
    let
      systems = [
        "x86_64-linux"
        "aarch64-linux"
        "x86_64-darwin"
        "aarch64-darwin"
      ];
      forEachSystem = f: nixpkgs.lib.genAttrs systems (system: f nixpkgs.legacyPackages.${system});
    in
    {
      devShells = forEachSystem (pkgs:
        let
          python = pkgs.python312;
        in
        {
          default = pkgs.mkShell {
            name = "dopplergeist-dev";

            packages = [
              python
              pkgs.ffmpeg # provides ffmpeg + ffprobe (libmp3lame encoder needed by MP3 smoke tests)
              pkgs.gh # GitHub CLI, needed for checkpoint-asset downloads
              pkgs.git
              pkgs.pkg-config
              pkgs.stdenv.cc
              # Native libraries behind the pip dependencies in pyproject.toml
              # (rasterio -> GDAL/PROJ/GEOS/HDF5/netCDF, soundfile -> libsndfile,
              #  scipy/numpy -> OpenBLAS, matplotlib -> freetype).
              pkgs.gdal
              pkgs.proj
              pkgs.geos
              pkgs.hdf5
              pkgs.netcdf
              pkgs.libsndfile
              pkgs.fftw
              pkgs.openblas
              pkgs.freetype
              pkgs.zlib
            ];

            shellHook = ''
              # Pinned manylinux wheels (e.g. rasterio) need libz/libstdc++
              # from outside the venv; Nix does not put them on the loader
              # path by default.
              export LD_LIBRARY_PATH="${pkgs.lib.makeLibraryPath [ pkgs.zlib pkgs.expat pkgs.stdenv.cc.cc ]}:''${LD_LIBRARY_PATH:-}"
              # Match the CI/threading defaults in .github/workflows.
              export MPLBACKEND="''${MPLBACKEND:-Agg}"
              export PYTHONUNBUFFERED="''${PYTHONUNBUFFERED:-1}"
              export OPENBLAS_NUM_THREADS="''${OPENBLAS_NUM_THREADS:-1}"
              export OMP_NUM_THREADS="''${OMP_NUM_THREADS:-1}"

              # Let pip builds find the Nix-provided native libraries.
              export GDAL_DATA="${pkgs.gdal}/share/gdal"
              export PROJ_DATA="${pkgs.proj}/share/proj"
              export PKG_CONFIG_PATH="${pkgs.libsndfile}/lib/pkgconfig:${pkgs.hdf5}/lib/pkgconfig:''${PKG_CONFIG_PATH:-}"

              echo "DOPPLERGEIST dev shell: $(python --version 2>&1), $(ffmpeg -version 2>/dev/null | head -1)"
              echo "Create an isolated env per docs/SETUP.md:"
              echo "  python -m venv .venv && .venv/bin/python -m pip install -e . && .venv/bin/dopplergeist --version"
            '';
          };
        });
    };
}
