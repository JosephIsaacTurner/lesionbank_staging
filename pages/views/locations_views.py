# pages/views/locations_views.py

from django.shortcuts import render


def locations_view(request):
    x = request.GET.get('x', '0')
    y = request.GET.get('y', '0')
    z = request.GET.get('z', '0')
    map_type = request.GET.get('map_type', 'roi')

    context = {
        'page_name': 'Locations',
        'title': 'Lesion Library',
        'x': x,
        'y': y,
        'z': z,
        'map_type': map_type,
    }
    return render(request, 'pages/locations.html', context)