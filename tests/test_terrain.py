import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from aircraft_geoloc.terrain import Terrain


def test_raster_height_and_geoid_are_combined_and_missing_coverage_is_rejected(tmp_path):
    paths=[]
    for name,data in [("ground",np.array([[10,20],[30,40]],dtype="float32")),
                      ("geoid",np.full((2,2),-30,dtype="float32"))]:
        path=tmp_path/(name+".tif")
        with rasterio.open(path,"w",driver="GTiff",width=2,height=2,count=1,dtype="float32",
                           crs="EPSG:4326",transform=from_origin(-101,41,1,1)) as raster:
            raster.write(data,1)
        paths.append(path)
    terrain=Terrain([paths[0]],geoid_path=paths[1])
    assert np.allclose(terrain.sample([40.5,39.5],[-100.5,-99.5]),[-20,10])
    with pytest.raises(ValueError,match="coverage missing"):
        terrain.sample([45],[-110])
