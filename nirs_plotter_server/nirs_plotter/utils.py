# utils.py
# Signal processing, machine learning, etc.

import os
import pickle
from nirs_plotter_server.settings import BASE_DIR
import numpy as np
from scipy.signal import savgol_filter, detrend, decimate
import matplotlib as mlp
import matplotlib.pyplot as plt

mlp.use("Agg")


class NIRSImage:
    """Class for process and store recovered image."""

    def __init__(self, width, height, pixel_size_mm_x, pixel_size_mm_y, fig, ax, *,
                 low_percentile=2, high_percentile=98):
        """Init instance."""

        self.shape = (width, height)
        self.fig = fig
        self.ax = ax

        # Work coordinates.
        self.wx_min, self.wx_max = 0, 0
        self.wy_min, self.wy_max = 0, 0

        # Display coordinates.
        self.dx_min, self.dy_min = 0, 0
        self.dx_max, self.dy_max = 0, 0

        # Pixel size in millimeter.
        self.pixel_size_mm_x, self.pixel_size_mm_y = 0, 0

        # Init metadata.
        self.set_figure(pixel_size_mm_x, pixel_size_mm_y, fig, ax)

        # Allocate memory.
        self.img = np.ones(self.shape) * -0xFFFFFFFF
        self.scan_flags = np.zeros(self.shape, dtype=bool)
        self.change_flags = np.zeros(self.shape, dtype=bool)
        self.all_data_raw = np.empty(self.shape, dtype=object)
        self.all_data_processed = np.empty(self.shape, dtype=object)

        # # Load reference spectrum.
        # with open(os.path.join(BASE_DIR, "../data/reference/reference_spectrum"), "rb") as f:
        #     reference_data = pickle.load(f)
        #     self.wavelength_list = reference_data["wavelength_list"]
        #     self.selected_indexes = reference_data["selected_indexes"]
        #     self.reference_spectrum = reference_data["reference_spectrum"]

        # # Signal parameters.
        # # self._target_wavelength = 1142.79
        # self._target_wavelength = 1302.71
        # self._moving_average_window_size = 11
        # self._decimal_factor = 1

        # # Pre-calculate wavelength list after processing.
        # self.wavelength_list_processed = self.wavelength_list[self.selected_indexes]
        # self.wavelength_list_processed = self.wavelength_list_processed[::self._decimal_factor]

        # # Pre-calculate index of target wavelength.
        # self._idx_target_wavelength = np.nanargmin(np.abs(self.wavelength_list_processed - self._target_wavelength))

        # Image parameters.
        # Normalization percentile range.
        self._low_percentile = low_percentile
        self._high_percentile = high_percentile

    def set_figure(self, pixel_size_mm_x, pixel_size_mm_y, fig, ax):
        """Get xy limits, min/max coordinates, etc."""

        # Validate parameters.
        wx_min = np.min(ax.get_xlim())
        wx_max = np.max(ax.get_xlim())
        wy_min = np.min(ax.get_ylim())
        wy_max = np.max(ax.get_ylim())

        # Sanity check.
        if not (np.isclose(pixel_size_mm_x * self.shape[0], wx_max - wx_min, rtol=1e-05, atol=1e-08)
                and np.isclose(pixel_size_mm_y * self.shape[1], wy_max - wy_min, rtol=1e-05, atol=1e-08)):
            print("[ERROR]: Figure size and pixel size are unmatched.")
            return

        # Set figure.
        self.fig = fig
        self.ax = ax

        # Set pixel size.
        self.pixel_size_mm_x, self.pixel_size_mm_y = pixel_size_mm_x, pixel_size_mm_y

        # Workspace limits.
        self.wx_min, self.wx_max = wx_min, wx_max
        self.wy_min, self.wy_max = wy_min, wy_max

        # Display limits.
        width, height = fig.canvas.get_width_height()
        self.dx_min, self.dy_min = list(ax.transData.transform((0., 0.)))
        self.dx_max, self.dy_max = list(ax.transData.transform((self.wx_max, self.wy_max)))

        # Convert to display coordinate system.
        self.dy_min = height - self.dy_min
        self.dy_max = height - self.dy_max

    def _displaycoord2workcoord(self, dx, dy):
        """Convert display coordinates to work coordinates."""
        width, height = self.fig.canvas.get_width_height()

        # Convert to down-to-up.
        dy = height - dy

        # Convert to work coordinates.
        wx, wy = list(self.ax.transData.inverted().transform(dx, dy))

        return wx, wy

    def _workcoord2displaycoord(self, wx, wy):
        """Convert work coordinates to display coordinates."""
        width, height = self.fig.canvas.get_width_height()
        dx, dy = list(self.ax.transData.transform(wx, wy))

        # Convert to up-to-down.
        dy = height - dy

        return dx, dy

    def _workcoord2imagecoord(self, wx, wy):
        """Convert work coordinates to image coordinates."""
        ix, iy = (np.floor((wx - self.wx_min + 0.1) / self.pixel_size_mm_x),
                  np.floor((wy - self.wy_min + 0.1) / self.pixel_size_mm_y))

        print(ix)
        print(iy)

        return int(ix), int(iy)

    def _imagecoord2workcoord(self, ix, iy):
        """Convert image coordinates to work coordinates."""
        wx, wy = (ix + 0.5) * self.pixel_size_mm_x, (iy + 0.5) * self.pixel_size_mm_y

        return wx, wy

    def _displaycoord2imagecoord(self, dx, dy):
        """Convert display coordinates to image coordinates."""
        return self._workcoord2imagecoord(*self._displaycoord2workcoord(dx, dy))

    def _imagecoord2displaycoord(self, ix, iy):
        """Convert image coordinates to display coordinates."""
        return self._workcoord2displaycoord(*self._imagecoord2workcoord(ix, iy))

    @staticmethod
    def _invalid_to_nearest(signal, copy=True):
        """ Repleace invalid values (nan/inf) to nearest valid values. """
        # Init.
        idx_left_valid = None
        idx_right_valid = None
        normal_state = np.isfinite(signal[0])

        if copy:
            new_signal = np.copy(signal)
        else:
            new_signal = signal

        for idx, s in enumerate(signal):
            # Looking for nan/inf.
            if normal_state & (~np.isfinite(s)):
                # Nan segment starts.
                normal_state = False
                idx_left_valid = idx - 1
            elif (~normal_state) & np.isfinite(s):
                # Nan segment ends.
                normal_state = True
                idx_right_valid = idx

                # Fill-in non-valid segment.
                if idx_left_valid is None:
                    # Head-nan process.
                    new_signal[:idx_right_valid] = signal[idx_right_valid]
                else:
                    # Find mid-point.
                    idx_mid = int(np.ceil((idx_right_valid + idx_left_valid) / 2))

                    # Fill-in, mid-point = right_valid
                    new_signal[idx_left_valid + 1:idx_mid] = signal[idx_left_valid]
                    new_signal[idx_mid:idx_right_valid] = signal[idx_right_valid]

        # Tail process.
        if not normal_state:
            new_signal[idx_left_valid + 1:] = signal[idx_left_valid]

        return new_signal

    def normalize_array(self, input_arr, revert=True, mask=None):
        """ Robust normalization of an array. """
        # Create a copy of input to prevent manipulation.
        input_arr = np.array(np.copy(input_arr))

        # Find percentiles if specified.
        if mask is not None:
            min_edge, max_edge = np.percentile(input_arr[mask], [self._low_percentile, self._high_percentile])
        else:
            min_edge, max_edge = np.percentile(input_arr, [self._low_percentile, self._high_percentile])

        # Set min-max to percentiles if specified.
        input_arr[input_arr < min_edge] = min_edge
        input_arr[input_arr > max_edge] = max_edge

        # Find min max values.
        min_value = np.min(input_arr)
        max_value = np.max(input_arr)
        if min_value == max_value:
            arr_normalized = np.zeros(input_arr.shape)
        else:
            arr_normalized = (input_arr - min_value) / (max_value - min_value)

        if revert:
            arr_normalized = 1.0 - arr_normalized  # Revert information pixel to 1.

        return arr_normalized

    @staticmethod
    def _moving_average(signal, N):
        from scipy.ndimage.filters import uniform_filter1d
        """ Moving average, nearest-padding, left-and-right. """
        return uniform_filter1d(signal, size=N, mode="reflect")

    def _preprocess(self, data_raw):
        """Pre-process raw signals."""

        # Get raw spectrum.
        raw_intensity = np.array(data_raw["intensity"])
        raw_reference = np.array(data_raw["reference"])
        processed = raw_intensity

        # Add extra pre-processing steps here.

        return np.array(processed)

    def set_pixel_data(self, idx_x, idx_y, data_raw):
        """Save and pre-process a spectrum for a pixel."""
        self.all_data_raw[idx_x, idx_y] = data_raw
        self.all_data_processed[idx_x, idx_y] = self._preprocess(data_raw)
        self.change_flags[idx_x, idx_y] = True
        self.scan_flags[idx_x, idx_y] = True

    def parse_all_pixels(self):
        """Parse all stored spectra into pixels."""
        # TODO: Replace model.

        for idx_y in range(self.all_data_processed.shape[1]):
            for idx_x in range(self.all_data_processed.shape[0]):

                if self.change_flags[idx_x, idx_y]:
                    data_processed = self.all_data_processed[idx_x, idx_y]

                    # Get pixel data.
                    pixel_data = np.mean(data_processed)
                    print("{}, {}: {}".format(idx_x, idx_y, pixel_data))

                    self.img[idx_x, idx_y] = pixel_data
                    self.change_flags[idx_x, idx_y] = False

    def get_image(self):
        """Return image array.
           Note: the coordinates should be transposed.
           numpy coordinates:
           .-------> y
           |
           |
           |
           |
           v
           x

           Display coordinates:
           .-------> x
           |
           |
           |
           |
           v
           y
        """
        return self.img.transpose()

    def train_model(self):
        pass
