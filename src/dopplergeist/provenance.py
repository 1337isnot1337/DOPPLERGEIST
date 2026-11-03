"""File provenance for the configured research pipeline, using only the stdlib.

Hashes identify supplied inputs. They do not establish that a caller chose event
windows, physical bounds, or a search area independently of a known location.
"""
import hashlib
from importlib.machinery import EXTENSION_SUFFIXES
from pathlib import Path


def implementation_provenance(code_root):
    """Hash this package, retaining legacy paths relative to its install parent.

    The parent can be a checkout's src directory or an installed site-packages
    directory. Unrelated installed libraries are not implementation sources.
    """
    root = Path(code_root).resolve()
    package_root = root / "dopplergeist"
    if not package_root.is_dir():
        raise FileNotFoundError(f"Implementation package is absent: {package_root}")
    digest = hashlib.sha256()
    sources = []
    native_paths = [package_root / f"_native_ridge{suffix}" for suffix in EXTENSION_SUFFIXES
                    if (package_root / f"_native_ridge{suffix}").is_file()]
    for path in sorted([*package_root.rglob("*.py"), *native_paths]):
        relative = str(path.relative_to(root))
        data = path.read_bytes()
        # Preserve the existing aggregate digest format for downstream readers.
        digest.update(relative.encode())
        digest.update(data)
        sources.append({"path": str(path), "relative_path": relative,
                        "sha256": hashlib.sha256(data).hexdigest()})
    return {"sha256": digest.hexdigest(), "sources": sources}


class RunProvenance:
    """Capture declared inputs before use and late-discovered terrain inputs.

    The configuration digest uses the exact bytes parsed by the caller. Other
    inputs are hashed when registered; no source files are copied or locked.
    """

    def __init__(self, config_path, config_bytes):
        self.config_path = Path(config_path).resolve()
        self._sources = {}
        self._limitations = [
            "Input hashes do not establish that event windows, physical bounds, "
            "or search bounds were chosen independently of ground truth.",
            "Input and code files are hashed at run startup, but are not copied "
            "or locked. Their contents could change during execution. "
            "Copernicus catalogue and exposed used-tile paths are captured "
            "after terrain sampling.",
        ]
        self.config_sha256 = hashlib.sha256(config_bytes).hexdigest()
        self._register(self.config_path, self.config_sha256, "configuration",
                       "parsed_configuration")

    def local(self, value):
        path = Path(value)
        return path if path.is_absolute() else self.config_path.parent / path

    def _register(self, path, digest, role, captured_at):
        key = str(Path(path).resolve())
        previous = self._sources.get(key)
        if previous is not None:
            if previous["sha256"] != digest:
                raise ValueError(f"Input changed between provenance captures: {key}")
            if role not in previous["roles"]:
                previous["roles"].append(role)
                previous["roles"].sort()
            return
        self._sources[key] = {"path": key, "sha256": digest, "roles": [role],
                              "captured_at": captured_at}

    def add_file(self, path, role, captured_at="before_execution"):
        path = Path(path).resolve()
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        self._register(path, digest, role, captured_at)

    def collect_declared_inputs(self, config):
        self.add_file(self.local(config["audio"]), "audio")
        for path in config["tracks"]:
            self.add_file(self.local(path), "tracks")
        for event in config["events"]:
            if event.get("ridge_csv"):
                self.add_file(self.local(event["ridge_csv"]), "ridge_csv")
        if config.get("type_database"):
            self.add_file(self.local(config["type_database"]), "type_database")
        ground = config["terrain"]
        if ground.get("geoid_raster"):
            self.add_file(self.local(ground["geoid_raster"]), "geoid")
        # The research pipeline ignores explicit rasters when a Copernicus
        # provider is selected. Do not present those inactive paths as inputs.
        if not ground.get("copernicus_cache"):
            for path in ground.get("rasters", []):
                self.add_file(self.local(path), "terrain")

    def collect_terrain_inputs(self, ground, terrain):
        """Record only a provider's explicitly exposed used Copernicus tiles.

        Current CopernicusTerrain does not expose used_tile_paths. That absence
        is recorded rather than substituting every file in its shared cache.
        A future provider may expose an iterable of actual used tile paths.
        """
        if not ground.get("copernicus_cache"):
            return
        catalogue = self.local(ground["copernicus_cache"]) / "tileList.txt"
        if catalogue.is_file():
            self.add_file(catalogue, "terrain_catalogue", "after_terrain_sampling")
        else:
            self._limitations.append("The Copernicus tile catalogue was not available for hashing.")
        used_paths = getattr(terrain, "used_tile_paths", None)
        if used_paths is None:
            self._limitations.append(
                "The terrain provider does not expose the Copernicus tiles "
                "actually used. Their hashes are absent; cache contents were "
                "not treated as a record of used tiles."
            )
            return
        if isinstance(used_paths, (str, bytes, Path)):
            raise TypeError("used_tile_paths must be an iterable of tile paths")
        for path in used_paths:
            self.add_file(path, "terrain_tile", "after_terrain_sampling")

    @property
    def sources(self):
        # Return independent records so a report consumer cannot mutate the ledger.
        return [dict(entry, roles=list(entry["roles"]))
                for _, entry in sorted(self._sources.items())]

    def declaration(self):
        return {"schema_version": 1, "configuration_sha256": self.config_sha256,
                "truth_separation": "not_assessed",
                "limitations": list(self._limitations)}
