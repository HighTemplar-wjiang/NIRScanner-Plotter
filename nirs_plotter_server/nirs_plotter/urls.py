from django.urls import path

from . import views

urlpatterns = [
    path('plotter/', views.plotter_index, name="index"),
    path('plotter/buffer', views.get_serial_buffer, name='buffer'),
    path('plotter/state', views.get_plotter_state, name='state'),
    path('plotter/write', views.write_plotter, name="write"),
    path('plotter/image', views.get_plotter_map, name="image"),
    path('plotter/move', views.plotter_movement, name="move"),
    path('plotter/pixelsize', views.set_pixel_size, name="pixelsize"),
    path('plotter/metadata', views.get_plotter_metadata, name="metadata"),
    path('plotter/unlock', views.unlock_plotter, name="unlock"),
    path('plotter/zero', views.set_zero_point, name="zero"),
    path('nirs/clearerror', views.clear_nirs_error_status, name="clearerror"),
    path('nirs/scan', views.nirs_scan, name="scan"),
    path('nirs/lamp', views.nirs_set_lamp_on_off, name="lamp"),
    path('nirs/setdata', views.nirs_set_data, name="setdata")
]
