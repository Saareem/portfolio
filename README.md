# portfolio
Some basic programming assignments and small programs as reference

# javascript_html

## new_portal_submitter, 2015
There's a mobile game called Ingress (https://ingress.com/) by Niantic (formerly Google). In the game there are portals which are virtual locations which need to be visited in the game to create links and fields between portals. The game also offers a full map of all the portals in the world: so called Intel Map (https://intel.ingress.com/intel). When the game launched, it didn't have any way to log the visited portals so that needed to be completed by hand. 

I initially used to copy the coordinates of the portal and its name into Google Maps by hand but I soon realized, there's a better way to do it. So, a tiny JavaScript web page was born in the form of new_portal_submitter.html and the associated css-file. The page includes two text fields for entering the name of the portal and the link for the portal in the Intel Map, which handily contains the associated coordinates. Then it reads those coordinates from the link and forms a KML Placemark element which is used in Google Earth to store placemark out of that name and the coordinates. The Placemark elements could then be added to a KML file which included all the portals I had visited. 
