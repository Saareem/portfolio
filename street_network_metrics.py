from functools import partial
from geopy.geocoders import Nominatim
import matplotlib.pyplot as plt
# import contextily as cx
import networkx as nx
import osmnx as ox

def get_networks(osm_cities_list):
    assert len(osm_cities_list) > 0, 'You should provide at least one city name in the list'
    cities = osm_cities_list
    if len(osm_cities_list) > 2:
        # Even two frames is a lot of data, so we will limit to two frames
        cities = osm_cities_list[:2]
    nets = []
    for city in cities:
        G = graph_from_place(city, 
    return nets