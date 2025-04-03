import osmnx as ox
import networkx as nx
import folium
from flask import Flask, request, render_template_string
from geopy.geocoders import Nominatim
from geopy.distance import geodesic
from math import radians, cos, sin, sqrt, atan2
import random

app = Flask(__name__)

# Initialize geocoder
geolocator = Nominatim(user_agent="geoapp")

# Function to download the road network for a specific location
def download_graph(location, buffer_dist=5000):
    graph = ox.graph_from_place(location, network_type='all', buffer_dist=buffer_dist, simplify=False)
    return graph

# Function to create and integrate a simulated traffic dataset
def integrate_simulated_traffic(graph):
    """
    Create a simulated dataset to adjust the edge weights of the graph to simulate traffic conditions.
    This dataset includes traffic speed, roadblocks, traffic jams, and accidents.

    Args:
        graph (networkx.DiGraph): The road network graph.
    
    Returns:
        networkx.DiGraph: Updated graph with integrated traffic data.
    """
    # Simulated traffic dataset: Traffic speed, roadblocks, traffic jams, accidents
    # These values will be used to simulate the effect on each edge in the graph.
    for u, v, data in graph.edges(data=True):
        # Simulate random traffic conditions for each edge
        data['traffic_speed'] = random.uniform(20, 60)  # Speed in km/h (low speed indicates congestion)
        data['roadblock'] = random.choice([True, False])  # True if roadblock is present
        data['traffic_jam'] = random.choice([True, False])  # True if there's a traffic jam
        data['accident'] = random.choice([True, False])  # True if an accident is reported

        # Modify the edge weight based on traffic conditions
        # If there's a roadblock, make the weight very high (essentially unusable)
        if data['roadblock']:
            data['length'] *= 10
            print(f"Roadblock detected on edge {u} -> {v}, increasing weight")

        # If there's a traffic jam, increase the weight based on the reduction in speed
        if data['traffic_jam']:
            speed_factor = data['traffic_speed'] / 60  # Reduce weight proportionally to speed (60 km/h max)
            data['length'] *= (1 / speed_factor) if speed_factor != 0 else 10  # Avoid division by zero
            print(f"Traffic jam on edge {u} -> {v}, speed reduced to {data['traffic_speed']} km/h")

        # If there's an accident, make the route less desirable
        if data['accident']:
            data['length'] *= 1.5  # Increase length to simulate delay
            print(f"Accident reported on edge {u} -> {v}, increasing length by 1.5x")

    return graph

# Haversine distance for A* heuristic
def haversine_distance(node1, node2):
    lat1, lon1 = node1
    lat2, lon2 = node2

    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    r = 6371  # Radius of Earth in kilometers
    return r * c * 1000  # Return in meters

# HTML template for the map and controls
html_template = '''
<!DOCTYPE html>
<html>
<head>
    <title>Interactive Map</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.7.1/dist/leaflet.css" />
    <script src="https://unpkg.com/leaflet@1.7.1/dist/leaflet.js"></script>
    <style>
        body, html { height: 100%; margin: 0; }
        #map { height: 80%; width: 100%; }
        #controls { text-align: center; margin-top: 10px; }
    </style>
</head>
<body>
    <form action="/set_location" method="POST" style="margin-bottom: 20px; text-align:center;">
        <label for="location">Enter a location: </label>
        <input type="text" id="location" name="location" placeholder="Enter city or address" required>
        <input type="submit" value="Set Location">
    </form>

    <div id="map"></div>
    <div id="controls">
        <button onclick="findPath()">Find Path</button>
        <button onclick="resetMap()">Reset Map</button>
    </div>

    <script>
        var lat = {{ lat }};
        var lon = {{ lon }};
        var map = L.map('map').setView([lat, lon], 13);
        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19 }).addTo(map);

        var startMarker, endMarker, waypointMarkers = [];

        map.on('click', function(e) {
            var lat = e.latlng.lat;
            var lng = e.latlng.lng;

            if (!startMarker) {
                startMarker = L.marker([lat, lng], { draggable: true }).addTo(map)
                    .bindPopup('Start Point').openPopup();
                document.getElementById('start').value = lat + ',' + lng;
            } else if (!endMarker) {
                endMarker = L.marker([lat, lng], { draggable: true }).addTo(map)
                    .bindPopup('End Point').openPopup();
                document.getElementById('end').value = lat + ',' + lng;
            } else {
                // Add intermediate waypoints
                var waypointMarker = L.marker([lat, lng], { draggable: true }).addTo(map)
                    .bindPopup('Waypoint').openPopup();
                waypointMarkers.push(waypointMarker);
                document.getElementById('waypoints').value += lat + ',' + lng + ';';
            }
        });

        function findPath() {
            var start = document.getElementById('start').value;
            var end = document.getElementById('end').value;
            var waypoints = document.getElementById('waypoints').value;

            if (start && end) {
                window.location.href = '/find_path?start=' + start + '&end=' + end + '&waypoints=' + waypoints;
            } else {
                alert('Please select a start and end point.');
            }
        }

        function resetMap() {
            if (startMarker) map.removeLayer(startMarker);
            if (endMarker) map.removeLayer(endMarker);
            waypointMarkers.forEach(function(marker) {
                map.removeLayer(marker);
            });
            startMarker = null;
            endMarker = null;
            waypointMarkers = [];
            document.getElementById('start').value = '';
            document.getElementById('end').value = '';
            document.getElementById('waypoints').value = '';
        }
    </script>

    <input type="hidden" id="start">
    <input type="hidden" id="end">
    <input type="hidden" id="waypoints">
</body>
</html>
'''

@app.route('/')
def index():
    """Default route to render the interactive map."""
    return render_template_string(html_template, lat=34.0234, lon=-84.6155)  # Default: Kennesaw, GA

@app.route('/set_location', methods=['POST'])
def set_location():
    """Route to handle location input and update the map."""
    location = request.form.get('location')
    try:
        geocode_result = geolocator.geocode(location, timeout=10)
        if geocode_result:
            lat, lon = geocode_result.latitude, geocode_result.longitude
            global graph, graph_unprojected
            graph = download_graph(location)
            graph = integrate_simulated_traffic(graph)  # Integrate the simulated traffic data into the graph
            graph_unprojected = ox.project_graph(graph, to_crs='epsg:4326')
            return render_template_string(html_template, lat=lat, lon=lon)
        else:
            return "<h1>Location not found. Please try again.</h1>"
    except Exception as e:
        return f"<h1>Error: {str(e)}</h1>"

@app.route('/find_path')
def find_path():
    """Route to calculate and display the shortest path."""
    global graph, graph_unprojected

    start = request.args.get('start')
    end = request.args.get('end')
    waypoints = request.args.get('waypoints', '').strip(';').split(';') if request.args.get('waypoints') else []

    start_lat, start_lon = map(float, start.split(','))
    end_lat, end_lon = map(float, end.split(','))
    waypoint_coords = [tuple(map(float, w.split(','))) for w in waypoints]

    # Sort waypoints by distance to the start point
    waypoint_coords.sort(key=lambda wp: geodesic((start_lat, start_lon), wp).meters)

    # Calculate the complete path
    dijkstra_coords = []
    a_star_coords = []
    previous_node = ox.distance.nearest_nodes(graph_unprojected, X=start_lon, Y=start_lat)

    def heuristic(u, v):
        """Haversine distance heuristic for A*."""
        u_coords = (graph_unprojected.nodes[u]['y'], graph_unprojected.nodes[u]['x'])
        v_coords = (graph_unprojected.nodes[v]['y'], graph_unprojected.nodes[v]['x'])
        return haversine_distance(u_coords, v_coords)

    for waypoint in waypoint_coords:
        waypoint_node = ox.distance.nearest_nodes(graph_unprojected, X=waypoint[1], Y=waypoint[0])
        dijkstra_sub_path = nx.shortest_path(graph, source=previous_node, target=waypoint_node, weight='length')
        dijkstra_coords.extend([(graph_unprojected.nodes[node]['y'], graph_unprojected.nodes[node]['x']) for node in dijkstra_sub_path])

        a_star_sub_path = nx.astar_path(graph, source=previous_node, target=waypoint_node, heuristic=heuristic, weight='length')
        a_star_coords.extend([(graph_unprojected.nodes[node]['y'], graph_unprojected.nodes[node]['x']) for node in a_star_sub_path])

        previous_node = waypoint_node

    # Add the final path segment to the end point
    end_node = ox.distance.nearest_nodes(graph_unprojected, X=end_lon, Y=end_lat)
    dijkstra_sub_path = nx.shortest_path(graph, source=previous_node, target=end_node, weight='length')
    dijkstra_coords.extend([(graph_unprojected.nodes[node]['y'], graph_unprojected.nodes[node]['x']) for node in dijkstra_sub_path])

    a_star_sub_path = nx.astar_path(graph, source=previous_node, target=end_node, heuristic=heuristic, weight='length')
    a_star_coords.extend([(graph_unprojected.nodes[node]['y'], graph_unprojected.nodes[node]['x']) for node in a_star_sub_path])

    # Offset the A* path slightly to create visual separation
    offset = 0.00001
    a_star_coords_offset = [(lat + offset, lon + offset) for lat, lon in a_star_coords]

    # Create the map with paths
    midpoint = [(start_lat + end_lat) / 2, (start_lon + end_lon) / 2]
    m = folium.Map(location=midpoint, zoom_start=13)

    # Add markers
    folium.Marker([start_lat, start_lon], tooltip='Start', icon=folium.Icon(color='green')).add_to(m)
    folium.Marker([end_lat, end_lon], tooltip='End', icon=folium.Icon(color='red')).add_to(m)
    for lat, lon in waypoint_coords:
        folium.Marker([lat, lon], tooltip='Waypoint', icon=folium.Icon(color='blue')).add_to(m)

    # Draw the Dijkstra path (blue)
    folium.PolyLine(dijkstra_coords, color='blue', weight=5, opacity=0.6, tooltip='Dijkstra Path').add_to(m)

    # Draw the offset A* path (red)
    folium.PolyLine(a_star_coords_offset, color='red', weight=5, opacity=0.6, tooltip='A* Path (offset)').add_to(m)

    # Calculate total distances
    dijkstra_distance = sum(ox.utils_graph.get_route_edge_attributes(graph, dijkstra_sub_path, 'length'))
    a_star_distance = sum(ox.utils_graph.get_route_edge_attributes(graph, a_star_sub_path, 'length'))

    # Render map in HTML
    map_html = m._repr_html_()
    return render_template_string('''
    <!DOCTYPE html>
    <html>
    <head>
        <title>Path with Waypoints</title>
    </head>
    <body>
        <div>{{ map_html | safe }}</div>
        <div style="text-align: center; margin-top: 20px;">
            <p>Dijkstra Path Total Distance: {{ dijkstra_distance }} meters</p>
            <p>A* Path Total Distance: {{ a_star_distance }} meters</p>
            <button onclick="window.location.href='/'">Regenerate</button>
        </div>
    </body>
    </html>
    ''', map_html=map_html, dijkstra_distance=dijkstra_distance, a_star_distance=a_star_distance)

if __name__ == '__main__':
    app.run(debug=True)