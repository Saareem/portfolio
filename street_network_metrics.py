import geopandas as gpd
import pandas as pd
import matplotlib.pyplot as plt
import networkx as nx
import osmnx as ox
import logging

# Initialize logger for the module
logger = logging.getLogger(__name__)

def get_network(osm_city, network_type='bike'):
    """
    Get network for a city using the name of the city in the query.
    Use names which contain the country separated with a comma, since
    queries like 'Helsinki' might return results which are not
    from the actual city of Helsinki, Finland. Change network_type
    parameter to switch to a different kind of network. Types can be found 
    from osmnx documentation: 
    https://osmnx.readthedocs.io/en/stable/search.html?q=network_type&check_keywords=yes&area=default
    
    Note that fetching network data for large cities might take several minutes!
    
    returns:
        osm_city::string             : placename
        graph::networkx.MultiDiGraph : the graph from the query 
    Usage:
    
    city, g = get_network('Helsinki, Finland', 'bike')
    # downloads the bicycle network of Helsinki, Finland.
    """
    assert type(osm_city) == str, 'You should provide a string'
    assert osm_city is not None, 'You should provide a city name'
    logger.info('Start downloading network for {city}, network_type={t}'.format(city=osm_city, t=network_type))
    graph = ox.graph_from_place(osm_city, network_type=network_type)
    assert graph is not None, 'No graphs returned by the query'
    logger.info('Network downloaded for {city}. Object: {g}'.format(city=osm_city, t=type(graph), g=graph))
    return osm_city, graph


def graphs_to_gdfs(graph_objs):
    """
    Takes a graph object (graph dictionary) with a following structure:
    {
        cityname::string: {
            {
                'graph': <networkx.MultiDiGraph>,
                .
                .
                .
                other keys
            }
        }
        .
        .
        .
        other cities
    }
    
    and returns the graph object populated with nodes and edges
    as geopandas.GeoDataFrames for all cities. Will also project
    graph to a suitable UTM zone for metric calculations.
    
    """
    assert len(graph_objs.keys()) > 0, 'No graphs to convert'
    for key in graph_objs:
        logger.info('Reprojecting graph: {city}'.format(city=key))
        graph = ox.project_graph(graph_objs[key]['graph'])
        logger.info('Start converting to a GeoDataFrame: {city}'.format(city=key))
        nodes, edges = ox.graph_to_gdfs(graph)
        graph_objs[key]['edges'] = edges
        graph_objs[key]['nodes'] = nodes
        logger.info('Conversion DONE: {city}'.format(city=key))
    return graph_objs


def gdf_value_counts(cityname, gdf, col_name, type_title, explode=False):
    """
    Calculate value counts for some column 'col_name' in the GeoDataFrame (or pandas.DataFrame),
    changes count values to integers and renames some columns. 
    
    Params:
        cityname::str              : name of the city, which will be used in the value count column
        gdf::DataFrame/GeoDataFrame: data frame from which the value counts are calculated
        col_name::str              : a column name in the dataframe which will be used for calculating
        the value counts
        type_title::str            : a column name for the type (grouping key) column
        explode::bool              : defines if the dataframe will be exploded using 'col_name'
                                     before calculating value counts. Exploding the frame is useful
                                     for columns which have lists as value. The lists will be converted to string
                                     if explode is set off.
    Return:
        renamed_col::str            : A name for the count value column
        counts::pandas.DataFrame    : A dataframe for the value counts
    """
    
    def list_to_str(ls):
        """
        Converts list of strings to string 
        but leaves strings unchanged.
        """
        if all([len(elem) > 1 and type(elem) == str for elem in ls]):
            return ", ".join(ls)
        else:
            return ls
        
    logger.info('Extracting value counts: {city}, exploded={exp}.'.format(city=cityname, exp=explode))
    renamed_col = 'Count ({city})'.format(city=cityname)
    if explode: # Explode if the column has lists as value
        logger.info('Exploding GeoDataFrame: {city}'.format(city=cityname))
        gdf = gdf.explode(col_name)
        logger.info('Exploding DONE: {city}'.format(city=cityname))
    counts = pd.DataFrame(gdf[col_name].value_counts().reset_index())
    if not explode:
        # Convert lists of strings to string
        counts['index'] = counts['index'].apply(list_to_str)
    # Change count values to integer as they are whole numbers
    counts[col_name] = counts[col_name].astype(pd.Int64Dtype())
    logger.info('Renaming columns: {col}'.format(col=col_name))
    # Rename some columns for nice visualizations
    counts = counts.rename({col_name: renamed_col, 'index': type_title}, axis=1)
    return renamed_col, counts


def join_highway_type_counts(gdf_dict, val_count_col, join_col, cities):
    """
    Calculates and joins value counts from two cities into a common DataFrame
    The joins are performed both with and without exploding the
    column first.
    Params:
        gdf_dict::dict  : a dictionary with following structure
        {
            cityname::string: {
                {
                    'graph': <networkx.MultiDiGraph>,
                    'edges': <pandas.GeoDataFrame>,
                    'nodes': <pandas.GeoDataFrame>,
                    .
                    .
                    .
                    other keys
                }
            }
            .
            .
            .
            other cities
        }
        
        val_count_col::str           : a column used for calculating value counts
        join_col::str                : Column used as the type title for comparison column
                                       frames and as a column in joining the frames
        cities::tuple                : A 2-tuple of city names
        
    Return:
        joined_counts_exp::DataFrame : Value counts joined together exploded before joining
        joined_counts::DataFrame     : Value counts joined together without exploding
    """
    CITY1, CITY2 = cities
    logger.info('Start joining highway type counts on "{key}"'.format(key=join_col))
    for city in gdf_dict: # Loop the cities in the dictionary
        gdf = gdf_dict[city]['edges']
        # calculate value counts with exploding
        count_col_exp, counts_exp = gdf_value_counts(city, gdf, val_count_col, join_col, explode=True)
        # calcualte value counts without exploding
        count_col, counts = gdf_value_counts(city, gdf, val_count_col, join_col, explode=False)
        gdf_dict[city]['exp_counts'] = counts_exp
        gdf_dict[city]['counts'] = counts
    # Join exploded and non-exploded value counts together for easier comparison of cities
    left_exp, right_exp = gdf_dict[CITY1]['exp_counts'], gdf_dict[CITY2]['exp_counts']
    # Use outer join to preserve index in both tables
    joined_counts_exp = left_exp.merge(right=right_exp, left_on=join_col, right_on=join_col, how='outer')
    left, right = gdf_dict[CITY1]['counts'], gdf_dict[CITY2]['counts']
    joined_counts = left.merge(right=right, left_on=join_col, right_on=join_col, how='outer')
    logger.info('Type counts joined on "{key}"'.format(key=join_col))
    return joined_counts_exp, joined_counts