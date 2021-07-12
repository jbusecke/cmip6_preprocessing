import itertools

import numpy as np
import pytest
import xarray as xr

from cmip6_preprocessing.preprocessing import (
    broadcast_lonlat,
    cmip6_renaming_dict,
    combined_preprocessing,
    correct_coordinates,
    correct_lon,
    correct_units,
    fix_metadata,
    maybe_convert_bounds_to_vertex,
    maybe_convert_vertex_to_bounds,
    parse_lon_lat_bounds,
    promote_empty_dims,
    rename_cmip6,
    replace_x_y_nominal_lat_lon,
    sort_vertex_order,
)


def create_test_ds(xname, yname, zname, xlen, ylen, zlen):
    x = np.linspace(0, 359, xlen)
    y = np.linspace(-90, 89, ylen)
    z = np.linspace(0, 5000, zlen)

    data = np.random.rand(len(x), len(y), len(z))
    ds = xr.DataArray(data, coords=[(xname, x), (yname, y), (zname, z)]).to_dataset(
        name="test"
    )
    ds.attrs["source_id"] = "test_id"
    # if x and y are not lon and lat, add lon and lat to make sure there are no conflicts
    lon = ds[xname] * xr.ones_like(ds[yname])
    lat = xr.ones_like(ds[xname]) * ds[yname]
    if xname != "lon" and yname != "lat":
        ds = ds.assign_coords(lon=lon, lat=lat)
    else:
        ds = ds.assign_coords(longitude=lon, latitude=lat)
    return ds


@pytest.mark.parametrize("xname", ["i", "x", "lon"])
@pytest.mark.parametrize("yname", ["j", "y", "lat"])
@pytest.mark.parametrize("zname", ["lev", "olev", "olevel"])
@pytest.mark.parametrize("missing_dim", [None, "x", "y", "z"])
def test_rename_cmip6(xname, yname, zname, missing_dim):
    xlen, ylen, zlen = (10, 5, 6)
    ds = create_test_ds(xname, yname, zname, xlen, ylen, zlen)

    if missing_dim == "x":
        ds = ds.drop_dims(xname)
    elif missing_dim == "y":
        ds = ds.drop_dims(yname)
    elif missing_dim == "z":
        ds = ds.drop_dims(zname)

    ds_renamed = rename_cmip6(ds, cmip6_renaming_dict())
    assert set(ds_renamed.dims).issubset(set(["x", "y", "lev"]))
    if missing_dim not in ["x", "y"]:
        assert (set(ds_renamed.coords) - set(ds_renamed.dims)) == set(["lon", "lat"])
    if not missing_dim == "x":
        assert xlen == len(ds_renamed.x)
    if not missing_dim == "y":
        assert ylen == len(ds_renamed.y)
    if not missing_dim == "z":
        assert zlen == len(ds_renamed.lev)

    # test exceptions and error handling
    with pytest.warns(UserWarning):
        ds_renamed = rename_cmip6(ds, {})

    with pytest.raises(ValueError):
        ds_renamed = rename_cmip6(ds, {"x": "x"})


def test_broadcast_lonlat():
    x = np.arange(-180, 179, 5)
    y = np.arange(-90, 90, 6)
    data = np.random.rand(len(x), len(y))
    ds = xr.DataArray(data, dims=["x", "y"], coords={"x": x, "y": y}).to_dataset(
        name="test"
    )
    expected = ds.copy()
    expected.coords["lon"] = ds.x * xr.ones_like(ds.y)
    expected.coords["lat"] = xr.ones_like(ds.x) * ds.y

    ds_test = broadcast_lonlat(ds)
    xr.testing.assert_identical(expected, ds_test)


def test_promote_empty_dims():
    xlen, ylen, zlen = (10, 5, 6)
    ds = create_test_ds("x", "y", "z", xlen, ylen, zlen)
    ds = ds.drop_vars(["x", "y", "z"])
    ds_promoted = promote_empty_dims(ds)
    assert set(["x", "y", "z"]).issubset(set(ds_promoted.coords))


@pytest.mark.parametrize("nans", [True, False])
@pytest.mark.parametrize("dask", [True, False])
def test_replace_x_y_nominal_lat_lon(dask, nans):
    x = np.linspace(0, 720, 10)
    y = np.linspace(-200, 140, 5)
    lon = xr.DataArray(np.linspace(0, 360, len(x)), coords=[("x", x)])
    lat = xr.DataArray(np.linspace(-90, 90, len(y)), coords=[("y", y)])
    llon = lon * xr.ones_like(lat)
    llat = xr.ones_like(lon) * lat

    data = np.random.rand(len(x), len(y))
    ds = xr.DataArray(data, coords=[("x", x), ("y", y)]).to_dataset(name="data")
    ds.coords["lon"] = llon
    ds.coords["lat"] = llat

    if nans:
        lon = ds["lon"].load().data
        lon[0, :] = np.nan
        lon[-1, :] = np.nan
        lon[:, 0] = np.nan
        lon[:, -1] = np.nan
        lon[15:23, 23:26] = np.nan
        ds["lon"].data = lon

        # for lats put only some nans in the middle.
        # I currently have no way to interpolate lats at the edge.
        lat = ds["lat"].load().data
        lat[15:23, 23:26] = np.nan
        ds["lat"].data = lat

    if dask:
        ds = ds.chunk({"x": -1, "y": -1})
        ds.coords["lon"] = ds.coords["lon"].chunk({"x": -1, "y": -1})
        ds.coords["lat"] = ds.coords["lat"].chunk({"x": -1, "y": -1})

    replaced_ds = replace_x_y_nominal_lat_lon(ds)

    assert all(~np.isnan(replaced_ds.x))
    assert all(~np.isnan(replaced_ds.y))

    assert all(replaced_ds.x.diff("x") > 0)
    assert all(replaced_ds.y.diff("y") > 0)
    assert len(replaced_ds.lon.shape) == 2
    assert len(replaced_ds.lat.shape) == 2
    assert set(replaced_ds.lon.dims) == set(["x", "y"])
    assert set(replaced_ds.lat.dims) == set(["x", "y"])
    assert all(~np.isnan(replaced_ds.x))
    assert all(~np.isnan(replaced_ds.y))

    # test a dataset that would result in duplicates with current method
    x = np.linspace(0, 720, 4)
    y = np.linspace(-200, 140, 3)
    llon = xr.DataArray(
        np.array([[0, 50, 100, 150], [0, 50, 100, 150], [0, 50, 100, 150]]),
        coords=[("y", y), ("x", x)],
    )
    llat = xr.DataArray(
        np.array([[0, 0, 10, 0], [10, 0, 0, 0], [20, 20, 20, 20]]),
        coords=[("y", y), ("x", x)],
    )
    data = np.random.rand(len(x), len(y))
    ds = xr.DataArray(data, coords=[("x", x), ("y", y)]).to_dataset(name="data")
    ds.coords["lon"] = llon
    ds.coords["lat"] = llat

    if dask:
        ds = ds.chunk({"x": -1, "y": -1})
        ds.coords["lon"] = ds.coords["lon"].chunk({"x": -1, "y": -1})
        ds.coords["lat"] = ds.coords["lat"].chunk({"x": -1, "y": -1})

    replaced_ds = replace_x_y_nominal_lat_lon(ds)
    assert all(~np.isnan(replaced_ds.x))
    assert all(~np.isnan(replaced_ds.y))
    assert len(replaced_ds.y) == len(np.unique(replaced_ds.y))
    assert len(replaced_ds.x) == len(np.unique(replaced_ds.x))
    # make sure values are sorted in ascending order
    assert all(replaced_ds.x.diff("x") > 0)
    assert all(replaced_ds.y.diff("y") > 0)
    assert len(replaced_ds.lon.shape) == 2
    assert len(replaced_ds.lat.shape) == 2
    assert set(replaced_ds.lon.dims) == set(["x", "y"])
    assert set(replaced_ds.lat.dims) == set(["x", "y"])


@pytest.mark.parametrize(
    "coord",
    [
        "x",
        "y",
        "lon",
        "lat",
        "lev",
        "lev_bounds",
        "lon_bounds",
        "lat_bounds",
        "time_bounds",
        "lat_verticies",
        "lon_verticies",
    ],
)
def test_correct_coordinates(coord):
    xlen, ylen, zlen = (10, 5, 6)
    ds = create_test_ds("xx", "yy", "zz", xlen, ylen, zlen)
    # set a new variable
    ds = ds.assign({coord: ds.test})

    ds_corrected = correct_coordinates(ds)
    assert coord in list(ds_corrected.coords)


def test_parse_lon_lat_bounds():
    lon = np.arange(0, 10)
    lat = np.arange(20, 30)
    data = np.random.rand(len(lon), len(lat))
    ds = xr.DataArray(data, dims=["x", "y"], coords={"x": lon, "y": lat}).to_dataset(
        name="test"
    )
    ds.coords["lon"] = ds.x * xr.ones_like(ds.y)
    ds.coords["lat"] = xr.ones_like(ds.x) * ds.y

    ds.coords["lon_bounds"] = (
        xr.DataArray([-0.1, -0.1, 0.1, 0.1], dims=["vertex"]) + ds["lon"]
    )
    ds.coords["lat_bounds"] = (
        xr.DataArray([-0.1, 0.1, 0.1, -0.1], dims=["vertex"]) + ds["lat"]
    )

    ds_test = parse_lon_lat_bounds(ds)
    assert "lon_verticies" in ds_test.coords
    assert "lat_verticies" in ds_test.coords

    # introduce a time diemension
    for wrong_coord in ["lon_bounds", "lat_bounds"]:
        # TODO: this should also test lev_bounds.
        # Are there other coords that should be purged of the
        ds_wrong = ds.copy()
        ds_wrong.coords[wrong_coord] = ds_wrong.coords[wrong_coord] * xr.DataArray(
            range(5), dims=["time"]
        )

        ds_test2 = parse_lon_lat_bounds(ds_wrong)
        assert "time" in ds_wrong.dims
        assert "time" not in ds_test2.variables


@pytest.mark.parametrize("missing_values", [False, 1e36, -1e36, 1001, -1001])
@pytest.mark.parametrize(
    "shift",
    [
        -70,
        -180,
        -360,
    ],
)  # cant handle positive shifts yet
def test_correct_lon(missing_values, shift):
    xlen, ylen, zlen = (40, 20, 6)
    ds = create_test_ds("x", "y", "lev", xlen, ylen, zlen)
    ds = ds.assign_coords(x=ds.x.data + shift)
    lon = ds["lon"].reset_coords(drop=True)
    ds = ds.assign_coords(lon=lon + shift)
    if missing_values:
        # CESM-FV has some super high missing values. Test removal
        lon = ds["lon"].load().data
        lon[10:20, 10:20] = missing_values
        ds["lon"].data = lon

    ds_lon_corrected = correct_lon(ds)
    assert ds_lon_corrected.lon.min() >= 0
    assert ds_lon_corrected.lon.max() <= 360


def test_correct_units():
    lev = np.arange(0, 200)
    data = np.random.rand(*lev.shape)
    ds = xr.DataArray(data, dims=["lev"], coords={"lev": lev}).to_dataset(name="test")
    ds.attrs["source_id"] = "something"
    ds.lev.attrs["units"] = "centimeters"

    ds_test = correct_units(ds)
    assert ds_test.lev.attrs["units"] == "m"
    np.testing.assert_allclose(ds_test.lev.data, ds.lev.data / 100.0)


def test_maybe_convert_bounds_to_vertex():
    # create a ds with bounds
    lon = np.arange(0, 10)
    lat = np.arange(20, 30)
    data = np.random.rand(len(lon), len(lat))
    ds = xr.DataArray(
        data, dims=["lon", "lat"], coords={"lon": lon, "lat": lat}
    ).to_dataset(name="test")
    for va in ["lon", "lat"]:
        ds.coords[va + "_bounds"] = ds[va] + xr.DataArray([-0.01, 0.01], dims=["bnds"])

    # create expected dataset
    lon_b = xr.ones_like(ds.lat) * ds.coords["lon_bounds"]
    lat_b = xr.ones_like(ds.lon) * ds.coords["lat_bounds"]

    lon_v = xr.concat(
        [lon_b.isel(bnds=ii).squeeze(drop=True) for ii in [0, 0, 1, 1]], dim="vertex"
    )
    lon_v = lon_v.reset_coords(drop=True)

    lat_v = xr.concat(
        [lat_b.isel(bnds=ii).squeeze(drop=True) for ii in [0, 1, 1, 0]], dim="vertex"
    )
    lat_v = lat_v.reset_coords(drop=True)

    ds_expected = ds.copy()
    ds_expected = ds_expected.assign_coords(lon_verticies=lon_v, lat_verticies=lat_v)

    xr.testing.assert_identical(ds_expected, maybe_convert_bounds_to_vertex(ds))
    # check that datasets that already conform to this are not changed
    xr.testing.assert_identical(
        ds_expected, maybe_convert_bounds_to_vertex(ds_expected)
    )


def test_maybe_convert_vertex_to_bounds():
    # create a ds with verticies
    lon = np.arange(0, 10)
    lat = np.arange(20, 30)
    data = np.random.rand(len(lon), len(lat))
    ds = xr.DataArray(data, dims=["x", "y"], coords={"x": lon, "y": lat}).to_dataset(
        name="test"
    )
    ds.coords["lon"] = ds.x * xr.ones_like(ds.y)
    ds.coords["lat"] = xr.ones_like(ds.x) * ds.y

    ds.coords["lon_verticies"] = (
        xr.DataArray([-0.1, -0.1, 0.1, 0.1], dims=["vertex"]) + ds["lon"]
    )
    ds.coords["lat_verticies"] = (
        xr.DataArray([-0.1, 0.1, 0.1, -0.1], dims=["vertex"]) + ds["lat"]
    )
    ds = promote_empty_dims(ds)

    # create expected dataset
    ds_expected = ds.copy()
    for va in ["lon", "lat"]:
        ds_expected.coords[va + "_bounds"] = (
            xr.DataArray([-0.1, 0.1], dims=["bnds"]) + ds_expected[va]
        )
    ds_expected = promote_empty_dims(ds_expected)

    ds_test = maybe_convert_vertex_to_bounds(ds)

    xr.testing.assert_identical(ds_expected, ds_test)
    # check that datasets that already conform to this are not changed
    xr.testing.assert_identical(
        ds_expected, maybe_convert_vertex_to_bounds(ds_expected)
    )

    assert np.all(ds_test.lon_bounds.diff("bnds") > 0)
    assert np.all(ds_test.lat_bounds.diff("bnds") > 0)


def test_sort_vertex_order():
    ordered_points = np.array([[1, 1, 2, 2], [3, 4, 4, 3]]).T

    # check every permutation of the points
    for order in list(itertools.permutations([0, 1, 2, 3])):
        points_scrambled = ordered_points[order, :]

        # create xarray
        lon_v = xr.DataArray(
            points_scrambled[:, 0],
            dims=["vertex"],
            coords={"x": 0, "y": 0},
            name="lon_bounds",
        ).expand_dims(["x", "y"])
        lat_v = xr.DataArray(
            points_scrambled[:, 1],
            dims=["vertex"],
            coords={"x": 0, "y": 0},
            name="lat_bounds",
        ).expand_dims(["x", "y"])
        da = (
            xr.DataArray([np.nan], coords={"x": 0, "y": 0})
            .expand_dims(["x", "y"])
            .to_dataset(name="test")
        )
        da = da.assign_coords({"lon_verticies": lon_v, "lat_verticies": lat_v})

        da_sorted = sort_vertex_order(da).squeeze()
        new = np.vstack((da_sorted.lon_verticies, da_sorted.lat_verticies)).T

        np.testing.assert_allclose(new, ordered_points)

        assert da_sorted.lon_verticies.isel(vertex=0) < da_sorted.lon_verticies.isel(
            vertex=3
        )
        assert da_sorted.lon_verticies.isel(vertex=1) < da_sorted.lon_verticies.isel(
            vertex=2
        )

        assert da_sorted.lat_verticies.isel(vertex=0) < da_sorted.lat_verticies.isel(
            vertex=1
        )
        assert da_sorted.lat_verticies.isel(vertex=3) < da_sorted.lat_verticies.isel(
            vertex=2
        )

        # shift the vertex by one and see if the result is the same
        da_shift = da.copy()
        da_shift = da_shift.assign_coords(vertex=da_shift.vertex + 10)
        da_sorted_shift = sort_vertex_order(da_shift).squeeze()
        np.testing.assert_allclose(da_sorted_shift.vertex.data, np.arange(4))


def test_fix_metadata():
    # Create a dataset with matching attrs
    ds = xr.Dataset()
    ds.attrs = {
        "source_id": "GFDL-CM4",
        "experiment_id": "historical",
        "branch_time_in_parent": "nonsense",
    }
    ds_fixed = fix_metadata(ds)
    assert ds.attrs["branch_time_in_parent"] == 91250

    # Test that another dataset is untouched
    ds = xr.Dataset()
    ds.attrs = {
        "source_id": "GFDL-CM4",
        "experiment_id": "other",
        "branch_time_in_parent": "nonsense",
    }
    ds_fixed = fix_metadata(ds)
    assert ds.attrs["branch_time_in_parent"] == "nonsense"


### Combination test - involving###


def test_combined_preprocessing_mislabeled_coords():
    """Test if the renaming is applied to datavariables and then if they are moved to the coords."""
    # create a 2d dataset
    xlen, ylen, zlen = (10, 5, 1)
    ds = (
        create_test_ds("x", "y", "dummy", xlen, ylen, zlen).squeeze().drop_vars("dummy")
    )
    ds = ds.assign(depth=5.0)

    ds_pp = combined_preprocessing(ds)
    assert "lev" in ds_pp.coords
    np.testing.assert_allclose(ds.depth.data, ds_pp.lev.data)
