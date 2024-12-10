# pages/views/lesion_subject_views.py

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.utils.timezone import now
from django.contrib.auth.decorators import login_required
from django.urls import reverse
from django.utils.html import format_html
from django.db.models import Q, Min, Case, When, Value, FloatField
from django.core.paginator import Paginator, PageNotAnInteger, EmptyPage
from django.http import JsonResponse
from urllib.parse import quote 
from pages.forms import SubjectForm
from pages.models import CaseReport, Subject
from accounts.models import CustomUser as User
from sqlalchemy_utils.db_utils import get_files_at_xyz
from sqlalchemy_utils.db_session import get_session
from pages.decorators import user_can_edit_subject


def is_staff_user(user):
    """Check if user has staff or superuser privileges."""
    return user.is_staff or user.is_superuser


def get_lesion_subjects_json(request):
    """
    Return JSON response containing filtered and paginated lesion subjects data.
    Handles spatial filtering, search, and ordering of subjects based on request parameters.
    """
    # Pagination parameters
    draw = int(request.GET.get('draw', 1))
    start = int(request.GET.get('start', 0))
    length = int(request.GET.get('length', 100))

    # Filter parameters
    sex_name = request.GET.get('sex_name')
    cause_name = request.GET.get('cause_name')
    symptom_name = request.GET.get('symptom_name')
    domain_name = request.GET.get('domain_name')
    subdomain_name = request.GET.get('subdomain_name')
    username = request.GET.get('username')  # New filter parameter

    # Spatial filter parameters
    x = request.GET.get('x')
    y = request.GET.get('y')
    z = request.GET.get('z')
    map_type = request.GET.get('map_type', 'roi')

    # Context parameter to determine the template
    context = request.GET.get('context', 'lesion_library')  # Default to 'lesion_library'

    search_value = request.GET.get('search[value]', '')
    order_column_index = request.GET.get('order[0][column]', '0')
    order_dir = request.GET.get('order[0][dir]', 'asc')

    # Define column_order_map based on context
    if context == 'locations':
        # Column indices for locations.html
        column_order_map = {
            '0': 'value',  # Value column
            '1': 'id',
            '2': 'age',
            '3': 'sex__name',
            '4': 'handedness__name',
            '5': 'cause__name',
            '6': 'min_domain',
            '7': 'min_subdomain',
            '8': 'min_symptom',
        }
        if request.user.is_staff:
            column_order_map['9'] = 'user__username'  # Add username for ordering
    else:
        # Column indices for lesion_library.html
        column_order_map = {}
        col_idx = 0
        if request.user.is_staff:
            column_order_map[str(col_idx)] = 'user__username'
            col_idx += 1
        column_order_map[str(col_idx)] = 'id'
        col_idx += 1
        column_order_map[str(col_idx)] = 'age'
        col_idx += 1
        column_order_map[str(col_idx)] = 'sex__name'
        col_idx += 1
        column_order_map[str(col_idx)] = 'handedness__name'
        col_idx += 1
        column_order_map[str(col_idx)] = 'cause__name'
        col_idx += 1
        column_order_map[str(col_idx)] = 'min_domain'
        col_idx += 1
        column_order_map[str(col_idx)] = 'min_subdomain'
        col_idx += 1
        column_order_map[str(col_idx)] = 'min_symptom'
        col_idx += 1
        # No additional ordering for 'Details', 'ROI', 'Connectivity'

    queryset = Subject.objects.all()
    if not is_staff_user(request.user):
        queryset = queryset.filter(internal_use_only=False)

    # Apply spatial filtering (existing logic)
    if x and y and z:
        try:
            x_int, y_int, z_int = map(int, (x, y, z))
            session = get_session()

            try:
                internal_map_type = map_type.lower()
                roi_results = get_files_at_xyz(x_int, y_int, z_int, internal_map_type, session)
                subject_ids = list(roi_results.keys())

                if subject_ids:
                    when_list = [When(id=subject_id, then=Value(value)) 
                               for subject_id, value in roi_results.items()]
                    queryset = queryset.filter(id__in=subject_ids).annotate(
                        value=Case(*when_list, default=Value(0), output_field=FloatField())
                    ).order_by('-value')
                else:
                    queryset = queryset.none()
            except Exception as e:
                return JsonResponse({'error': f'Error fetching files: {str(e)}'}, status=500)
            finally:
                session.close()
        except ValueError:
            return JsonResponse({'error': 'Invalid coordinate values'}, status=400)

    # Apply filters and collect counts
    filter_counts = {}
    if sex_name:
        queryset = queryset.filter(sex__name=sex_name)
        filter_counts['sexCount'] = queryset.count()
    
    if cause_name:
        queryset = queryset.filter(cause__name=cause_name)
        filter_counts['causeCount'] = queryset.count()

    if username and request.user.is_staff:
        queryset = queryset.filter(user__username=username)
        filter_counts['usernameCount'] = queryset.count()

    if any([symptom_name, domain_name, subdomain_name]):
        base_filter = ~Q(symptoms__internal_use_only=True) if not is_staff_user(request.user) else Q()
        
        if symptom_name:
            queryset = queryset.filter(base_filter & Q(symptoms__name=symptom_name))
            filter_counts['symptomCount'] = queryset.count()
        
        if domain_name:
            queryset = queryset.filter(base_filter & Q(symptoms__domain__name=domain_name))
            filter_counts['domainCount'] = queryset.count()
        
        if subdomain_name:
            queryset = queryset.filter(base_filter & Q(symptoms__subdomain__name=subdomain_name))
            filter_counts['subdomainCount'] = queryset.count()

    # Apply search filter
    if search_value:
        queryset = queryset.filter(
            Q(age__icontains=search_value) |
            Q(nickname__icontains=search_value) |
            Q(sex__name__icontains=search_value) |
            Q(handedness__name__icontains=search_value) |
            Q(cause__name__icontains=search_value) |
            Q(symptoms__name__icontains=search_value) |
            Q(symptoms__domain__name__icontains=search_value) |
            Q(symptoms__subdomain__name__icontains=search_value) |
            Q(user__username__icontains=search_value)  # Include username in search
        ).distinct()

    records_total = Subject.objects.filter(
        internal_use_only=False if not is_staff_user(request.user) else Q()
    ).count()
    records_filtered = queryset.count()

    # Prepare queryset for ordering
    queryset = queryset.annotate(
        min_symptom=Min('symptoms__name'),
        min_domain=Min('symptoms__domain__name'),
        min_subdomain=Min('symptoms__subdomain__name'),
    ).distinct()

    order_column = column_order_map.get(str(order_column_index), 'id')
    if order_dir == 'desc':
        order_column = f'-{order_column}'

    if not (x and y and z):
        queryset = queryset.order_by(order_column)

    # Paginate results
    paginator = Paginator(queryset, length)
    page_number = (start // length) + 1
    try:
        subjects = paginator.page(page_number)
    except (PageNotAnInteger, EmptyPage):
        subjects = paginator.page(1)

    # Prepare response data
    data = []
    for subject in subjects:
        symptoms_filter = Q() if is_staff_user(request.user) else Q(internal_use_only=False)
        symptoms = set(subject.symptoms.filter(symptoms_filter).values_list('name', flat=True))
        domains = set(subject.symptoms.filter(symptoms_filter).values_list('domain__name', flat=True))
        subdomains = set(subject.symptoms.filter(symptoms_filter).values_list('subdomain__name', flat=True))

        # Generate HTML links
        base_url = reverse('lesion_library')
        symptom_links = [f'<a href="{base_url}?symptom_name={quote(s)}">{s}</a>' for s in symptoms]
        domain_links = [f'<a href="{base_url}?domain_name={quote(d)}">{d}</a>' for d in domains if d]
        subdomain_links = [f'<a href="{base_url}?subdomain_name={quote(s)}">{s}</a>' for s in subdomains if s]

        roi_file = subject.roi_files.filter(path__regex=r'\.nii(?:\.gz)?$').first()
        connectivity_file = subject.connectivity_files.filter(path__regex=r'\.nii(?:\.gz)?$').first()

        data_item = {
            'value': getattr(subject, 'value', None) if context == 'locations' else '',  # Only for locations
            'id': subject.id,
            'age': subject.age or '',
            'sex': subject.sex.name if subject.sex else '',
            'handedness': subject.handedness.name if subject.handedness else '',
            'cause': subject.cause.name if subject.cause else '',
            'min_domain': ', '.join(domain_links),
            'min_subdomain': ', '.join(subdomain_links),
            'min_symptom': ', '.join(symptom_links),
            'details_url': reverse('subject_detail', args=[subject.id]),
            'roi_file_url': roi_file.path.url if roi_file else '',
            'connectivity_file_url': connectivity_file.path.url if connectivity_file else '',
            'created_by': subject.user.username if request.user.is_staff and subject.user else '',
        }

        if context == 'lesion_library' and request.user.is_staff:
            # Construct the URL with existing filters and the selected username
            # Preserve existing GET parameters except 'username'
            query_params = request.GET.copy()
            query_params['username'] = subject.user.username
            filter_url = f"{reverse('lesion_library')}?{query_params.urlencode()}"
            data_item['created_by'] = f'<a href="{filter_url}">{subject.user.username}</a>'
        
        data.append(data_item)

    response_data = {
        'draw': draw,
        'recordsTotal': records_total,
        'recordsFiltered': records_filtered,
        'data': data,
        **filter_counts
    }

    return JsonResponse(response_data)


def lesion_library_view(request):
    """Render the lesion library page with filter parameters."""
    context = {
        'title': 'Lesion Library',
        'page_name': 'lesion_library',
        'sex_name': request.GET.get('sex_name'),
        'cause_name': request.GET.get('cause_name'),
        'symptom_name': request.GET.get('symptom_name'),
        'domain_name': request.GET.get('domain_name'),
        'subdomain_name': request.GET.get('subdomain_name'),
        'username': request.GET.get('username'),  # Add username to context
        'user_list': User.objects.filter(subject__isnull=False).distinct(),  # List of users who have created subjects
        'sex_choices': Subject.objects.values_list('sex__name', flat=True).distinct(),
        'cause_choices': Subject.objects.values_list('cause__name', flat=True).distinct(),
        'domain_choices': Subject.objects.values_list('symptoms__domain__name', flat=True).distinct(),
        'subdomain_choices': Subject.objects.values_list('symptoms__subdomain__name', flat=True).distinct(),
        'symptom_choices': Subject.objects.values_list('symptoms__name', flat=True).distinct(),
    }
    return render(request, 'pages/lesion_library.html', context)


@login_required
def add_dangling_subject(request):
    """
    Handle creation of subjects not associated with any case report.
    Users can optionally associate a case report using the Select2 field.
    """
    if request.method == 'POST':
        print("Beginning to add dangling subject")
        form = SubjectForm(request.POST, request.FILES, user=request.user)
        
        if form.is_valid():
            subject = form.save()  # commit=True by default
            subject_detail_url = reverse('subject_detail', args=[subject.id])
            messages.success(
                request, 
                format_html(
                    'Subject added successfully. <a href="{}">View here</a>.', 
                    subject_detail_url
                )
            )
            return redirect('add_dangling_subject')
        
        messages.error(request, 'Please correct the errors below.')
    else:
        form = SubjectForm(user=request.user)

    context = {
        'form': form,
        'page_name': 'add_dangling_subject',
        'title': 'Add Dangling Subject',
    }
    return render(request, 'pages/add_dangling_subject.html', context)


@login_required
def add_subject_to_case_report(request, case_report_id):
    """
    Handle creation of subjects associated with a specific case report.
    The case_report field is pre-populated and hidden to enforce association with the specified case report.
    """
    case_report = get_object_or_404(CaseReport, id=case_report_id)
    
    if request.method == 'POST':
        form = SubjectForm(
            request.POST, 
            request.FILES, 
            user=request.user, 
            fixed_case_report=case_report  # Pass the fixed case report to pre-populate and hide the field
        )
        if form.is_valid():
            subject = form.save(commit=True)
            subject.user = request.user
            subject.insert_date = now()
            subject.save()
            
            subject_detail_url = reverse('subject_detail', args=[subject.id])
            messages.success(
                request,
                format_html(
                    'Subject added successfully. <a href="{}">View here</a>.', 
                    subject_detail_url
                )
            )
            return redirect('add_subject_to_case_report', case_report_id=case_report.id)
        
        messages.error(request, 'Please correct the errors below.')
    else:
        form = SubjectForm(
            user=request.user, 
            fixed_case_report=case_report  # Initialize the form with the fixed case report
        )

    context = {
        'form': form,
        'case_report': case_report,
        'page_name': 'add_subject_to_case_report',
        'title': 'Add Subject to Case Report',
    }
    return render(request, 'pages/add_subject_to_case_report.html', context)


@login_required
@user_can_edit_subject
def edit_subject_view(request, subject_id, subject):
    """
    Handle editing or deletion of an existing subject.
    Users can modify subject details and change the associated case report.
    Only staff members or the creator of the subject can edit it.
    
    The `subject` parameter is injected by the `user_can_edit_subject` decorator.
    """
    
    if request.method == 'POST':
        if 'delete_subject' in request.POST:
            has_case_report = subject.case_report is not None
            subject.delete_related_data()
            subject.delete()
            messages.success(request, 'Subject and all associated data have been deleted.')
            if has_case_report:
                return redirect('case_report_detail', subject.case_report.id)
            return redirect('lesion_library')
        
        form = SubjectForm(request.POST, request.FILES, instance=subject, user=request.user)
        if form.is_valid():
            form.save(commit=True)
            messages.success(request, 'Subject updated successfully.')
            return redirect('edit_subject', subject_id=subject.id)
        
        messages.error(request, 'Please correct the errors below.')
    else:
        form = SubjectForm(instance=subject, user=request.user)

    context = {
        'form': form,
        'subject': subject,
        'case_report': subject.case_report,
        'page_name': 'edit_subject',
        'title': 'Edit Subject',
    }
    return render(request, 'pages/edit_subject.html', context)


def subject_detail_view(request, subject_id):
    """Display detailed information about a specific subject and associated data."""
    subject = get_object_or_404(Subject, id=subject_id)
    user_can_view = True

    if subject.internal_use_only and not (request.user.is_authenticated and request.user.is_staff):
        user_can_view = False
    elif subject.internal_use_only:
        messages.warning(
            request,
            'Alert: This subject is marked for internal use only and is not publicly accessible to non-staff members.'
        )

    context = {
        'subject': subject,
        'user_can_view': user_can_view,
        'page_name': 'subject_detail',
        'title': 'Subject Detail',
    }

    if user_can_view:
        context.update({
            'symptoms': subject.symptoms.all(),
            'connectivity_files': subject.connectivity_files.all(),
            'roi_files': subject.roi_files.all(),
            'original_image_files': subject.original_image_files.all(),
        })

    return render(request, 'pages/subject_detail.html', context)