from pathlib import Path
import json,hashlib,sys
import aircraft_geoloc
from aircraft_geoloc.provenance import implementation_provenance
root=Path(sys.argv[1])
package=Path(aircraft_geoloc.__file__).resolve().parent
assert 'site-packages' in package.parts
expected=json.loads((root/'expected-package.json').read_text())
actual={p.relative_to(package.parent).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in package.rglob('*') if p.is_file() and p.suffix in {'.py','.html','.js','.css'}}
assert actual==expected,(actual.keys()-expected.keys(),expected.keys()-actual.keys())
manifest=implementation_provenance(package.parent)
expected_digest=hashlib.sha256()
for name in sorted(k for k in expected if k.endswith('.py')):
    expected_digest.update(name.encode())
    expected_digest.update((package.parent/name).read_bytes())
assert manifest['sha256']==expected_digest.hexdigest()
probe=package.parent/'unrelated_integration_probe.py'
assert not probe.exists()
try:
    probe.write_text('unrelated = True\n')
    assert implementation_provenance(package.parent)==manifest
finally:
    probe.unlink()
receipt={'source_commit':'f0db844ae2496fa1faf7bf438daf152c55514b00','passed':True,'installed_package':str(package),'source_and_asset_files_verified':len(actual),'web_assets_verified':sorted(k for k in actual if k.endswith(('.html','.js','.css'))),'package_only_digest':manifest['sha256'],'unrelated_installed_file_excluded':True,'checkout_source_and_assets_match':True}
(root/'wheel-verification.json').write_text(json.dumps(receipt,indent=2)+'\n')
print(json.dumps(receipt))
