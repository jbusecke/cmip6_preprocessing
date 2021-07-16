try:
    import intake
except ImportError:
    intake = None


def google_cmip_col(catalog="main"):
    """A tiny utility function to point to the 'official' pangeo cmip6 cloud files."""
    if intake is None:
        raise ImportError(
            "This functionality requires intake-esm. Install with `conda install -c conda-forge intake-esm"
        )
    if catalog == "main":
        return intake.open_esm_datastore(
            "https://storage.googleapis.com/cmip6/pangeo-cmip6.json"
        )
    # this doesnt work anymore, but ill leave it here as an example for the future
    #     elif catalog == "testing":
    #         return intake.open_esm_datastore(
    #             "https://storage.googleapis.com/cmip6/pangeo-cmip6-testing.json"
    #         )
    else:
        raise ValueError("Catalog not recognized. Should be `main` or `testing`")


def model_id_match(match_list, id_tuple):
    """Matches `id_tuple` to the list of tuples `exception_list`, which can contain
    wildcards (match any entry) and lists (match any entry that is in the list).

    Parameters
    ----------
    match_list : list
        list of tuples with id strings corresponding to e.g. `source_id`, `grid_label`...
    id_tuple : tuple
        single tuple with id strings.
    """
    # Check the size of tuples
    if any([len(t) != len(id_tuple) for t in match_list]):
        raise ValueError(
            "Each tuple in `match_list` must have the same number of elements as `match_id`"
        )

    match_list_checked = []
    for ml in match_list:
        ml_processed = []
        for i in range(len(ml)):
            match_element = ml[i]
            if isinstance(match_element, str) and match_element != "*":
                match_element = [match_element]
            if id_tuple[i] in match_element or match_element == "*":
                ml_processed.append(True)
            else:
                ml_processed.append(False)
        match_list_checked.append(all(ml_processed))
    return any(match_list_checked)


def _key_from_attrs(ds, attrs, sep="."):
    return sep.join([ds.attrs[i] if i in ds.attrs.keys() else "none" for i in attrs])


def cmip6_dataset_id(
    ds,
    sep=".",
    id_attrs=[
        "activity_id",
        "institution_id",
        "source_id",
        "experiment_id",
        "variant_label",
        "table_id",
        "grid_label",
        "version",
        "variable_id",
    ],
):
    """Creates a unique string id for e.g. saving files to disk from CMIP6 output

    Parameters
    ----------
    ds : xr.Dataset
        Input dataset
    sep : str, optional
        String/Symbol to seperate fields in resulting string, by default "."

    Returns
    -------
    str
        Concatenated
    """
    return _key_from_attrs(ds, id_attrs, sep=sep)
