from aavs_calibration.definitions import AntennaType
from aavs_calibration.database import *
from urllib import urlopen

# Connect to database
db = connect()

# Sheet url
url = r"https://docs.google.com/spreadsheets/d/e/2PACX-1vQqOhkIgUBtIHBFOVRd34potpDGND7mIQ66hF97f4zwoMt30Jgko5tdNer_" \
      r"TsWOPZgYooA0UjR2KhrB/pub?gid=1156216434&single=true&output=tsv"

# Some global params
nof_antennas = 48

# Station name and location
station_name = "EDA2"
lat, lon = -26.7047565370444444, 116.6724377923805556

# This is used to re-map ADC channels index to the RX
# number going into the TPM
# [Antenna number / RX]
antenna_preadu_mapping = {0: 1, 1: 2, 2: 3, 3: 4,
                          8: 5, 9: 6, 10: 7, 11: 8,
                          15: 9, 14: 10, 13: 11, 12: 12,
                          7: 13, 6: 14, 5: 15, 4: 16}

# TPM order in configuration file
tpm_order = [21, 22, 23]
tpm_names = ["TPM 7", "TPM 11", "TPM 16"]


def populate_station():
    """ Reads antenna base locations from the Google Drive sheet and fills the data into the database """

    # Purge antennas from database
    purge_station(station_name)

    # Read antenna location spreadsheet
    response = urlopen(url)
    html = response.read().split('\n')

    # Two antennas are not in-place, however we still get an input into the TPM
    switched_preadu_map = {y: x for x, y in antenna_preadu_mapping.iteritems()}

    # Antenna information placeholder
    antenna_information = []

    # Loop over Tiles in order
    for tpm in tpm_order:
        # Go through rows in spreadsheet and process antennas connected to current tpm
        for i in range(1, len(html)):
            items = html[i].split('\t')
            if items[12] != '-' and int(items[12]) == tpm:
                base, rx = int(items[0]), int(items[13])
                north, east, up = float(items[1].replace(',', '.')), float(items[2].replace(',', '.')), 0
                antenna_information.append({'base': base, 'tpm': tpm, 'rx': rx, 'east': east, 'north': north})

    # Create station entry
    Station(name=station_name,
            nof_antennas=nof_antennas,
            antenna_type=AntennaType.EDA2.name,
            tpms=tpm_order,
            latitude=lat,
            longitude=lon).save()

    # Grab station information
    station = Station.objects(name=station_name).first()

    for i, antenna in enumerate(antenna_information):
        # Fill data into database

        Antenna(antenna_station_id=tpm_order.index(antenna['tpm']) * 16 + switched_preadu_map[antenna['rx']],
                station_id=station.id,
                x_pos=antenna['east'],
                y_pos=antenna['north'],
                base_id=antenna['base'],
                tpm_id=antenna['tpm'],
                tpm_name="Tile {}".format(tpm_order[i / 16]),
                tpm_rx=antenna['rx'],
                status_x='',
                status_y='').save()


populate_station()