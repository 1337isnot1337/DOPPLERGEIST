{
  description = "DOPPLERGEIST - A tool to geolocate audio recordings using aircraft Doppler shifts and historical flight tracks.";

  inputs = {
    nixpkgs.url = "https://channels.nixos.org/nixpkgs-unstable/nixexprs.tar.zst";
  };

  outputs = inputs: {
    packages = builtins.mapAttrs (system: pkgs: {
      dopplergeist = pkgs.callPackage ./package.nix { };

      default = inputs.self.packages.${system}.dopplergeist;
    }) inputs.nixpkgs.legacyPackages;

    apps = builtins.mapAttrs (system: _: {
      default = {
        type = "app";
        program = "${inputs.self.packages.${system}.default}/bin/dopplergeist";
      };
    }) inputs.nixpkgs.legacyPackages;

    formatter = builtins.mapAttrs (_: pkgs: pkgs.nixfmt) inputs.nixpkgs.legacyPackages;
  };
}
