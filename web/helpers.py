import aavs_calibration.common as db

from datetime import datetime, timedelta
from matplotlib.figure import Figure
import matplotlib.dates as md
import numpy as np


def station_list():
    station_list = db.get_station_list()
    return list(set(db.get_station_list()) - set(['UKPHASE0']))


def get_nof_tiles(station):
    """ Return number of antennas in station"""
    # TODO: Make better
    base, _, _ = db.get_antenna_positions(station)
    return len(base) / 16


def generate_fibre_delay_plot():
    """ Generate fibre delay plot """

    # Grab delay measurements for the last two days 
    cursor = db.db.fibre_delay.find({'measurement_time': { '$gte': datetime.now() - timedelta(days=2) }})
    cursor = cursor.sort([('measurement_time', -1)])

    # Create X and Y lists
    x, y = [], []
    for item in cursor:
        x.append(md.date2num(item['measurement_time']))
        y.append(item['delay'])

    # Create plot
    fig = Figure(figsize=(18, 8))
    ax = fig.subplots(nrows=1, ncols=1, sharex='all', sharey='all')
    date_format = md.DateFormatter('%-j - %H:%M:%S')
    ax.xaxis.set_major_formatter(date_format)

    ax.plot(x, y)
    ax.set_title("Delay measurements")
    ax.set_xlabel("Date (AWST)")
    ax.set_ylabel("Difference (degrees)")

    return fig


def generate_antenna_delay_plot(station):
    """ Generate antenna delay plot """

    _, _, _, delays = db.get_latest_calibration_solution(station, True)
    delays = delays * 1e3

    # Get antenna locations
    base, x, y = db.get_antenna_positions(station)

    # Generate plot for X
    fig = Figure(figsize=(18, 8))
    ax = fig.subplots(nrows=1, ncols=2, sharex='all', sharey='all')
    fig.suptitle("{} Latest Antenna Delays".format(station))

    ax[0].scatter(x, y, marker='o', c=delays[:, 0], s=50, cmap='seismic', edgecolors='k', vmin=-10, vmax=10, linewidths=0.8)
    for i in range(len(x)):
        ax[0].text(x[i] + 0.3, y[i] + 0.3, base[i], fontsize=7)
    ax[0].set_title("{} X Pol Delay".format(station))
    ax[0].set_xlabel("X")
    ax[0].set_ylabel("Y")

    # Generate plot for Y
    pcm = ax[1].scatter(x, y, marker='o', c=delays[:, 1], s=50, cmap='seismic', edgecolors='k', vmin=-10, vmax=10,
                        linewidths=0.8)
    for i in range(len(x)):
        ax[1].text(x[i] + 0.3, y[i] + 0.3, base[i], fontsize=7)
    ax[1].set_title("{} Y Pol Delay".format(station))
    ax[1].set_xlabel("X")

    # Add colorbar and save
    fig.subplots_adjust(bottom=0.1, top=0.9, left=0.1, right=0.88,
                        wspace=0.05, hspace=0.17)
    cb_ax = fig.add_axes([0.9, 0.1, 0.02, 0.8])
    fig.colorbar(pcm, label="Delay (ns)", cax=cb_ax)

    return fig
