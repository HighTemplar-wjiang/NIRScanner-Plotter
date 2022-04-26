import os
import json
import time
import numpy as np

from nirs_plotter_server.settings import BASE_DIR
from django.shortcuts import render_to_response
from django.http import JsonResponse, HttpResponse, HttpResponseBadRequest
from django.views.decorators.csrf import csrf_exempt
from .apps import NirsPlotterConfig, set_new_pixel_size_mm
from .utils import NIRSImage


def plotter_index(request):
    """index"""
    return render_to_response("index.html")


def get_serial_buffer(request):
    """Get all current serial buffer data and clear the buffer."""
    with NirsPlotterConfig.serial_lock:
        buffer = list(NirsPlotterConfig.serial_buffer.queue)
        NirsPlotterConfig.serial_buffer.queue.clear()
    return JsonResponse({
        "data": buffer
    })


def get_plotter_map(request):
    """Draw plotter figure and return the image."""
    with NirsPlotterConfig.generator_lock:
        response = next(NirsPlotterConfig.image_response_generator)
    return response


def get_plotter_state(request):
    """Get the plotter state and position."""
    with NirsPlotterConfig.serial_lock:
        return JsonResponse(NirsPlotterConfig.plotter_state)


def get_plotter_metadata(request):
    """Return metadata about the plotter."""
    response = JsonResponse(NirsPlotterConfig.metadata)
    response["Access-Control-Allow-Origin"] = "*"
    response["Access-Control-Expose-Headers"] = "*"
    return response


@csrf_exempt
def write_plotter(request):
    """Write a command to plotter."""
    if request.method == "POST":
        # Json decode.
        try:
            data = json.loads(request.body)
        except json.decoder.JSONDecodeError as e:
            return HttpResponseBadRequest("JSON format error.")

        # Get data fields.
        command = data["command"].encode()

        # Execute.
        with NirsPlotterConfig.serial_lock:
            NirsPlotterConfig.serial_port.write(command)
        return HttpResponse("")
    else:
        return HttpResponseBadRequest("Only POST method is accepted.")


def unlock_plotter(request):
    """Unlock the plotter."""
    with NirsPlotterConfig.serial_lock:
        NirsPlotterConfig.serial_port.write("$X\n".encode())

    response = HttpResponse("")
    response["Access-Control-Allow-Origin"] = "*"
    return response


@csrf_exempt
def set_pixel_size(request):
    """Set pixel size in millimeter."""
    if request.method == "POST":
        try:
            data = json.loads(request.body)
        except json.decoder.JSONDecodeError as e:
            return HttpResponseBadRequest("JSON format error.")

        # Get data.
        new_value = data["pixel_size"]

        # Sanity check.
        if ("x" in new_value) and ("y" in new_value):
            # Set new value.
            set_new_pixel_size_mm(new_value)

            response = HttpResponse("")
            response["Access-Control-Allow-Origin"] = "*"
            return response
        else:
            return HttpResponseBadRequest("JSON format error.")
    else:
        return HttpResponseBadRequest("Only POST method is accepted.")

@csrf_exempt
def set_zero_point(request):
    """Set current position as zero position."""
    if request.method != "GET":
        try:
            data = json.loads(request.body)
        except json.decoder.JSONDecodeError as e:
            return HttpResponseBadRequest("JSON format error.")

        # Get flags.
        x_flag = data["x_flag"]
        y_flag = data["y_flag"]
        z_flag = data["z_flag"]

        # Construct command.
        command = "G10 P1 L20"
        if x_flag:
            command += " X0"
        if y_flag:
            command += " Y0"
        if z_flag:
            command += " Z0"
        command += "\n"

        with NirsPlotterConfig.serial_lock:
            NirsPlotterConfig.serial_port.write(command.encode())
        response = HttpResponse("")
        response["Access-Control-Allow-Origin"] = "*"
        return response
    else:
        return HttpResponseBadRequest("Only POST method is accepted.")


@csrf_exempt
def plotter_movement(request):
    """Move plotter to specified position."""
    if request.method == "POST":
        # Json decode.
        try:
            data = json.loads(request.body)
        except json.decoder.JSONDecodeError as e:
            return HttpResponseBadRequest("JSON format error.")

        # Get data fields.
        move_type = data["move_type"]
        position = data["position"]
        feed = data["feed"]

        # Construct G-code.
        relative_point = [0, 0, 0]
        if move_type == "incremental":
            command = "G91 G1 G21 "
            # Wait until idle if incremental movement.
            while True:
                with NirsPlotterConfig.serial_lock:
                    if NirsPlotterConfig.plotter_state["state"].lower() == "idle":
                        relative_point = NirsPlotterConfig.plotter_state["position"]
                        break
                    else:
                        time.sleep(0.2)

        elif move_type == "absolute":
            command = "G90 G1 G21 "
        else:
            return HttpResponseBadRequest(
                "Unknown movement type: {}. Acceptable types: incremental, absolute.".format(move_type))

        if "x" in position:
            command += "X{:.1f} ".format(position["x"])
            NirsPlotterConfig.plotter_state["targeting"][0] = position["x"] + relative_point[0]
        if "y" in position:
            command += "Y{:.1f} ".format(position["y"])
            NirsPlotterConfig.plotter_state["targeting"][1] = position["y"] + relative_point[1]
        if "z" in position:
            command += "Z{:.1f} ".format(position["z"])
            NirsPlotterConfig.plotter_state["targeting"][2] = position["z"] + relative_point[2]
        command += "F{:d}\n".format(feed)

        # Execute.
        with NirsPlotterConfig.serial_lock:
            NirsPlotterConfig.serial_port.write(command.encode())

        response = HttpResponse("")
        response["Access-Control-Allow-Origin"] = "*"
        return response
    else:
        return HttpResponseBadRequest("Only POST method is accepted.")


@csrf_exempt
def clear_nirs_error_status(request):
    """Reset NIRS error status."""
    NirsPlotterConfig.nirs.clear_error_status()
    return HttpResponse("")


@csrf_exempt
def nirs_scan(request):
    """Take a NIRS scan and return the spectrum."""
    if request.method == "POST":
        try:
            data = json.loads(request.body)
        except json.decoder.JSONDecodeError as e:
            return HttpResponseBadRequest("JSON format error.")

        # Clear error status.
        # NirsPlotterConfig.nirs.clear_error_status()

        num_repeats = data["num_repeats"]
        # Set PGA gain if required.
        if "pga_gain" in data:
            pga_gain = int(data["pga_gain"])
            NirsPlotterConfig.nirs.set_pga_gain(pga_gain)

        # Scan.
        NirsPlotterConfig.nirs.scan(num_repeats)

        # Get data.
        results = NirsPlotterConfig.nirs.get_scan_results()

        # Update image.
        wx, wy, _ = NirsPlotterConfig.plotter_state["position"]
        ix, iy = NirsPlotterConfig.scanned_image._workcoord2imagecoord(wx, wy)
        NirsPlotterConfig.scanned_image.set_pixel_data(ix, iy, results)
        NirsPlotterConfig.scanned_image.parse_all_pixels()

        return JsonResponse({
            "data": results,
        })

    else:
        return HttpResponseBadRequest("Only POST method is accepted.")


@csrf_exempt
def nirs_set_lamp_on_off(request):
    """Keep the lamp on / off."""
    if request.method == "POST":
        try:
            data = json.loads(request.body)
        except json.decoder.JSONDecodeError as e:
            return HttpResponseBadRequest("JSON format error.")

        new_value = int(data["keep_lamp_on_off"])

        # Set lamp on / off.
        NirsPlotterConfig.nirs.set_lamp_on_off(new_value)

        return HttpResponse("")

    else:
        return HttpResponseBadRequest("Only POST method is accepted.")


@csrf_exempt
def nirs_set_data(request):
    """Set data for current pixel for drawing."""
    if request.method == "POST":
        try:
            data = json.loads(request.body)
        except json.decoder.JSONDecodeError as e:
            return HttpResponseBadRequest("JSON format error.")

        # Get spectrum.
        scan_data = data["data"]
        ix, iy = data["ix"], data["iy"]

        # Update image.
        NirsPlotterConfig.scanned_image.set_pixel_data(ix, iy, scan_data)
        NirsPlotterConfig.scanned_image.parse_all_pixels()

        return HttpResponse("")

    else:
        return HttpResponseBadRequest("Only POST method is accepted.")



