# pages/views/home_views.py

from django.shortcuts import render
from pages.models import Symptom, GroupLevelMapFile, Subject


def home_page_view(request):
    # Fetch all symptoms that have associated GroupLevelMapFile with statistic_type 'percent_overlap'
    symptoms_with_maps = Symptom.objects.filter(
        group_level_map_files__statistic_type__code='percent_overlap'
    ).distinct()

    if not symptoms_with_maps.exists():
        # Handle the case where no symptoms are found
        context = {
            'error': 'No symptoms found',
            'title': 'LesionBank - Home'
        }
        return render(request, 'pages/home.html', context)
    
    # Pick a random symptom
    symptom = symptoms_with_maps.order_by('?').first()

    # Find count of subjects with this symptom
    subject_count = Subject.objects.filter(symptoms=symptom).count()

    # Fetch associated Group Level Map Files
    print("symptom: ", symptom)
    group_level_map_file = GroupLevelMapFile.objects.filter(
        symptom=symptom,
        statistic_type__code='percent_overlap',
        filetype__in=['nii.gz', 'nii']
    ).first()
    
    context = {
        'symptom': symptom,
        'subject_count': subject_count,
        'group_level_map_file': group_level_map_file,
        'title': 'LesionBank - Home'
    }
    return render(request, 'pages/home.html', context)