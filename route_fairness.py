import csv
import openrouteservice
import argparse
import math

PROFILE = 'cycling-regular'
FORMAT = 'geojson'
LOCUST_ST_COORDS = (-72.65808105468751, 42.33334765235137)
VALLEY_RECYC_COORDS = (-72.65505552291872, 42.30060518470567)


class Geography:
    """
    Performs routing and other geographic computation
    """

    def __init__(self):
        """
        Initializes self
        """
        self.client = openrouteservice.Client(
            base_url='http://localhost:8080/ors')

    def navigate(self, start, end):
        """
        Finds a path between the points start and end

        Arguments:
            start: (float, float) -- tuple containing lon,lat of starting point
            end: (float, float) -- tuple containing lon,lat of ending point

        Returns:
            dict -- Dictionary containing:
                'geometry': [[float, float, float],...] -- list of lon,lat,elv
                    points on path
                'ascent': float -- Vertical meters up on path
                'descent': float -- Vertical meters down on path
                'distance': float -- Path length in meters
        """
        directions = self.client.directions((start, end), profile=PROFILE,
            format=FORMAT, elevation=True)['features'][0]
        assert len(directions['properties']['segments']) == 1
        return {
            'geometry': directions['geometry']['coordinates'],
            'ascent': directions['properties']['ascent'],
            'descent': directions['properties']['descent'],
            'distance': directions['properties']['segments'][0]['distance']
        }


class RouteFairness:
    """
    Stores information on routes and pickups, provides an interface to collect
    information on route difficulty
    """

    def __init__(self, route_table, pickup_table):
        """
        Initializes self

        Arguments:
            route_table: str -- the name of the tsv file containing the route
                table
            pickup_table: 
        """
        self.geography = Geography()
        self.difficulty_indicators = {
            'ascent': (lambda pickup: pickup['path']['ascent'], 'ascent'),
            'descent': (lambda pickup: pickup['path']['descent']*-1,
                'descent'),
            'distance': (lambda pickup: pickup['path']['distance'], 'distance')
        }

        self.route_table = {}
        with open(route_table, newline='') as file:
            reader = csv.DictReader(file)
            for row in reader:
                row['difficulty'] = {indicator: 0 for indicator in
                                     self.difficulty_indicators}
                row['num_pickups'] = 0
                self.route_table[row['indexnum']] = row

        self.pickup_table = {}
        with open(pickup_table, newline='') as file:
            reader = csv.DictReader(file, delimiter='\t')
            for row in reader:
                row['difficulty'] = {indicator: 0 for indicator in
                                     self.difficulty_indicators}
                self.pickup_table[row['id']] = row

        for id in self.pickup_table:
            self.get_path(self.pickup_table[id])


    def get_path(self, pickup):
        """
        Adds path information to pickup['path']

        Arguments:
            pickup: dict -- The pickup to add path information to
        """
        pickup_coords = (pickup['longitude'], pickup['latitude'])
        match self.route_table[pickup['route_id']]['destination']:
            case "Locust":
                pickup['path'] = self.geography.navigate(
                    pickup_coords, LOCUST_ST_COORDS)
            case "Valley":
                pickup['path'] = self.geography.navigate(
                    pickup_coords, LOCUST_ST_COORDS)
            case _:
                pickup['path'] = {'geometry': None, 'ascent': None,
                                  'descent': None, 'distance': None}

    def score_pickups(self, *args):
        """
        Computes per pickup difficulty, stores result in pickup['difficulty']

        Arguments:
            indicators: [(function, str),...] -- Tuples containing name and
                function used to compute the desired difficulty indicator, the
                indicator function should take a self.pickup_table entry as
                only argument
        """
        indicators = [self.difficulty_indicators[indicator] for indicator in
                      args]
        for indicator in indicators:
            min = math.inf
            max = math.inf * -1
            scores = {}
            for id in self.pickup_table:
                score = indicator[0](self.pickup_table[id])
                scores[id] = score
                if score < min:
                    min = score
                if score > max:
                    max = score

            # Normalize and store data
            for id in self.pickup_table:
                score = (scores[id] - min) / (max - min)
                self.pickup_table[id]['difficulty'][indicator[1]] = score

    def score_routes(self):
        """
        Computes per route difficulty, stores result in route['difficulty']

        Works with existing per pickup difficulty scores, be sure to score
        pickups with score_pickups before calling score_routes
        """
        for id in self.pickup_table:
            pickup = self.pickup_table[id]
            route = self.route_table[pickup['route_id']]
            route['num_pickups'] += 1
            for indicator in pickup['difficulty']:
                route['difficulty'][indicator] += \
                pickup['difficulty'][indicator]

        # Average over pickups
        empty = []
        for id in self.route_table:
            route = self.route_table[id]
            if route['num_pickups'] == 0:
                empty.append(id)
                continue
            for indicator in route['difficulty']:
                route['difficulty'][indicator] /= route['num_pickups']

        for id in empty:
            del self.route_table[id]

    def compute_difficulty(self, *args):
        """
        Computes per pickup and per route difficulty, stores result in
        pickup['difficulty'] and route['difficulty']

        Arguments:
            indicators: [(function, str),...] -- Tuples containing name and
                function used to compute the desired difficulty indicator, the
                indicator function should take a self.pickup_table entry as
                only argument
        """
        self.score_pickups(*args)
        self.score_routes()

    def print_difficulties(self, group_name, get_unit_name, entries, 
                           cell_size=30):
        row = lambda l,f,c,r: print(l+str(f*cell_size+c)*(width-1)+
                                    str(f*cell_size)+r)
        first = next(iter(entries.items()))[1] # Get first entry
        width = len(first['difficulty']) + 1
        row('┏', '━', '┳', '┓')
        print(f'┃{group_name:^{cell_size}}', end='')
        for attribute in first['difficulty']:
            print(f'┃{attribute:^{cell_size}}', end='')
        print('┃')
        row('┡', '━', '╇', '┩')
        for id in entries:
            entry = entries[id]
            print(f'│{get_unit_name(entry):^{cell_size}}', end='')
            for attribute in entry['difficulty']:
                print(f'│{entry["difficulty"][attribute]:^{cell_size}}', end='')
            print('│')
        row('└', '━', '┴', '┘')

    def print_route_difficulties(self):
        self.print_difficulties('route name', lambda r: r['route_name'],
                                route_fairness.route_table)

    def print_pickup_difficulites(self):
        self.print_difficulties('pickup name', lambda p: p['house_number']+" "+
                                p['street'], route_fairness.pickup_table)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        prog='Pedal People route fairness system', description='Reads in and \
        stores information on routes and pickups, returns difficulty per \
        pickup')
    parser.add_argument('routes', help='filename of route table to import')
    parser.add_argument('pickups', help='filename of pickup table to import')
    args = parser.parse_args()

    route_fairness = RouteFairness(args.routes, args.pickups)
    route_fairness.compute_difficulty('ascent','descent','distance')

    route_fairness.print_route_difficulties()
    input("Press enter to print pickup difficulties:")
    route_fairness.print_pickup_difficulites()

