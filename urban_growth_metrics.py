#!pip install OWSLib
from owslib.wfs import WebFeatureService
import pandas as pd
import geopandas as gpd
from requests import Request
from requests.utils import quote, unquote
import logging
import matplotlib.pyplot as plt
import urllib.parse
import re
import copy
from functools import reduce
import itertools
# Patches are needed for legend handles (Proxy Artist)
import matplotlib.patches as mpatches
# Needed for colormaps
import matplotlib
# Mapclassify is used for value reclassification
import mapclassify
import contextily as cx
logger = logging.getLogger(__name__)


def get_municipality_codes(cities, wfs_base_url='https://geo.stat.fi/geoserver/wfs?', 
                           filter_op="IN", typeName="tilastointialueet:kunta4500k_2022"):
    """
    Return name,code mapping and geometry for municipality names in Finland.
    
    Parameters:
        cities::list(str)                  : A list of city names like ["Helsinki", "Tampere"] or 
                                             just ["Helsinki"], if you want a single value.
        wfs_base_url::str                  : A url for the WFS server which delivers typename
                                             suitable for searching for the municipality codes and
                                             geometries. 'tilastointialueet:kunta5400k_2022' from
                                             Statistics Finland did the trick in 2022.
        filter_op::str                     : A CQL2 operator used in query. "IN" by default
                                             but "=" will be used for single value queries.
        typeName::str                      : A typename of the layer used for querying codes.
                                             
    """
    # Assume the name of the city is in the form "Helsinki, Finland" and only use the 
    # first element before the commma.
    logger.info("Start getting municipality codes for: {}".format(cities))
    assert len(cities) > 0, "Input needs to contain at least one city"
    citynames = [x.split(",")[0].strip() for x in cities]
    cityname_filter = None
    if len(citynames) > 1:
        cityname_filter = str(tuple(citynames))
    else:
        cityname_filter = "('{}')".format(citynames[0])
        filter_op="="
    #print(cityname_filter)
    url = wfs_base_url
    params = dict(request='GetFeature', 
                  typeName=typeName,
                  srsName="EPSG:3067",
                  outputFormat="application/json",
                  version="2.0.0",
                  cql_filter="nimi+{fop}+{cities}".format(fop=filter_op, cities=quote(cityname_filter, safe='')))
    wfs_request_url = unquote(Request('GET', url, params=params).prepare().url)
    logger.info("Requesting layer: {}".format(wfs_request_url))
    municipalities = gpd.read_file(wfs_request_url)
    municipalities.crs="EPSG:3067"
    muns = municipalities[['kunta', 'nimi', 'geometry']].to_dict('list')
    name_pairs = None
    if len(municipalities) > 1:
        name_pairs = tuple(zip(muns['nimi'],muns['kunta']))
    else:
        name_pairs = (muns['nimi'][0],muns['kunta'][0])
    logger.info("Fineshed getting municipality codes for: {}".format(cities))
    return municipalities, name_pairs    
    

def get_wfs_time_series(layer_prefix, years, cities, filter_col, wfs_base_url="https://paituli.csc.fi/geoserver/paituli/wfs?"):
    """
    Get a time series, a series of layers from consecutive years, from a WFS service. 
    for Finnish cities. For example calling function with
    cities = ["Helsinki, Finland"], years=[2020], filter_col="kunta", 
    wfs_base_url="https://paituli.csc.fi/geoserver/paituli/wfs?"
    layer_prefix="paituli:tike_vaki1km_"
    
    will return those features of paituli:tike_vaki1km_2020 which are in Helsinki
    assuming that typename has a suitable column used for filtering.
    
    Parameters:
        layer_prefix::str                 : A prefix of time series layer. E.g. "paituli:tike_vaki1km_" is
                                            a prefix of "paituli:tike_vaki1km_2016"
        years::list(int)                  : A list of years, whose layer is returned
        cities::list(str)                 : A list of Finnish cities
        filter_col::str                   : A column used in Filtering cities
        wfs_base_url::str                 : A URL of the WFS service endpoint
    
    Return:
        requested_layers::dict            : A dictionary which maps each requested layer to its corresponding 
                                            GeoDataFrame
    """
    # Get the prefix mapping and schemas in order to query correct typeNames and propertyNames
    # Sometimes names of the properties change scale
    logger.info("Start downloading wfs time series: {c}, {f}, {l}, {y}".format(c=cities, f=filter_col, l=layer_prefix, y=years))
    logger.info("Start downloading wfs time series details: {c}, {f}, {l}, {y}".format(c=cities, f=filter_col, l=layer_prefix, y=years))
    prefix_mapping, requested_schemas = get_wfs_time_series_details_by_prefix([layer_prefix], 
                                                                              years, "https://paituli.csc.fi/geoserver/paituli/wfs?", 
                                                                              [filter_col])
    url = wfs_base_url
    # Map city names "Helsinki, Finland" to Finnish municipalitycodes and their geometries
    muns, name_pairs = get_municipality_codes(cities)
    codes = None
    # Use "CQL IN" filter by default
    filter_op = "IN"
    # Get municipality codes from the name_map
    if len(cities) > 1:
        codes = [code for (_,code) in name_pairs]
    else:
        # If only one pair is present, use that
        _, code = name_pairs
        codes = [code]
        # with single codes, use "=" as the CQL filter
        filter_op = "="
    # Initialize WFS parameters except typeName and cql_filter, which will be initialized later
    params = dict(service='WFS', version="2.0.0", request='GetFeature', outputFormat='json', srsName='EPSG:3067')
    
    for key, value in requested_schemas.items():
        req = build_wfs_request(wfs_base_url, key, value[filter_col], codes, params, filter_op)
        logger.info("Requesting WFS layer: {}".format(req))
        gdf = gpd.read_file(req)
        # Assign crs as EPSG:3067. Supplying this as a parameter just didn't work. :-(
        gdf.crs = "EPSG:3067"
        # Add GeoDataFrame to requested layers.
        requested_schemas[key] = gdf
    requested_layers = requested_schemas
    logger.info("Finished downloading wfs time series: {c}".format(c=cities))
    return requested_layers


def build_wfs_request(wfs_base_url, typename, filter_col, filter_values, params, filter_op="IN"):
    """
    A function to build WFS queries with single propertyName CQL filters
    of string values. A rework would be needed to support more
    nuanced CQL filters. Will return something funky if no filter values are
    given.
    
    Parameters:
    -----------
        wfs_base_url::str                      : A URL to the WFS service endpoint
        typename::str                          : A valid WFS typename on the WFS server
        filter_col::str                        : A WFS propertyName used in filtering
        filter_values::list(str)               : A list of string values used in filtering
        params::dict                           : A dictionary of WFS parameters supplied to
                                                 the service endpoint in request
        filter_op::str                         : The operation used in filtering string values.
                                                 Is "IN" by default.
    Return:
        wfs_request_url::str                   : A WFS request URL that can be supplied to, 
                                                 for example, geopandas.read_file() to get
                                                 data according to the filter.
    """
    logger.info("Start building WFS request URL: {t}, {u}, {fv}".format(t=typename, u=wfs_base_url, fv=filter_values))

    if filter_op == "IN":
        filter_values = str(tuple(filter_values))
    if filter_op == "=" and len(filter_values) == 1:
        filter_values = "'{}'".format(filter_values[0])
    params['cql_filter'] = "{col}+{fop}+{values}".format(col=filter_col, fop=filter_op, values=quote(filter_values, safe=''))
    params['typeName'] = typename
    wfs_request_url = unquote(Request('GET', wfs_base_url, params=params).prepare().url)
    logger.info("Fineshed building WFS reques URL for: {t}, {u}".format(t=typename, u=wfs_request_url))
    return wfs_request_url

    
def get_wfs_time_series_details_by_prefix(layer_prefixes, years=[], 
                                          wfs_base_url="https://paituli.csc.fi/geoserver/paituli/wfs?", 
                                          wfs_propertyNames=[], wfs_version='2.0.0'):
    """
    Get the details, i.e. typenames and schemas by year from a WFS time series. Useful for most WFS
    services which offer data for many years in format {prefix}_{year}, e.g. only the year suffix
    changes:
    - paituli:tike_vaki1km_2016
    - paituli:tike_vaki1km_2017
    - paituli:tike_vaki1km_2018
    
    PropertyName search from the schema is case-insensitive, so if you need to get schema for
    "kunta", it will instead return first suitable propertyname in the schema.
    "kunta" ~ "KUNTA", "Kunta"
    Parameters:
    -----------
        layer_prefixes::list(str)              : A list of prefix/es for typename/s. A prefix is the part of
                                                 the typename that preceeds the year. E.g.
                                                 ["paituli:tike_vaki1km_"] or 
                                                 ["paituli:tike_vaki1km_","paituli:tike_kuntienVaesto_"]
        years::list(int)                       : A list of years that the layers are searched. E.g.
                                                 [2015] or [2015,2016,2017]. Empty list means that all
                                                 typenames matching the prefix will be returned.
        wfs_base_url::str                      : A URL to the WFS service endpoint
        wfs_propertynames::list(str)           : A list of WFS property names that will be returned in schema.
                                                 E.g. if you are interested in the schema and names of "kunta" and
                                                 "name", wfs_propertynames=["kunta", "name"]
        wfs_version::str                       : The version of the WFS service endpoint. Any other version
                                                 than "1.0.0", "1.1.0" or "2.0.0" will likely lead to errors.
    Return:
        prefix_mapping::dict                   : A dictionary which has a key entry for each prefix in the list, 
                                                 values are the layers which start with the prefix, and each
                                                 layer has also the matching propertyName mapping from values
                                                 of wfs_propertynames to actual names of the properties. 
        requested_schemas::dict                : A dictionary which contains full schema of property names queried
                                                 
    """
    wfs11 = WebFeatureService(url=wfs_base_url, version=wfs_version)
    logger.info("Start requesting WFS typeName and propertyName details: {lp}, {y}, {wpn}".format(lp=layer_prefixes, 
                                                                                                 y=years, wpn=wfs_propertyNames))
    def filter_typeNames(typeName):
        """
        Filters typeNames which match values of prefixes 
        """
        if any([typeName.startswith(prefix) for prefix in layer_prefixes]):
            if years is None or len(years) == 0:
                return True
            else:
                return int(typeName.split('_')[-1]) in years
        else:
            return False

    requested_schemas = {}
    prefix_mapping = {}
    requested_layers = list(filter(filter_typeNames, list(wfs11.contents)))
    
    # Loop through requested layers, requested WFS propertyNames in the schema
    # and add to requested_schema
    for l in requested_layers:
        #print({l: wfs11.get_schema(l)['properties']})
        for col in wfs_propertyNames:
            for prop_name, prop_value in wfs11.get_schema(l)['properties'].items():
                # Ignore case: "kunta" will match "Kunta" or "KUNTA"
                match = re.match(col, prop_name, re.IGNORECASE)
                # Add column to schema map, if it matches a propertyName
                if match:
                    if l in requested_schemas:
                        updated = requested_schemas[l]
                        if col not in updated:
                            updated[col] = match.group(0)
                    else:
                        requested_schemas[l] = {}
                        requested_schemas[l][col] = match.group(0)
    
    # Construct prefix mapping which maps prefixes to layers and their schemas
    prefix_mapping = {prefix: [] for prefix in layer_prefixes}
    for prefix in layer_prefixes:
        for l in requested_layers:
            if l.startswith(prefix):
                prefix_mapping[prefix].append({l: requested_schemas[l]})
    logger.info("Finished requesting WFS typeName and propertyName details: {lp}, {y}, {wpn}".format(lp=layer_prefixes, 
                                                                                                 y=years, wpn=wfs_propertyNames))
    return prefix_mapping, requested_schemas


def time_series_from_geodataframes(gdfs_by_year, key=None, columns=[], axis=1):
    """
    Will create a time series from geopandas.GeoDataFrames (or even pandas.DataFrames, if axis=0).
    If axis = 0, the dataframes from each year will be concatenated as rows. Will work the best
    if each of the input dataframes only contain one row. If axis=1, the columns from each
    dataframe will be renamed according to its year and assembled as one dataframe which
    has the same number of columns and rows that the SMALLEST of the dataframes or the columns 
    which are in `columns`. I.e, the function
    will perform inner join on `key`
    
    Parameters:
    -----------
        gdfs_by_year::tuple(int,GeoDataFrame)   : A pair of year and GeoDataFrame
        key::str                                : A key column that is used in joining together GeoDataFrames
                                                  from each year. If None and axis=1, the function probably 
                                                  does not work. If axis=0, the key wont be used.
        columns::list(str)                      : Columns for the output dataframe. If the columns are not
                                                  valid values in any of the GeoDataFrames, they wont be used.
        axis::int                               : axis=0: concatenate rows of the dataframes,
                                                  axis=1: inner join dataframes on `key`
    Return:
        gdfs::geopandas.GeoDataFrame (or DataFrame)
              
    """
    logger.info("Start building timeseries from dataframes: {key}, {c}, {ax}".format(key=key, c=columns, ax=axis))
    def municipality_data_time_series(gdfs_by_year, columns=[]):
        years = []
        layers = []
        for year, lyr in gdfs_by_year:
            years.append(str(year))
            layers.append(lyr[columns])
        df_all = pd.concat(layers)
        df_all = df_all.set_axis(years)
        return df_all
    
    assert axis in (0,1), "Axis has to be 0 or 1"
    assert len(gdfs_by_year) > 1, "Input has to have at least 2 GeoDataFrames in a list"
    assert all([type(year) == int and type(gdf) == gpd.GeoDataFrame for year, gdf in gdfs_by_year]), "Data not given as list of (year, geopandas.GeoDataFrame) pairs"
    assert len(set([year for year, _ in gdfs_by_year])) == len(gdfs_by_year), "Some years have the same value."
    # Add column names from each dataframe into its own set.
    gdfs_cols = [set(list(gdf.columns.values)) for year, gdf in gdfs_by_year]
    # Intersection of the sets contains the common unique columns of the dataframes
    gdfs_col_intersection = set.intersection(*gdfs_cols)
    # If `columns` has been supplied and it has common columns with all the unique columns
    # only use those common columns
    if len(columns) > 0 and len(set(columns).intersection(gdfs_col_intersection)) > 0:
        if key in gdfs_col_intersection:
            gdfs_col_intersection = set(columns).intersection(gdfs_col_intersection)
    # Assure that the `key` column is in all of the dataframes
    assert key in gdfs_col_intersection or axis==0, "GeoDataFrames do not have a common key attribute"
    # The list of columns in output dataframes
    intersected_cols = list(gdfs_col_intersection)
    gdfs = None
    
    # Use attribute inner join, if axis=1
    if axis == 1:
        gdfs = reduce(lambda left, right: rename_and_merge_gdfs(left, right, intersected_cols, key), gdfs_by_year)
    # Use concatenation, if axis=0
    elif axis == 0:
        gdfs = municipality_data_time_series(gdfs_by_year, intersected_cols)
    logger.info("Finished building timeseries from dataframes: {key}, {c}, {ax}, {res}".format(key=key, c=columns, ax=axis, res=gdfs))
    return gdfs


def rename_and_merge_gdfs(left, right, intersected_cols, key):
    """
    Reduces columns to of the input dataframes to the `intersected_cols`. Then Renames 
    columns of GeoDataFrame by appending year to each column which isn't value of the `key`. 
    After merge the of the right pair will be renamed to "geometry_{year}" and "geometry"
    of the left pair will be set as the geometry column of the output GeoDataFrame.
    DataFrames should have a matching CRS but it's not checked.
    
    Parameters:
    -----------
        left::tuple(int,GeoDataFrame) | GeoDataFrame  : A year dataframe pair or just the dataframe
                                                        which contains the merged result of N
                                                        previous dataframes (from previous years)
        right::tuple(int,GeoDataFrame)                : A year dataframe pair for the following
                                                        dataframe.
        intersected_cols::list(str)                   : The set of column names that the output
                                                        dataframe will contain.
        key::str                                      : A key column that will not be renamed
    
    Return:
        res::gpd.GeoDataFrame                         : A dataframe which results from the merge.
                                                        
    """
    logger.info("Start renaming and mergin dataframes: {l}, {r}, {ic}, {k}".format(k=key, ic=intersected_cols, l=left, r=right))
    # First assign GeoDataFrames as None
    year_left, gdf_left = None, None
    # If `left` is a tuple and the values have types int and GeoDataFrame, 
    if type(left) == tuple and type(left[0]) == int and type(left[1]) == gpd.GeoDataFrame:
        # it's then safe to assign year_left and gdf_left from `left`.
        year_left, gdf_left = left
        # Set the columns
        gdf_left = gdf_left[intersected_cols]
        # Rename columns by appending year_left to suitable columns
        gdf_left = gdf_left.rename(mapper=lambda col: year_appender(year_left, key, col), axis=1)
    else:
        # If `left` only contains a dataframe, do not assign the year.
        gdf_left = left
    # Assign right year and GeoDataFrame
    year_right, gdf_right = right
    # Set the columns
    gdf_right = gdf_right[intersected_cols]
    # Rename columns
    gdf_right = gdf_right.rename(mapper=lambda col: year_appender(year_right, key, col), axis=1)
    # Perform merge as inner join on `key`
    res = gdf_left.merge(right=gdf_right, how='inner', on=key, suffixes=(None, "_{}".format(year_right)))
    # Set the geometry column.
    res = res.set_geometry("geometry")
    logger.info("Finished renaming and mergin dataframes: {l}, {r}, {ic}, {k}, {res}".format(k=key, ic=intersected_cols, l=left, r=right, res=res))
    return res


def year_appender(year, key, col):
    """
    Renames all columns but the geometry column and key column 
    from a DataFrame by appending year to the end separated with 
    an underscore.
    
    Parameters:
    -----------
        year::int (or other suitable) : Year that will be appended to the end of the column name
        key::str                      : Column assigned to `key` wont be renamed.
        col::str                      : Column that is renamed.
    
    Return:
        col::str                      : Renamed column or the column without change if its
                                        either "geometry" or the value of `key`
    """
    if col not in ('geometry', key):
        return "{c}_{y}".format(c=col, y=year)
    else:
        return col 
    

def timeseries_diff(df_timeseries_rows, columns=[], rename_map={}, percentage_change=False, drop_na=True):
    """
    Returns difference DataFrame for time series, where the difference is the 
    change between each consecutive row in the series. Time series dataframe has 
    one row for each year and one column for each attribute in the data and the 
    row is indexed. The index of the input dataframe is used to set labels for the 
    difference rows.
    
    Parameters:
    -----------
        df_timeseries_rows::pd:DataFrame      : DataFrame which contains a time series. I.e.
                                                one row for each year and N columns (one for
                                                each attribute).
        columns::list(str)                    : A list that contains columns that the change will be 
                                                calculated for. Only those columns will be returned
                                                in the resulting dataframe. If the list is empty or
                                                the values are not in the labels of the DataFrame,
                                                all columns of the frame will be used. This might
                                                create errors if the datatype of some column is not 
                                                numeric
        rename_map::dict                      : A dictionary which contains new {name : new_name} for
                                                each column that the user wants to rename. Names
                                                must be valid column values in the input DataFrame. If
                                                the column name does not exist in the rename_map, it
                                                will become "diff_<original column name>" (or
                                                "diff_p_<original column name>" if percentage_change=True)
        percentage_change::bool               : If True, the relative change will be calculated, otherwise
                                                the absolute change. Relative change will be in the decimal
                                                form. Multiply DataFrame (df.mul(100)) to make it %
        drop_na::bool                         : If True, the rows of NaN will be dropped and y_axis
                                                index will be set to ["0-1", "1-2", "2-3",...] if 
                                                for an index [0,1,2,3,...]. Each index value will
                                                be cast to string and consecutive values will be joined
                                                with a score "-". Leave False, if you want to leave the NaN
                                                rows and not set the y-axis labels.
    Return:
        A pd.DataFrame which contains difference in absolute or relative terms between
        each consecutive row.
                
    """
    assert len(df_timeseries_rows) > 1, "Dataframe must have at least two rows"
    df_cols = list(df_timeseries_rows.columns.values)
    # Get the unique common columns between supplied columns and actual columns
    col_intersection = set(columns).intersection(df_cols)
    # If user inputs columns that are not in the actual columns of the DataFrame,
    # use the columns of the DataFrame instead.
    if len(col_intersection) < len(set(columns)):
        columns = df_cols
    else:
        # Columns are safe to be used as is
        columns = list(col_intersection)
    
    # deeply copy the dataframe, so the original does not change
    df = df_timeseries_rows[columns].copy(deep=True)
    diff_cols = []
    # Maps percentage_change selection to difference column format and 
    # difference function (pd.Series.diff() or pd.Series.pct_change())
    diff_col_prefix = {False: {"diff_col": "diff_{}", "fun": lambda x: x.diff()}, 
                       True: {"diff_col": "diff_p_{}", "fun" : lambda x: x.pct_change()}}
    # Loop through all columns and
    # calculate difference columns according to the 
    # selected difference calculation method (absolute=diff,relative=pct_change)
    for col in columns:
        diff_col = diff_col_prefix[percentage_change]["diff_col"].format(col)
        diff_fun = diff_col_prefix[percentage_change]["fun"]
        df[diff_col] = df[col].pipe(diff_fun)
        # Adds to the list of columns
        diff_cols.append(diff_col)

    #print(diff_cols)
    df = df[diff_cols]
    
    # Take a deepcopy to avoid changing the original
    rename_map = copy.deepcopy(rename_map)
    # Rename changed column names to those requested by user
    # or the original names, if user does not have preferences.
    for diff_col, col in zip(diff_cols, columns):
        if col in rename_map:
            deleted_value = rename_map.pop(col)
            rename_map[diff_col] = deleted_value
        else:
            rename_map[diff_col] = col
    #print(rename_map)
    # Rename columns based on rename_map
    df = df.rename(rename_map, axis=1)        
    
    # Build Y-axis labels from index values. Works best if values are years in string format
    y_axis = []
    i = 0
    y_index = list(df.index) 
    while i + 1 < len(y_index):  
        y_axis.append("{i_th}-{i_plus_th}".format(i_th=y_index[i], i_plus_th=y_index[i+1]))
        i+=1
    if drop_na:    
        df = df.dropna()
        df = df.set_axis(y_axis)
    # sort the columns in the DataFrame alphabetically to avoid returning 
    # in changing orders.
    sorted_cols = sorted(list(df.columns.values))
    return df[sorted_cols]


def timeseries_gdf_diff(timeseries_gdf, prefixes=[]):
    """
    Calculates difference columns for each column in the GeoDataFrame assuming the
    columns in the gdf are named by appending year to the end of the original
    column and grouping by column prefix in 'prefixes'. For example:
    If original data had column prefix 'men', and the data spanned years from
    2018 to 2020, the timeseries geodataframe
    would contain 'men_2018', 'men_2019' and 'men_2020'.
    The columns are grouped by prefix and the difference column would 
    be calculated between consecutive years. Essentially,
    difference between 2018 and 2019,
    difference betweeb 2019 and 2020, 
    would be calculated for prefix 'men'
    and the resulting 
    dataframe would then contain new columns:
    - 'men_2018_2019_diff', 'men_2018_2019_pct', 'men_2019_2020_diff', 'men_2019_2020_pct'
    and the original columns.
    
    Parameters:
    -----------
        timeseries_gdf::GeoDataFrame      : Is a timeseries dataframe where columns from several years
                                            have been merged to one dataframe and columns have year appended 
                                            to the end. 
        prefixes::list(str)               : Prefixes for the columns in the timeseries GeoDataFrame, which have 
                                            year appended
    Return:
    -------
        gdf::GeoDataFrame                 : The GeoDataFrame with all the original and all the difference columns
        original_cols::list(str)          : The list of original columns in the timeseries GeoDataFrame
        diff_cols::list(str)              : The list of new absolute change columns. Each column ends with '_diff'
        pct_cols::list(str)               : The list of new relative change columns. Each column ends with '_pct'
    """
    df_cols = list(timeseries_gdf.columns.values)
    assert len(df_cols) > 1, "Dataframe must have at least two columns"
    # Make a list of columns by prefix -pairs
    cols_by_prefix = [(prefix, list(filter(lambda x: x.startswith(prefix), timeseries_gdf.columns))) for prefix in prefixes]
    # Make a list of all columns which are yearly columns according to the prefix
    cols_from_prefixes = list(itertools.chain(*[ls for (col, ls) in cols_by_prefix]))
    # Take intersection of columns in the oroginal data frame and those
    # grouped from prefixes
    col_intersection = set(cols_from_prefixes).intersection(df_cols)
    columns = None
    # Use the column intersection only if it's
    # not shorter than the list of original
    # columns
    if len(col_intersection) < len(set(df_cols)):
        columns = df_cols
    else:
        # Columns are safe to be used as is
        columns = list(col_intersection)
    
    # deeply copy the dataframe, so the original does not change
    df = timeseries_gdf[columns].copy(deep=True)
    diff_cols = []
    pct_cols = []

    for (prefix, ls_cols) in cols_by_prefix:
        # Construct pairs of columns from consecutive years
        for a,b in itertools.pairwise(ls_cols):
            # Split year from the end of the string
            # assuming there's "_xxxx" at the end where "xxxx" denotes year. 
            year_a = a.split('_')[-1]
            year_b = b.split('_')[-1]
            # Make beginning for the result column by appending
            # start and end year to the prefix
            col_suffix = "{pr}_{ya}_{yb}".format(pr=prefix, ya=year_a, yb=year_b)
            # Add diff to the absolute difference column
            col_diff = "{}_diff".format(col_suffix)
            # and pct to the relative change column
            col_pct = "{}_pct".format(col_suffix)
            # Calculate absolute difference
            df[col_diff] = df[b] - df[a]
            # Calculate relative difference in percentages (% form)
            df[col_pct] = (( df[b] - df[a]) / df[a]) * 100
            # Add each column to the list of absolute
            # and relative change columns
            diff_cols.append(col_diff)
            pct_cols.append(col_pct)
    
    # Use all difference columns as new columns
    new_cols = diff_cols + pct_cols
    #print(diff_cols)
    # Sort columns alphabetically
    final_cols = sorted(new_cols + columns)
    gdf = df
    original_cols = df_cols
    return gdf, original_cols, diff_cols, pct_cols


def plot_population_differences(group_str, dcol, pcol, city1_gdf, city2_gdf, 
                                cities_str, k, t, size=(12,12), cmap_s='coolwarm', 
                                legend_bbox=(1.6, 1), wspace=1, hspace=0.001, 
                                legend_background_color='grey'):
    """
    Plots a set of population difference columns with geopandas.GeoDataFrame.plot()
    as a 2x2 subplots where row stands for the type of difference (absolute, relative)
    and columns stands for the city. Figure will contain:
    - On the first row:
      - Absolute difference plots for both cities using the 'dcol'
    on the second row:
      - Relative difference plots for both cities using the 'pcol'
    
    Each row will be classified using `mapclassify` library 
    by concatenating the column values from both cities' GeoDataFrames 
    and therefore the colors have uniform scale accross the row, 
    both on the map and the legend. Each row has a shared legend.
    
    Parameters:
    -----------
        group_str::str           : The name of the plotted group as a string. Name describes the plotted
                                   set of difference columns. It's essentially a more descriptive name
                                   for the common prefix of 'dcol' and 'pcol'. This will be added to 
                                   the end a of each legend title as a separate row.
        dcol::str                : A absolute difference column from timeseries_gdf_diff() with a '_diff'
                                   as the prefix. The column values will contain absolute difference of 
                                   two years.
        pcol::str                : A relative difference column from timeseries_gdf_diff() with a '_pct'
                                   as the prefix. The column values will contain relative difference of 
                                   two years in percentages (as % so don't multiply by 100).
        city1_gdf::GeoDataFrame  : timeseries GeoDataFrame from timeseries_gdf_diff() for city1
        city2_gdf::GeoDataFrame  : timeseries GeoDataFrame from timeseries_gdf_diff() for city2
        cities_str::list(str)    : A list of city names in the form "City, Country" such as "Helsinki, Finland".
                                   Will be added as the title on the corresponding column.
        k::int                   : Number of classes the column values are classified to
        t::str                   : Title for the whole figure
        size::tuple(float,float) : Size as a (width, height) tuple for the figure
        cmap_s::str              : String representation of valid matplotlib Colormap
        legend_bbox::tuple(f,f)  : bbox_to_anchor for the legend as a (float,float) tuple. Adjusts the position
                                   of the legends relative to the axes on the first column of each row
        wspace::float            : The horizontal space in inches between the subplots. Increase
                                   the default if the legend does not fit into the space between the plots.
        hspace::float            : The vertical space between the subplots in inches
        legend_background_color  : The background color of the legend as a string presentation of matplotlib
                                   Color.
    Return:
    ------
        fig::matplotlib.Figure   : The resulting figure of 2x2 subplots. Each city on each column and each
                                   difference type on each row. Each axes will be plotted using WebMercator
                                   (epsg:3857) since it's best supported by Contextily background maps.
        
    """
    logger.info(('Start plotting population difference subplots:'
                 'group_str:{gs}, dcol:{dc}, pcol:{pc}, cmap:{cm},'
                 'legend_bbox:{lb}').format(gs=group_str, dc=dcol,pc=pcol,cm=cmap_s,lb=legend_bbox))
    # Make a list of difference columns so they can be used
    # in list comprehensions and loops
    diff_cols = [dcol, pcol]
    # Do the same for GeoDataFrames
    gdfs = [city1_gdf, city2_gdf]
    # This is needed for the classification to work. 
    # Infinity in classification will ruin the classificaton
    # as every bin except the first will be infinite.
    pd.options.mode.use_inf_as_na = True
    # Loop through every combination of difference column - GeoDataFrame pair
    # to form a 2-dimensional array which works nicely with the plotting loop
    gdfs_arr = [[g[g[col].notna()].reset_index()[[col, 'geometry']] for g in gdfs] for col in diff_cols] 
    # Resulting "array" will have city1 on the first column, city2 on the next,
    # absolute change on the first row and relative change on the last row.
    
    # Make a colormap for plotting
    cmap = matplotlib.cm.get_cmap(cmap_s)
    
    # Concatenate series of absolute differences and
    # take the min and max values.
    series_concat_d = pd.concat([g[diff_cols[0]] for g in gdfs_arr[0]] )
    vmin_d, vmax_d = series_concat_d.min(), series_concat_d.max()
    
    # The same for relative differences
    series_concat_p = pd.concat([g[diff_cols[1]] for g in gdfs_arr[1]])
    vmin_p, vmax_p = series_concat_p.min(), series_concat_p.max()
    
    # Build normalization object using the min and max values and center=0.
    # This is an attempt to make negative change blue and positive change red.
    norm_d = matplotlib.colors.TwoSlopeNorm(vmin=vmin_d, vcenter=0, vmax=vmax_d)
    norm_p = matplotlib.colors.TwoSlopeNorm(vmin=vmin_p, vcenter=0, vmax=vmax_p)
    
    # Build classifier for absolute change using the 
    # concatenated series of values. This will make 
    # the color and number scale uniform accross the same type
    # of difference column, i.e. row of the plot.
    fj_d = mapclassify.FisherJenks(series_concat_d, k)
    classifier_d = fj_d.make(k=k)
    
    # Do the same with relative change
    fj_p = mapclassify.FisherJenks(series_concat_p, k)
    classifier_p = fj_p.make(k=k)
    classifiers = [classifier_d, classifier_p]
    
    # Use the bins to make appropriate colors for
    # the legend handles for absolute change
    bins_d = list(fj_d.bins)
    colors_d = [cmap(norm_d(val)) for val in bins_d]
    
    # Now the same with relative change
    bins_p = list(fj_p.bins)
    colors_p = [cmap(norm_p(val)) for val in bins_p]
    
    # Loop through every GeoDataFrame in the gdfs_arr, and use classifiers and colors to 
    # calculate classification column and color column for all the frames.
    for row, diff_col, clsr, color_list in zip(gdfs_arr, diff_cols, classifiers, [colors_d, colors_p]):
        for gdf in row:
            # Calculate classification column for every difference column
            # using the respective classifier
            gdf['cl'] = gdf[[diff_col]].apply(clsr)
            # Use the classification to give colors for every row in the
            # dataframes
            gdf['cl_color'] = gdf['cl'].apply(lambda c: color_list[c]) 
    
    # Build legend handles (patch + label) for each change type. ("Proxy Artists")
    handles_d = [mpatches.Patch(color=c, label=l) for c, l in zip(colors_d, fj_d.get_legend_classes())]
    handles_p = [mpatches.Patch(color=c, label=l) for c, l in zip(colors_p, fj_p.get_legend_classes())]
    
    # Make a list of handles so they can be easily used in the plotting loop
    handles = [handles_d, handles_p]
    # Legend titles for both difference types
    changes = ['Change (people),\n{}'.format(group_str), 'Change (%),\n{}'.format(group_str)]
    gdfs = gdfs_arr
    
    # Make a subplots object
    fig, axes = plt.subplots(2,2, figsize=size)
    # Loop through every row and column in the dataframes
    # and subplots axes and plot
    for r in range(0, len(axes)):
        for c in range(0, len(axes[r])):
            # Difference column changes by row
            diff_col = diff_cols[r]
            # Correct gdf is in the same index of the 2-dimensional
            # array as the index of the matplotlib Axes.
            # Project to Web Mercator, which the 
            gdf = gdfs[r][c].to_crs("epsg:3857")
            # Correct axes for the plot
            ax_rc = axes[r][c]
            # Plot the gdf using axes and colorize by precalculated color Series
            # Don't make a legend as that is build separately.
            ax = gdf.plot(ax=ax_rc, color=gdf['cl_color'], legend=False)
            # Set axis labels
            ax.set_xlabel('x (m)')
            ax.set_ylabel('y (m)')
            # Adjust horizontal and vertical space between axes
            # to make legend fit between the plots
            plt.subplots_adjust(wspace=wspace, hspace=hspace)
            # Add legend to axes only on the first column. 
            # Another one isn't needed as they share the legend.
            if c==0:
                ax.legend(handles=handles[r], bbox_to_anchor=legend_bbox, title=changes[r], facecolor=legend_background_color)
            # Set the title for each plot using the name of city
            ax_rc.set_title("{city}".format(city=cities_str[c]), y=1.0)
            # Add basemap using Contextily
            cx.add_basemap(ax=ax)
            logger.info('Plotted subplot axes for {c}, diff_col:{dc}'.format(c=cities_str[c], dc=diff_col))
    # Add a title for the figure
    fig.suptitle(t=t)
    # Disable the use_inf_as_na. Consider switching back earlier. In
    # distributed environment lot of bad stuff could happen with a
    # global options like this
    pd.options.mode.use_inf_as_na = False
    logger.info('Figure complete for {cl}'.format(cl=cities_str))
    return fig
                