from django.apps import AppConfig
from django.http import HttpResponse
from .utils import NIRSImage

# Import NIRS library.
from nirs_plotter_server.settings import BASE_DIR

import io
import os
import sys
sys.path.append(os.path.join(BASE_DIR, "../lib"))
from pynirs.NIRS import NIRS

import json
import time
import queue
import serial
from serial.tools.list_ports import comports
import threading
import numpy as np
import matplotlib as mlp
import matplotlib.pyplot as plt

mlp.use("Agg")


def serial_reader(port, lock, buffer, plotter_state):
    """Keep reading from the serial port.
       Also query and interpret the machine state.
    """

    while threading.main_thread().is_alive():
        # Sleep to prevent from overwhelming.
        time.sleep(0.10)

        # Query machine state.
        port.write("?\n".encode())

        with lock:
            # Fast reading.
            while True:
                data = port.readline().decode()
                if len(data) == 0:
                    break
                elif data == "\r\n":
                    pass
                else:
                    # Check and interpret machine state info.
                    # e.g.: <Alarm|WPos:0.000,0.000,0.000|FS:0,0>
                    if data[0] == "<":
                        # Split the message.
                        all_items = data[1:-1].split("|")

                        # Update the state and the position.
                        plotter_state["state"] = all_items[0]
                        plotter_state["position"] = list([float(pos) for pos in all_items[1].split(":")[1].split(",")])

                        # Regulate float numbers.
                        plotter_state["position"] = [0.0 if (-0.01 <= v <= 0.0) else v for v in plotter_state["position"]]

                    else:
                        # Save the data to buffer, deque the if full.
                        if buffer.full():
                            buffer.get()
                        buffer.put(data)
    # Clean up.
    port.close()


def construct_plotter_image_response(fig, ax, image, extent, plotter_state):
    """Draw and generate plotter image response."""
    while True:
        # Clear figure.
        ax.clear()
        # image = np.random.random(image.shape)
        # image[0, :] = 0
        # image[:, 0] = 0
        # plotter_state["position"] = np.random.randint(0, 50, (3, ))

        # Draw the map.
        # Copy image to prevent manipulation.
        img = image.get_image()
        img_mask = image.scan_flags.transpose()
        img_painted = np.copy(img)

        if np.any(image.scan_flags):
            # Scanned image.
            min_value = np.min(img[img_mask])
            max_value = np.max(img[img_mask])

            # Normalize array (revert 0 as no ink, 1 as with ink).
            img_painted = image.normalize_array(img_painted, mask=img_mask)

            # Set unscanned area as white -- max intensity (no ink).
            img_painted[~img_mask] = 0

        else:
            # Empty image -- not scanned yet.

            # Set image to plain white.
            img_painted = np.zeros(img.shape)

        print(img[0][0])
        ax.imshow(img_painted, cmap="binary", extent=extent, origin="upper", zorder=1,
                  vmin=0, vmax=1)
        ax.plot(plotter_state["position"][0], plotter_state["position"][1], "+r",
                markersize=15, clip_on=False, zorder=2)
        ax.plot(plotter_state["position"][0], plotter_state["position"][1], "or",
                markersize=15, clip_on=False, zorder=2, mfc="none")

        # fig.tight_layout()
        # fig.savefig("output.png", bbox_inches='tight')
        fig.savefig("output.png", dpi=fig.dpi)

        # Prepare response.
        buf = io.BytesIO()
        # canvas.print_png(buf, bbox_inches='tight', pad_inches=0)
        # fig.savefig(buf, bbox_inches="tight")
        fig.savefig(buf, dpi=fig.dpi, format="png")
        response = HttpResponse(buf.getvalue(), content_type="image/png")
        response["Access-Control-Allow-Origin"] = "*"
        response["Access-Control-Expose-Headers"] = "*"
        response["Content-Length"] = str(len(response.content))
        response["Plotter-State"] = str(plotter_state["state"])
        response["Plotter-Position"] = json.dumps(dict(zip("xyz", plotter_state["position"])))
        response["Targeting-Position"] = json.dumps(dict(zip("xyz", plotter_state["targeting"])))

        yield response


class NirsPlotterConfig(AppConfig):
    name = 'nirs_plotter'

    # Settings.
    max_workspace_size_mm = {
        "x": 200,
        "y": 100
    }
    workspace_size_mm = dict(max_workspace_size_mm)

    pixel_size_mm = {
        "x": 2,
        "y": 2
    }
    output_resolution = {
        "x": int(np.floor(workspace_size_mm["x"] / pixel_size_mm["x"])),
        "y": int(np.floor(workspace_size_mm["y"] / pixel_size_mm["y"]))
    }

    # Initialize a NIRS instance.
    nirs = NIRS()
    nirs.set_hibernate(False)

    # Connect to XY-plotter.
    serial_port = None
    dev_list = comports()
    for dev in dev_list:
        serial_port = serial.Serial(port=dev.device, baudrate=115200, bytesize=8, parity='N', stopbits=1, timeout=1)

    if serial_port is None:
        # Error.
        print("Failed to connect to plotter.")
        exit(-1)
    else:
        serial_port.write("$X\n".encode())

    # Machine state.
    plotter_state = {
        "state": "",
        "position": [0.0, 0.0, 0.0],
        "targeting": [0.0, 0.0, 0.0],
    }

    # Start serial port threading.
    serial_buffer = queue.Queue(maxsize=100)
    serial_lock = threading.Lock()
    serial_read_thread = threading.Thread(
        target=serial_reader, args=(serial_port, serial_lock, serial_buffer, plotter_state))
    serial_read_thread.start()

    # Prepare plotter figure.
    fig = None
    ax = None

    # Image generator lock.
    generator_lock = threading.Lock()


def set_new_pixel_size_mm(new_pixel_size_mm):
    """Set new pixel size, adjust work space accordingly."""

    # Compute new output resolution and work space size.
    new_output_resolution = {
        "x": int(np.floor(NirsPlotterConfig.max_workspace_size_mm["x"] / new_pixel_size_mm["x"])),
        "y": int(np.floor(NirsPlotterConfig.max_workspace_size_mm["y"] / new_pixel_size_mm["y"]))
    }
    new_workspace_size_mm = {
        "x": new_pixel_size_mm["x"] * new_output_resolution["x"],
        "y": new_pixel_size_mm["y"] * new_output_resolution["y"]
    }

    # Update parameters.
    base_size = 10
    fig, ax = plt.subplots(figsize=(base_size, new_workspace_size_mm["y"] / new_workspace_size_mm["x"] * base_size),
                           dpi=100)
    fig.subplots_adjust(left=0.04, right=0.93, bottom=0.04, top=0.93, wspace=0.0, hspace=0.0)
    # fig.subplots_adjust(left=0.00, right=1.0, bottom=0.00, top=1.0, wspace=0.0, hspace=0.0)
    ax.set_xlim(0, new_workspace_size_mm["x"])
    ax.set_ylim(0, new_workspace_size_mm["y"])

    # Adjust border line size.
    line_width = 1.0
    for spine in ax.spines.values():
        spine.set_linewidth(line_width)

    # Ticks and grid.
    grid_flag = False
    x_ticks_major = np.arange(0, new_workspace_size_mm["x"] + 0.1, new_workspace_size_mm["x"] * 5)
    x_ticks_minor = np.arange(0, new_workspace_size_mm["x"] + 0.1, new_workspace_size_mm["x"])
    y_ticks_major = np.flip(np.arange(0, new_workspace_size_mm["y"] + 0.1, new_workspace_size_mm["y"] * 5))
    y_ticks_minor = np.flip(np.arange(0, new_workspace_size_mm["y"] + 0.1, new_workspace_size_mm["y"]))
    ax.set_xticks(x_ticks_major, minor=False)
    ax.set_xticks(x_ticks_minor, minor=True)
    ax.set_yticks(y_ticks_major, minor=False)
    ax.set_yticks(y_ticks_minor, minor=True)
    ax.set_frame_on(True)
    ax.invert_yaxis()
    ax.get_xaxis().tick_top()
    # fig.set_tight_layout(True)
    # Turn grid on/off.
    if grid_flag:
        ax.grid(True, which="major", axis="both", alpha=1.0, color="w", linewidth=1)
        ax.grid(True, which="minor", axis="both", alpha=1.0, color="w", linewidth=1)
    else:
        ax.grid(False, which="major", axis="both")
        ax.grid(False, which="minor", axis="both")

    # Interpreted image test.
    # scanned_image = NIRSImage(new_output_resolution["x"], new_output_resolution["y"],
    #                           new_pixel_size_mm["x"], new_pixel_size_mm["y"], fig, ax)

    # Constructing metadata.
    width, height = fig.canvas.get_width_height()
    original_point_coordinates = list(ax.transData.transform((0., 0.)))
    maximal_coordinates = list(ax.transData.transform((new_workspace_size_mm["x"], new_workspace_size_mm["y"])))

    # Convert to display coordinate system.
    original_point_coordinates[1] = height - original_point_coordinates[1]
    maximal_coordinates[1] = height - maximal_coordinates[1]

    x_factor = abs(maximal_coordinates[0] - original_point_coordinates[0]) / new_workspace_size_mm["x"]
    y_factor = abs(maximal_coordinates[1] - original_point_coordinates[1]) / new_workspace_size_mm["y"]
    metadata = {
        "workspace_size_mm": new_workspace_size_mm,
        "pixel_size_mm": new_pixel_size_mm,
        "output_resolution": new_output_resolution,
        "original_point_coordinates": {
            "x": original_point_coordinates[0],
            "y": original_point_coordinates[1]
        },
        "xy_factors": {
            "x": x_factor,
            "y": y_factor
        }
    }

    # Image map and generator.
    # image = np.random.random((output_size["y"], output_size["x"]))
    # image = np.ones(shape=(output_resolution["y"], output_resolution["x"]), dtype=float)
    extent = (0, new_workspace_size_mm["x"], new_workspace_size_mm["y"], 0)

    # Save parameters.
    NirsPlotterConfig.pixel_size_mm = new_pixel_size_mm
    NirsPlotterConfig.output_resolution = new_output_resolution
    NirsPlotterConfig.workspace_size_mm = new_workspace_size_mm
    NirsPlotterConfig.metadata = metadata
    NirsPlotterConfig.fig = fig
    NirsPlotterConfig.ax = ax
    NirsPlotterConfig.scanned_image = NIRSImage(
            NirsPlotterConfig.output_resolution["x"],
            NirsPlotterConfig.output_resolution["y"],
            NirsPlotterConfig.pixel_size_mm["x"],
            NirsPlotterConfig.pixel_size_mm["y"],
            NirsPlotterConfig.fig,
            NirsPlotterConfig.ax)
    NirsPlotterConfig.extent = extent
    NirsPlotterConfig.image_response_generator = construct_plotter_image_response(
        NirsPlotterConfig.fig,
        NirsPlotterConfig.ax,
        NirsPlotterConfig.scanned_image,
        NirsPlotterConfig.extent,
        NirsPlotterConfig.plotter_state)


# Init parameters.
set_new_pixel_size_mm(NirsPlotterConfig.pixel_size_mm)

