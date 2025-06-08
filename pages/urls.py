# pages/urls.py

from django.urls import path

# Home and general views
from .views.home_views import home_page_view
from .views.faq_views import faq_view

# Training course related views
from .views.training_course_views import lesion_tracing_practice_view, create_level_view, lesion_tracing_completion_view

# Case report related views
from .views.case_report_views import case_report_library_view, case_report_detail_view, get_case_reports_json, import_case_report, edit_case_report_view, delete_case_report_view, lookup_case_report

# Subject and lesion related views
from .views.lesion_subject_views import edit_subject_view, add_subject_to_case_report, subject_detail_view, lesion_library_view, get_lesion_subjects_json, add_dangling_subject

# Symptom hierarchy related views
from .views.symptom_views import symptom_library_view, symptom_detail_view, domain_detail_view, subdomain_detail_view, get_symptoms_json, import_group_level_map_to_symptom, import_group_level_map_to_subdomain, import_group_level_map_to_domain, edit_symptom, edit_subdomain, edit_domain, manage_group_level_maps_symptom, manage_group_level_maps_subdomain, manage_group_level_maps_domain, add_new_symptom, get_subdomains

# Location views
from .views.locations_views import locations_view

# Analyze views
from .views.analyze_views import analyze_view, decode_task_status, decode_results_view, voxel_to_nifti_view, analyze_voxels_view, analyze_progress_view, analyze_task_status, analyze_results_view

urlpatterns = [
    # Home and general pages
    path("", home_page_view, name="home"),
    path("faq/", faq_view, name="faq"),

    # Training course paths
    path('create_levels/', create_level_view, name='create_level'),
    path("lesion_tracing_practice/", lesion_tracing_practice_view, name="lesion_tracing_practice"),
    path("lesion_tracing_practice/<int:level_id>/", lesion_tracing_practice_view, name="lesion_tracing_practice"),
    path("lesion_tracing_completion/", lesion_tracing_completion_view, name="lesion_tracing_completion"),

    # Case report paths
    path("library/", case_report_library_view, name="case_report_library"),
    path("case_reports/<int:case_report_id>/", case_report_detail_view, name="case_report_detail"),
    path("edit_case_reports/<int:case_report_id>/", edit_case_report_view, name="edit_case_report"),
    path('case-reports/<int:case_report_id>/delete/', delete_case_report_view, name='delete_case_report'),

    path("import_case_report/", import_case_report, name="import_case_report"),
    path('api/case-reports/', get_case_reports_json, name='get_case_reports_json'),
    path('api/lookup-case-report/', lookup_case_report, name='lookup_case_report'),

    # Subject and lesion paths
    path('lesion_library/', lesion_library_view, name='lesion_library'),
    path('subjects/<int:subject_id>/', subject_detail_view, name='subject_detail'),
    path('subjects/<int:subject_id>/edit/', edit_subject_view, name='edit_subject'),
    path('case_reports/<int:case_report_id>/add_subject/', add_subject_to_case_report, name='add_subject_to_case_report'),
    path('add_dangling_subject/', add_dangling_subject, name='add_dangling_subject'),
    path('api/lesion-subjects/', get_lesion_subjects_json, name='get_lesion_subjects_json'),

    # Symptom hierarchy paths
    path("symptoms/", symptom_library_view, name="symptom_library"),
    path("symptoms/<int:pk>/", symptom_detail_view, name="symptom_detail"),
    path("subdomains/<int:pk>/", subdomain_detail_view, name="subdomain_detail"),
    path("domains/<int:pk>/", domain_detail_view, name="domain_detail"),
    path('symptoms/<int:pk>/edit/', edit_symptom, name='edit_symptom'),
    path('subdomains/<int:pk>/edit/', edit_subdomain, name='edit_subdomain'),
    path('domains/<int:pk>/edit/', edit_domain, name='edit_domain'),
    path('api/symptoms/', get_symptoms_json, name='get_symptoms_json'),
    path('api/subdomains/', get_subdomains, name='get_subdomains'),
    path('add_symptom/', add_new_symptom, name='add_symptom'),

    # Group level map management
    path("symptoms/<int:pk>/import_group_level_map/", import_group_level_map_to_symptom, name="import_group_level_map_symptom"),
    path("subdomains/<int:pk>/import_group_level_map/", import_group_level_map_to_subdomain, name="import_group_level_map_subdomain"),
    path("domains/<int:pk>/import_group_level_map/", import_group_level_map_to_domain, name="import_group_level_map_domain"),
    path("symptoms/<int:pk>/manage_group_level_maps/", manage_group_level_maps_symptom, name="manage_group_level_maps_symptom"),
    path("subdomains/<int:pk>/manage_group_level_maps/", manage_group_level_maps_subdomain, name="manage_group_level_maps_subdomain"),
    path("domains/<int:pk>/manage_group_level_maps/", manage_group_level_maps_domain, name="manage_group_level_maps_domain"),

    # Location and decode paths
    path("locations/", locations_view, name="locations"),
    path("analyze/", analyze_view, name="analyze"),
    path('analyze_voxels/', analyze_voxels_view, name='analyze_voxels'),
    path('analyze_progress/', analyze_progress_view, name='analyze_progress'),
    path('analyze_task_status/<str:task_id>/', analyze_task_status, name='analyze_task_status'),
    path('analyze_results/', analyze_results_view, name='analyze_results'),
    path('decode/status/<task_id>/', decode_task_status, name='decode_task_status'),
    path('decode/results/', decode_results_view, name='decode_results'),
    path('voxel_to_nifti/', voxel_to_nifti_view, name='voxel_to_nifti'),

]