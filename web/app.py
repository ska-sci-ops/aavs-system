
from matplotlib.backends.backend_svg import FigureCanvasSVG as FigureCanvas
from flask import Flask, Response, render_template, send_from_directory, abort
import helpers
import time
import io

# Bandpass directory
bandpass_directory = "/storage/monitoring/bandpass"

# Gloval stations list
stations = [s.upper() for s in helpers.station_list()]
print(stations)

# Remove old  stations
stations.remove("AAVS1")
stations.remove("AAVS1.5")

app = Flask(__name__)

# app name 
@app.errorhandler(404) 

# inbuilt function which takes error as parameter 
def not_found(e): 
  return render_template("error_page.html") 


@app.route('/')
def index():
    """ Index page"""
    return render_template('index.html', stations=stations)


@app.route('/<station_name>')
def station(station_name):
    """ Display the main station page"""
    station_name = station_name.upper()
    if station_name not in stations:
        return render_template('error_page.html')
    else:
        return render_template("station.html", station=station_name, show_rms=True, show_delays=True)


@app.route('/<station_name>/rms')
def station_antenna_rms(station_name):
    """ Return a plot showing the antenna layout of the station """
    station_name = station_name.upper()

    while True:
        with open("{}/{}/antenna_rms.svg".format(bandpass_directory, station_name), 'r') as f:
            data = f.read()
            if data.endswith("</svg>\n"):
                break
            else:
                time.sleep(0.1)

    buff = io.BytesIO()
    buff.write(data)
    return Response(buff.getvalue(), mimetype='image/svg+xml')


@app.route('/<station_name>/rms/show', methods=['GET'])
def show_station_rms_image(station_name):
    """ Show antenna RMS image """
    station_name = station_name.upper()
    return render_template('show_image.html', refresh=True, image='/{}/rms'.format(station_name.upper()))


@app.route('/<station_name>/bandpass/<pol>/<tile>', methods=['GET'])
def get_bandpass(station_name, pol, tile):
    """ Return the required bandpass plot from the bandpass directory as a Response object """
    station_name = station_name.upper()
    pol = pol.lower()
    tile = int(tile)

    while True:
        with open("{}/{}/tile_{}_pol_{}.svg".format(bandpass_directory, station_name, tile+1, pol), 'r') as f:
            data = f.read()
            if data.endswith("</svg>\n"):
                break
            else:
                time.sleep(0.1)

    buff = io.BytesIO()
    buff.write(data)
    return Response(buff.getvalue(), mimetype='image/svg+xml')


@app.route('/<station_name>/bandpass/<pol>', methods=['GET'])
def show_bandpasses(station_name, pol):
    """ Display all tile bandpasses for the selected station """
    station_name = station_name.upper()
    pol = pol.lower()

    # Generate images list
    nof_tiles = helpers.get_nof_tiles(station_name.upper())
    images = []
    for i in range(nof_tiles):
        images.append('/{}/bandpass/{}/{}'.format(station_name.upper(), pol, i))
    return render_template('bandpasses.html', station=station_name, nof_tiles=nof_tiles, images=images, pol=pol)


@app.route('/<station_name>/bandpass/<pol>/<tile>/show', methods=['GET'])
def show_bandpass_image(station_name, pol, tile):
    """ Show a single bandpass image """
    station_name = station_name.upper()
    pol = pol.lower()
    tile = int(tile)

    return render_template('show_image.html', refresh=True, image='/{}/bandpass/{}/{}'.format(station_name.upper(), pol, tile))


@app.route("/<station_name>/calibration/delay_map/show", methods=['GET'])
def show_latest_delay_map(station_name):
    """ Generate latest delay map plot"""
    station_name = station_name.upper()
    figure = helpers.generate_antenna_delay_plot(station_name)
    output = io.BytesIO()
    FigureCanvas(figure).print_svg(output)
    return Response(output.getvalue(), mimetype='image/svg+xml')

@app.route("/<station_name>/fibre", methods=['GET'])
def show_latest_fibre_delays(station_name):
    """ Generate latest delay map plot"""
    figure = helpers.generate_fibre_delay_plot()
    output = io.BytesIO()
    FigureCanvas(figure).print_svg(output)
    return Response(output.getvalue(), mimetype='image/svg+xml')


@app.route("/<station_name>/calibration/delay_map", methods=['GET'])
def get_latest_delay_map(station_name):
    return render_template('show_image.html', refresh=False, image='/{}/calibration/delay_map/show'.format(station_name.upper()))


@app.route("/phase1/eda2")
def phase1_eda_page():
    return send_from_directory("/storage/monitoring/phase1/eda-2", "index.html")


@app.route("/phase1/aavs2")
def phase2_skala_page():
    return send_from_directory("/storage/monitoring/phase1/skala-4", "index.html")


@app.route("/phase1/STATION_EDA-2.png")
def phase1_eda_plot():
    return send_from_directory("/storage/monitoring/phase1/eda-2", "STATION_EDA-2.png")


@app.route("/phase1/STATION_SKALA-4.png")
def phase2_skala_plot():
    return send_from_directory("/storage/monitoring/phase1/skala-4", "STATION_SKALA-4.png")


if __name__ == "__main__":
    app.run(debug=True, port=80, host="0.0.0.0")
