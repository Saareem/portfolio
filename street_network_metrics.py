import geopandas as gpd
import pandas as pd
import matplotlib.pyplot as plt
import networkx as nx
import osmnx as ox
import logging

logger = logging.getLogger(__name__)

def get_network(osm_city, network_type='bike'):
    assert type(osm_city) == str, 'You should provide a string'
    assert osm_city is not None, 'You should provide a city name'
    logger.info('Start downloading network for {city}, network_type={t}'.format(city=osm_city, t=network_type))
    graph = ox.graph_from_place(osm_city, network_type=network_type)
    assert graph is not None, 'No graphs returned by the query'
    logger.info('Network downloaded for {city}. Object: {g}'.format(city=osm_city, t=type(graph), g=graph))
    return osm_city, graph


def graphs_to_gdfs(graph_objs):
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
    
    def list_to_str(ls):
        if all([len(elem) > 1 and type(elem) == str for elem in ls]):
            return ", ".join(ls)
        else:
            return ls
    logger.info('Extracting value counts: {city}, exploded={exp}.'.format(city=cityname, exp=explode))
    renamed_col = 'Count ({city})'.format(city=cityname)
    if explode:
        logger.info('Exploding GeoDataFrame: {city}'.format(city=cityname))
        gdf = gdf.explode(col_name)
        logger.info('Exploding DONE: {city}'.format(city=cityname))
    counts = pd.DataFrame(gdf[col_name].value_counts().reset_index())
    if not explode:
        counts['index'] = counts['index'].apply(list_to_str)
    counts[col_name] = counts[col_name].astype(pd.Int64Dtype())
    logger.info('Renaming columns: {col}'.format(col=col_name))
    counts = counts.rename({col_name: renamed_col, 'index': type_title}, axis=1)
    return renamed_col, counts


def join_highway_type_counts(gdf_dict, join_col, cities):
    CITY1, CITY2 = cities
    logger.info('Start joining highway type counts on "{key}"'.format(key=join_col))
    for city in gdf_dict:
        gdf = gdf_dict[city]['edges']
        count_col_exp, counts_exp = gdf_value_counts(city, gdf, 'highway', join_col, explode=True)
        count_col, counts = gdf_value_counts(city, gdf, 'highway', join_col, explode=False)
        gdf_dict[city]['exp_counts'] = counts_exp
        gdf_dict[city]['counts'] = counts
    left_exp, right_exp = gdf_dict[CITY1]['exp_counts'], gdf_dict[CITY2]['exp_counts']
    joined_counts_exp = left_exp.merge(right=right_exp, left_on=join_col, right_on=join_col, how='outer')
    left, right = gdf_dict[CITY1]['counts'], gdf_dict[CITY2]['counts']
    joined_counts = left.merge(right=right, left_on=join_col, right_on=join_col, how='outer')
    logger.info('Type counts joined on "{key}"'.format(key=join_col))
    return joined_counts_exp, joined_counts