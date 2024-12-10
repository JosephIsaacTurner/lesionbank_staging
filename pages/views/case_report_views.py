# pages/views/case_report_views.py

from urllib.parse import quote
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import JsonResponse
from django.db.models import (
    Q, Min, Count, Case, When, Value, CharField
)
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.conf import settings
from django.contrib import messages
from django.utils.html import format_html
from django.utils.timezone import now
from django.views.decorators.http import require_GET
from django.views.decorators.csrf import csrf_exempt

from pages.models import (
    Subject, Symptom,
    CaseReport, InclusionCriteria
)
from pages.forms import CaseReportForm, CaseStudyInclusionForm


def staff_required(login_url=None):
    """
    Decorator for views that checks that the user is a staff member.

    Args:
        login_url (str, optional): URL to redirect to for login. Defaults to None.

    Returns:
        function: Decorated view function.
    """
    return user_passes_test(lambda u: u.is_staff, login_url=login_url)


def is_staff_user(user):
    """
    Check if the user is a staff member or superuser.

    Args:
        user (User): The user instance.

    Returns:
        bool: True if user is staff or superuser, else False.
    """
    return user.is_staff or user.is_superuser


def get_case_reports_json(request):
    """
    Retrieve case reports in JSON format with pagination, filtering, and ordering.

    Args:
        request (HttpRequest): The HTTP request object.

    Returns:
        JsonResponse: JSON response containing case report data.
    """
    # Pagination parameters
    draw = int(request.GET.get('draw', 1))
    start = int(request.GET.get('start', 0))
    length = int(request.GET.get('length', 100))

    # Filtering parameters
    domain_name = request.GET.get('domain_name')
    subdomain_name = request.GET.get('subdomain_name')
    symptom_name = request.GET.get('symptom_name')
    validated_status = request.GET.get('validated_status')

    # Search value
    search_value = request.GET.get('search[value]', '')

    # Ordering parameters
    order_column_index = request.GET.get('order[0][column]', '0')
    order_dir = request.GET.get('order[0][dir]', 'asc')

    # Mapping from column index to database fields
    column_order_map = {
        '0': 'doi',
        '1': 'first_author',
        '2': 'year',
        '3': 'min_domain',
        '4': 'min_subdomain',
        '5': 'min_symptom',
        '6': 'validated_status',
    }

    # Initial queryset
    queryset = CaseReport.objects.all()

    if not is_staff_user(request.user):
        queryset = queryset.exclude(casereportsymptom__symptom__internal_use_only=True)

    # Apply domain filter
    if domain_name:
        domain_filter = Q(casereportsymptom__symptom__domain__name=domain_name)
        if not is_staff_user(request.user):
            domain_filter &= Q(casereportsymptom__symptom__internal_use_only=False)
        queryset = queryset.filter(domain_filter)
        count_domain = queryset.count()

    # Apply subdomain filter
    if subdomain_name:
        subdomain_filter = Q(casereportsymptom__symptom__subdomain__name=subdomain_name)
        if not is_staff_user(request.user):
            subdomain_filter &= Q(casereportsymptom__symptom__internal_use_only=False)
        queryset = queryset.filter(subdomain_filter)
        count_subdomain = queryset.count()

    # Apply symptom filter
    if symptom_name:
        symptom_filter = Q(casereportsymptom__symptom__name=symptom_name)
        if not is_staff_user(request.user):
            symptom_filter &= Q(casereportsymptom__symptom__internal_use_only=False)
        queryset = queryset.filter(symptom_filter)
        count_symptom = queryset.count()

    # Apply search
    if search_value:
        queryset = queryset.filter(
            Q(doi__icontains=search_value) |
            Q(first_author__icontains=search_value) |
            Q(year__icontains=search_value) |
            Q(casereportsymptom__symptom__domain__name__icontains=search_value) |
            Q(casereportsymptom__symptom__subdomain__name__icontains=search_value) |
            Q(casereportsymptom__symptom__name__icontains=search_value)
        ).distinct()

    # Total records before filtering
    records_total = CaseReport.objects.exclude(
        casereportsymptom__symptom__internal_use_only=True
    ).count() if not is_staff_user(request.user) else CaseReport.objects.count()

    # Annotate queryset with validation counts and status
    queryset = queryset.annotate(
        num_included=Count('inclusion_criteria', filter=Q(inclusion_criteria__is_included=True)),
        num_excluded=Count('inclusion_criteria', filter=Q(inclusion_criteria__is_included=False)),
        total_validations=Count('inclusion_criteria'),
    ).annotate(
        validated_status=Case(
            When(total_validations=0, then=Value('2: Unseen')),
            When(num_included__gte=1, num_excluded=0, then=Value('0: Validated')),
            When(num_included=0, num_excluded__gte=1, then=Value('3: Rejected')),
            When(num_included__gte=1, num_excluded__gte=1, then=Value('1: Disagreement')),
            default=Value('4: Unknown'),
            output_field=CharField(),
        )
    )

    # Apply validated_status filter
    if validated_status:
        validated_filters = {
            'Unseen': Q(total_validations=0),
            'Validated': Q(num_included__gte=1, num_excluded=0),
            'Rejected': Q(num_included=0, num_excluded__gte=1),
            'Disagreement': Q(num_included__gte=1, num_excluded__gte=1),
        }
        filter_condition = validated_filters.get(validated_status)
        if filter_condition:
            queryset = queryset.filter(filter_condition)

    # Total records after filtering
    records_filtered = queryset.count()

    # Annotate queryset for ordering
    queryset = queryset.annotate(
        min_symptom=Min('casereportsymptom__symptom__name'),
        min_domain=Min('casereportsymptom__symptom__domain__name'),
        min_subdomain=Min('casereportsymptom__symptom__subdomain__name'),
    ).distinct()

    # Determine ordering
    order_column = column_order_map.get(str(order_column_index), 'doi')
    if order_dir == 'desc':
        order_column = f'-{order_column}'
    queryset = queryset.order_by(order_column)

    # Apply pagination
    paginator = Paginator(queryset, length)
    page_number = (start // length) + 1
    try:
        case_reports = paginator.page(page_number)
    except PageNotAnInteger:
        case_reports = paginator.page(1)
    except EmptyPage:
        case_reports = paginator.page(paginator.num_pages)

    # Prepare data for response
    data = []
    for case_report in case_reports:
        # Retrieve related domains, subdomains, and symptoms
        if not is_staff_user(request.user):
            symptoms = set(
                case_report.casereportsymptom_set.filter(symptom__internal_use_only=False)
                .values_list('symptom__name', flat=True)
            )
            domains = set(
                case_report.casereportsymptom_set.filter(symptom__internal_use_only=False)
                .values_list('symptom__domain__name', flat=True)
            )
            subdomains = set(
                case_report.casereportsymptom_set.filter(symptom__internal_use_only=False)
                .values_list('symptom__subdomain__name', flat=True)
            )
        else:
            symptoms = set(case_report.casereportsymptom_set.values_list('symptom__name', flat=True))
            domains = set(case_report.casereportsymptom_set.values_list('symptom__domain__name', flat=True))
            subdomains = set(case_report.casereportsymptom_set.values_list('symptom__subdomain__name', flat=True))

        # Construct HTML links for domains
        domain_links = [
            format_html('<a href="{}">{}</a>', 
                       reverse('case_report_library') + f"?domain_name={quote(domain)}", 
                       domain) 
            for domain in domains
        ]
        domain_html = ', '.join(domain_links)

        # Construct HTML links for subdomains
        subdomain_links = [
            format_html('<a href="{}">{}</a>', 
                       reverse('case_report_library') + f"?subdomain_name={quote(subdomain)}", 
                       subdomain) 
            for subdomain in subdomains
        ]
        subdomain_html = ', '.join(subdomain_links)

        # Construct HTML links for symptoms
        symptom_links = [
            format_html('<a href="{}">{}</a>', 
                       reverse('case_report_library') + f"?symptom_name={quote(symptom)}", 
                       symptom) 
            for symptom in symptoms
        ]
        symptom_html = ', '.join(symptom_links)

        # Prepare PDF URL
        pdf_url = (
            f"{settings.MEDIA_URL}{str(case_report.path).replace('%2F', '%252F')}"
            if request.user.is_authenticated and case_report.path
            else None
        )

        data.append({
            'doi': case_report.doi,
            'first_author': case_report.first_author,
            'year': case_report.year or '',
            'domain': domain_html,
            'subdomain': subdomain_html,
            'symptom': symptom_html,
            'validated_status': case_report.validated_status,
            'case_report_id': f"{case_report.id}",
            'pdf_url': pdf_url,
        })

    # Prepare JSON response
    json_response = {
        'draw': draw,
        'recordsTotal': records_total,
        'recordsFiltered': records_filtered,
        'data': data,
    }

    if domain_name:
        json_response['domainCount'] = count_domain
    if subdomain_name:
        json_response['subdomainCount'] = count_subdomain
    if symptom_name:
        json_response['symptomCount'] = count_symptom

    return JsonResponse(json_response)


def case_report_library_view(request):
    """
    Render the Case Report Library page with optional filtering parameters.

    Args:
        request (HttpRequest): The HTTP request object.

    Returns:
        HttpResponse: Rendered HTML page.
    """
    domain_name = request.GET.get('domain_name')
    subdomain_name = request.GET.get('subdomain_name')
    symptom_name = request.GET.get('symptom_name')

    # Validate the 'validated' query parameter if present
    validated = request.GET.get('validated')
    if validated is not None:
        validated = validated.lower() == 'true'

    context = {
        'title': 'Case Report Library',
        'page_name': 'case_report_library',
        'domain_name': domain_name,
        'subdomain_name': subdomain_name,
        'symptom_name': symptom_name,
        'validated': validated,
        'is_logged_in': request.user.is_authenticated,
    }

    return render(request, 'pages/case_report_library.html', context)


def case_report_detail_view(request, case_report_id):
    """
    Display the details of a specific case report, including associated symptoms and inclusion criteria.

    Args:
        request (HttpRequest): The HTTP request object.
        case_report_id (int): The ID of the case report.

    Returns:
        HttpResponse: Rendered HTML page with case report details.
    """
    case_report = get_object_or_404(CaseReport, id=case_report_id)
    symptoms = Symptom.objects.filter(
        casereportsymptom__case_report=case_report
    ).select_related('subdomain__domain').distinct()

    # Fetch subjects associated with this case report
    subjects = Subject.objects.filter(case_report=case_report)

    # Fetch inclusion criteria
    inclusion_criteria_list = InclusionCriteria.objects.filter(case_report=case_report)
    included_users = inclusion_criteria_list.filter(is_included=True).values_list('user__username', flat=True)
    excluded_users = inclusion_criteria_list.filter(is_included=False).values_list('user__username', flat=True)
    inclusion_notes = inclusion_criteria_list.exclude(notes__isnull=True).exclude(notes__exact='')

    # Handle inclusion form submission
    if request.user.is_authenticated:
        try:
            user_inclusion_criteria = InclusionCriteria.objects.get(
                case_report=case_report,
                user=request.user,
            )
        except InclusionCriteria.DoesNotExist:
            user_inclusion_criteria = None

        if request.method == 'POST':
            form = CaseStudyInclusionForm(request.POST, instance=user_inclusion_criteria)
            if form.is_valid():
                inclusion_criteria = form.save(commit=False)
                inclusion_criteria.case_report = case_report
                inclusion_criteria.user = request.user
                inclusion_criteria.insert_date = now()
                inclusion_criteria.save()
                messages.success(request, 'Your validation has been submitted.')
                return redirect('case_report_detail', case_report_id=case_report.id)
            else:
                messages.error(request, 'Please correct the errors below.')
        else:
            form = CaseStudyInclusionForm(instance=user_inclusion_criteria)
    else:
        form = None

    context = {
        'page_name': 'case_report_detail',
        'title': 'Case Report Detail',
        'case_report': case_report,
        'symptoms': symptoms,
        'included_users': included_users,
        'excluded_users': excluded_users,
        'form': form,
        'subjects': subjects,
        'inclusion_notes': inclusion_notes,
    }

    return render(request, 'pages/case_report_detail.html', context)


@login_required
def import_case_report(request):
    """
    Handle the import of a new case report via a form submission.

    Args:
        request (HttpRequest): The HTTP request object.

    Returns:
        HttpResponse: Redirect to the import page upon success or render the form with errors.
    """
    if request.method == 'POST':
        print("Beginning to import case report")
        form = CaseReportForm(request.POST, request.FILES, user=request.user)  # Pass the user here
        if form.is_valid():
            user = request.user
            # No need to set form.instance.user here; it's handled in the form's save() method
            doi = form.cleaned_data.get('doi')
            pubmed_id = form.cleaned_data.get('pubmed_id')

            # Check for duplicates
            duplicate = False
            if doi and CaseReport.objects.filter(doi=doi).exists():
                messages.error(request, 'A case report with this DOI already exists.')
                duplicate = True
            if pubmed_id and CaseReport.objects.filter(pubmed_id=pubmed_id).exists():
                messages.error(request, 'A case report with this PubMed ID already exists.')
                duplicate = True

            if not duplicate:
                case_report = form.save()  # Save without commit=False
                # Construct the URL for the detail view
                detail_url = reverse('case_report_detail', args=[case_report.id])
                # Create a formatted success message with a link
                success_message = format_html(
                    'Case report imported successfully. <a href="{}">View here</a>.',
                    detail_url
                )
                messages.success(request, success_message)
                return redirect('import_case_report')
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = CaseReportForm(user=request.user)  # Pass the user here as well

    context = {
        'form': form,
        'page_name': 'import_case_report',
        'title': 'Import Case Report',
    }
    return render(request, 'pages/import_case_report.html', context)


@login_required
def edit_case_report_view(request, case_report_id):
    """
    Edit the details of a specific case report. Accessible only by staff users.

    Args:
        request (HttpRequest): The HTTP request object.
        case_report_id (int): The ID of the case report to edit.

    Returns:
        HttpResponse: Redirect to the case report detail page upon success or render the edit form with errors.
    """
    case_report = get_object_or_404(CaseReport, id=case_report_id)

    if request.method == 'POST':
        # Pass 'user=request.user' to the form
        form = CaseReportForm(request.POST, request.FILES, instance=case_report, user=request.user)
        if form.is_valid():
            try:
                form.save()
                messages.success(request, 'Case report updated successfully.')
                return redirect('case_report_detail', case_report_id=case_report.id)
            except Exception as e:
                messages.error(request, f'Error saving case report: {e}')
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        # Pass 'user=request.user' to the form
        form = CaseReportForm(instance=case_report, user=request.user)

    context = {
        'form': form,
        'case_report': case_report,
        'page_name': 'edit_case_report',
        'title': 'Edit Case Report',
    }
    return render(request, 'pages/edit_case_report.html', context)


@require_GET
@csrf_exempt  # Consider handling CSRF tokens properly in production
def lookup_case_report(request):
    """
    Lookup a CaseReport by doi, pubmed_id, or other_citation in that order.
    Returns data compatible with Select2.
    """
    query = request.GET.get('query', '').strip()
    if not query:
        return JsonResponse({'results': []}, status=400)

    # Priority: DOI > PubMed ID > Other Citation
    case_report = CaseReport.objects.filter(doi__iexact=query).first()
    matched_field = 'DOI'
    if not case_report:
        try:
            matched_field = 'PubMed ID'
            pubmed_id = int(query)
            case_report = CaseReport.objects.filter(pubmed_id=pubmed_id).first()
        except ValueError:
            pass
    if not case_report:
        matched_field = 'Other Citation'
        case_report = CaseReport.objects.filter(other_citation__iexact=query).first()

    matched_field = matched_field if case_report else 'None'

    if case_report:
        return JsonResponse({
            'results': [{
                'id': case_report.id,
                'text': f"ID: {case_report.id} - Matched by {matched_field}"
            }]
        })
    else:
        return JsonResponse({'results': []})