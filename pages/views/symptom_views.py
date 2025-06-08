# pages/views/symptom_views.py

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.db import transaction
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import (
    get_object_or_404,
    redirect,
    render
)
from django.urls import reverse
from urllib.parse import quote

from pages.forms import (
    DomainForm,
    DomainGroupLevelMapForm,
    DomainGroupLevelMapFileFormSet,
    SubdomainForm,
    SubdomainGroupLevelMapForm,
    SubdomainGroupLevelMapFileFormSet,
    SymptomForm,
    SymptomGroupLevelMapForm,
    SymptomGroupLevelMapFileFormSet,
    AddSymptomForm
)
from pages.models import Domain, GroupLevelMapFile, Subdomain, Symptom, Synonym, MeshTerm


def is_staff_user(user):
    return user.is_staff or user.is_superuser


def symptom_detail_view(request, pk):
    """
    Display the details of a specific symptom.
    """
    symptom = get_object_or_404(Symptom, pk=pk)
    user_can_view = True

    if symptom.internal_use_only:
        if not request.user.is_authenticated or not request.user.is_staff:
            user_can_view = False
        else:
            messages.warning(
                request,
                'Alert: This symptom is marked for internal use only and is not publicly accessible to non-staff members.'
            )

    context = {
        'page_name': 'symptom_detail',
        'symptom': symptom,
        'title': f"Symptom Detail - {symptom.name}",
        'user_can_view': user_can_view,
    }

    if user_can_view:
        group_level_map_files = GroupLevelMapFile.objects.filter(symptom=symptom)
        context['group_level_map_files'] = group_level_map_files

    return render(request, 'pages/symptom_detail.html', context)


def subdomain_detail_view(request, pk):
    """
    Display the details of a specific subdomain.
    """
    subdomain = get_object_or_404(Subdomain, pk=pk)
    group_level_map_files = GroupLevelMapFile.objects.filter(subdomain=subdomain)
    context = {
        'page_name': 'subdomain_detail',
        'subdomain': subdomain,
        'group_level_map_files': group_level_map_files,
        'title': f"Subdomain Detail - {subdomain.name}",
    }
    return render(request, 'pages/subdomain_detail.html', context)


def domain_detail_view(request, pk):
    """
    Display the details of a specific domain.
    """
    domain = get_object_or_404(Domain, pk=pk)
    group_level_map_files = GroupLevelMapFile.objects.filter(domain=domain)
    context = {
        'page_name': 'domain_detail',
        'domain': domain,
        'group_level_map_files': group_level_map_files,
        'title': f"Domain Detail - {domain.name}",
    }
    return render(request, 'pages/domain_detail.html', context)


def get_symptoms_json(request):
    """
    Retrieve symptoms data in JSON format for DataTables, with conditional visibility
    for non-staff users.
    """
    draw = int(request.GET.get('draw', 1))
    start = int(request.GET.get('start', 0))
    length = int(request.GET.get('length', 100))
    domain_name = request.GET.get('domain_name')
    subdomain_name = request.GET.get('subdomain_name')
    search_value = request.GET.get('search[value]', '')
    order_column_index = request.GET.get('order[0][column]', '0')
    order_dir = request.GET.get('order[0][dir]', 'asc')

    column_order_map = {
        '0': 'name',
        '1': 'domain__name',
        '2': 'subdomain__name',
        '3': 'subject_count',
        '4': 'connectivity_subject_count',
        '5': 'case_report_count',
    }

    is_staff = is_staff_user(request.user)
    queryset = Symptom.objects.all()
    
    # This filter will be empty for staff, and will filter for public subjects for non-staff.
    subject_visibility_filter = Q()

    # Apply visibility rules for non-staff users
    if not is_staff:
        # 1. Exclude symptoms explicitly marked as internal.
        queryset = queryset.filter(internal_use_only=False)
        
        # 2. Define the filter to count only public subjects.
        subject_visibility_filter = Q(subjects_with_symptoms__internal_use_only=False)
        
        # 3. Annotate with a temporary public subject count for filtering.
        queryset = queryset.annotate(
            public_subject_count=Count(
                'subjects_with_symptoms',
                filter=subject_visibility_filter,
                distinct=True
            )
        )
        
        # 4. Exclude symptoms that have no visible (public) subjects.
        queryset = queryset.filter(public_subject_count__gt=0)

    # `recordsTotal` is the count after visibility rules, but before table filtering.
    records_total = queryset.count()

    if domain_name:
        queryset = queryset.filter(domain__name=domain_name)
        count_domain = queryset.count()

    if subdomain_name:
        queryset = queryset.filter(subdomain__name=subdomain_name)
        count_subdomain = queryset.count()

    if search_value:
        queryset = queryset.filter(
            Q(name__icontains=search_value) |
            Q(domain__name__icontains=search_value) |
            Q(subdomain__name__icontains=search_value)
        )

    # `recordsFiltered` is the count after all filters have been applied.
    records_filtered = queryset.count()

    # Annotate the queryset with the final counts for display.
    # For non-staff, subject_visibility_filter ensures only public subjects are counted.
    # For staff, the filter is empty, so all subjects are counted.
    queryset = queryset.annotate(
        subject_count=Count(
            'subjects_with_symptoms',
            filter=subject_visibility_filter,
            distinct=True
        ),
        connectivity_subject_count=Count(
            'subjects_with_symptoms',
            filter=subject_visibility_filter & Q(subjects_with_symptoms__connectivity_files__isnull=False),
            distinct=True
        ),
        case_report_count=Count('case_reports', distinct=True),
    )

    order_column = column_order_map.get(str(order_column_index), 'name')
    if order_dir == 'desc':
        order_column = f'-{order_column}'

    queryset = queryset.order_by(order_column)
    queryset = queryset[start:start + length]

    data = []
    for symptom in queryset:
        domain_link = ''
        if symptom.domain:
            domain_detail_url = reverse('domain_detail', args=[symptom.domain.id])
            domain_link = f'<a href="{domain_detail_url}">{symptom.domain.name}</a>'

        subdomain_link = ''
        if symptom.subdomain:
            subdomain_detail_url = reverse('subdomain_detail', args=[symptom.subdomain.id])
            subdomain_link = f'<a href="{subdomain_detail_url}">{symptom.subdomain.name}</a>'

        symptom_url = reverse('symptom_detail', args=[symptom.id])
        symptom_link = f'<a href="{symptom_url}">{symptom.name}</a>'

        case_reports_url = f"{reverse('case_report_library')}?symptom_name={quote(symptom.name)}"
        case_reports_link = f'<a href="{case_reports_url}">{symptom.case_report_count}</a>'

        symptom_map = GroupLevelMapFile.objects.filter(
            symptom=symptom, statistic_type__code='percent_overlap'
        ).first()

        domain_map = None
        if symptom.domain:
            domain_map = GroupLevelMapFile.objects.filter(
                domain=symptom.domain, statistic_type__code='percent_overlap'
            ).first()

        subdomain_map = None
        if symptom.subdomain:
            subdomain_map = GroupLevelMapFile.objects.filter(
                subdomain=symptom.subdomain, statistic_type__code='percent_overlap'
            ).first()

        record = {
            'name': symptom_link,
            'domain': domain_link,
            'subdomain': subdomain_link,
            'subject_count': symptom.subject_count,
            'connectivity_subject_count': symptom.connectivity_subject_count,
            'case_report_count': case_reports_link,
        }

        if symptom_map:
            record['symptom_sensitivity_percent_overlap_map'] = {
                'id': symptom_map.id,
                'path': symptom_map.path.url if symptom_map.path else None
            }
        if domain_map:
            record['domain_sensitivity_percent_overlap_map'] = {
                'id': domain_map.id,
                'path': domain_map.path.url if domain_map.path else None
            }
        if subdomain_map:
            record['subdomain_sensitivity_percent_overlap_map'] = {
                'id': subdomain_map.id,
                'path': subdomain_map.path.url if subdomain_map.path else None
            }

        data.append(record)

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

    return JsonResponse(json_response)


def symptom_library_view(request):
    """
    Display the symptom library.
    """
    domain_name = request.GET.get('domain_name')
    subdomain_name = request.GET.get('subdomain_name')

    is_staff = is_staff_user(request.user)

    context = {
        'title': 'Symptom Library',
        'page_name': 'symptom_library',
        'domain_name': domain_name,
        'subdomain_name': subdomain_name,
        'is_staff': is_staff,
    }

    return render(request, 'pages/symptom_library.html', context)


@login_required
def import_group_level_map_view(request, category, pk, form_class, template_name, success_url_name):
    """
    Generic view to import a Group Level Map for a given category.
    """
    category_details = {
        'symptom': {
            'model': Symptom,
            'return_url_name': 'symptom_detail',
            'verbose_name': 'Symptom'
        },
        'subdomain': {
            'model': Subdomain,
            'return_url_name': 'subdomain_detail',
            'verbose_name': 'Subdomain'
        },
        'domain': {
            'model': Domain,
            'return_url_name': 'domain_detail',
            'verbose_name': 'Domain'
        }
    }

    if category not in category_details:
        messages.error(request, "Invalid category specified.")
        return redirect('some_error_page')  # Replace with your error page

    related_object = get_object_or_404(category_details[category]['model'], pk=pk)
    return_url_name = category_details[category]['return_url_name']
    related_object_verbose_name = category_details[category]['verbose_name']

    if request.method == 'POST':
        form = form_class(
            request.POST,
            request.FILES,
            user=request.user,
            related_object=related_object,
            category=category
        )
        if form.is_valid():
            group_level_map = form.save(commit=True, category_name=related_object.name)
            form.save_m2m()
            messages.success(request, 'Group Level Map added successfully.')
            return redirect(return_url_name, pk=related_object.id)
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = form_class(user=request.user, related_object=related_object, category=category)

    context = {
        'form': form,
        'related_object': related_object,
        'page_name': success_url_name,
        'title': f'Import Group Level Map to {related_object_verbose_name}',
        'return_url_name': return_url_name,
        'related_object_verbose_name': related_object_verbose_name,
    }
    return render(request, template_name, context)


@login_required
def import_group_level_map_to_symptom(request, pk):
    """
    Attach a Group Level Map to a Symptom.
    """
    return import_group_level_map_view(
        request=request,
        category='symptom',
        pk=pk,
        form_class=SymptomGroupLevelMapForm,
        template_name='pages/import_group_level_map_to_symptom.html',
        success_url_name='import_group_level_map_symptom'
    )


@login_required
def import_group_level_map_to_subdomain(request, pk):
    """
    Attach a Group Level Map to a Subdomain.
    """
    return import_group_level_map_view(
        request=request,
        category='subdomain',
        pk=pk,
        form_class=SubdomainGroupLevelMapForm,
        template_name='pages/import_group_level_map_to_subdomain.html',
        success_url_name='import_group_level_map_subdomain'
    )


@login_required
def import_group_level_map_to_domain(request, pk):
    """
    Attach a Group Level Map to a Domain.
    """
    return import_group_level_map_view(
        request=request,
        category='domain',
        pk=pk,
        form_class=DomainGroupLevelMapForm,
        template_name='pages/import_group_level_map_to_domain.html',
        success_url_name='import_group_level_map_domain'
    )


@login_required
def manage_group_level_maps_view(request, category, pk, formset_class, template_name):
    """
    Generic view to manage Group Level Maps for Symptom, Subdomain, or Domain.
    """
    category_mapping = {
        'symptom': {
            'model': Symptom,
            'verbose_name': 'Symptom',
            'return_url_name': 'symptom_detail',
            'manage_url_name': 'manage_group_level_maps_symptom'
        },
        'subdomain': {
            'model': Subdomain,
            'verbose_name': 'Subdomain',
            'return_url_name': 'subdomain_detail',
            'manage_url_name': 'manage_group_level_maps_subdomain'
        },
        'domain': {
            'model': Domain,
            'verbose_name': 'Domain',
            'return_url_name': 'domain_detail',
            'manage_url_name': 'manage_group_level_maps_domain'
        }
    }

    if category not in category_mapping:
        messages.error(request, "Invalid category specified.")
        return redirect('some_error_page')  # Replace with your error page

    related_model = category_mapping[category]['model']
    related_object_verbose_name = category_mapping[category]['verbose_name']
    manage_url_name = category_mapping[category]['manage_url_name']
    related_object = get_object_or_404(related_model, pk=pk)

    if request.method == 'POST':
        formset = formset_class(request.POST, request.FILES, instance=related_object, user=request.user)
        if formset.is_valid():
            with transaction.atomic():
                formset.save()
            messages.success(request, f'Group Level Maps for {related_object_verbose_name} updated successfully.')
            return redirect(reverse(manage_url_name, kwargs={'pk': related_object.id}))
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        formset = formset_class(instance=related_object, user=request.user)

    context = {
        'formset': formset,
        'related_object': related_object,
        'title': f'Manage Group Level Maps for {related_object_verbose_name}: {related_object.name}',
        'related_object_verbose_name': related_object_verbose_name,
        'manage_url_name': manage_url_name,
        'return_url_name': category_mapping[category]['return_url_name'],
    }
    return render(request, template_name, context)


@login_required
def manage_group_level_maps_symptom(request, pk):
    """
    Manage Group Level Maps for a Symptom.
    """
    return manage_group_level_maps_view(
        request=request,
        category='symptom',
        pk=pk,
        formset_class=SymptomGroupLevelMapFileFormSet,
        template_name='pages/manage_group_level_maps_symptom.html'
    )


@login_required
def manage_group_level_maps_subdomain(request, pk):
    """
    Manage Group Level Maps for a Subdomain.
    """
    return manage_group_level_maps_view(
        request=request,
        category='subdomain',
        pk=pk,
        formset_class=SubdomainGroupLevelMapFileFormSet,
        template_name='pages/manage_group_level_maps_subdomain.html'
    )


@login_required
def manage_group_level_maps_domain(request, pk):
    """
    Manage Group Level Maps for a Domain.
    """
    return manage_group_level_maps_view(
        request=request,
        category='domain',
        pk=pk,
        formset_class=DomainGroupLevelMapFileFormSet,
        template_name='pages/manage_group_level_maps_domain.html'
    )


@user_passes_test(is_staff_user)
def edit_symptom(request, pk):
    """
    Edit a Symptom and its associated Group Level Maps.
    """
    symptom = get_object_or_404(Symptom, pk=pk)
    if request.method == 'POST':
        form = SymptomForm(request.POST, instance=symptom)
        formset = SymptomGroupLevelMapFileFormSet(request.POST, request.FILES, instance=symptom)
        if form.is_valid() and formset.is_valid():
            form.save()
            formset.save()
            messages.success(request, 'Symptom updated successfully.')
            return redirect('edit_symptom', pk=symptom.pk)
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = SymptomForm(instance=symptom)
        formset = SymptomGroupLevelMapFileFormSet(instance=symptom)

    context = {
        'form': form,
        'formset': formset,
        'title': f'Edit Symptom: {symptom.name}',
        'symptom': symptom
    }
    return render(request, 'pages/edit_symptom.html', context)


@user_passes_test(is_staff_user)
def edit_subdomain(request, pk):
    """
    Edit a Subdomain and its associated Group Level Maps.
    """
    subdomain = get_object_or_404(Subdomain, pk=pk)
    if request.method == 'POST':
        form = SubdomainForm(request.POST, instance=subdomain)
        formset = SubdomainGroupLevelMapFileFormSet(request.POST, request.FILES, instance=subdomain)
        if form.is_valid() and formset.is_valid():
            form.save()
            formset.save()
            messages.success(request, 'Subdomain updated successfully.')
            return redirect('edit_subdomain', pk=subdomain.pk)
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = SubdomainForm(instance=subdomain)
        formset = SubdomainGroupLevelMapFileFormSet(instance=subdomain)

    context = {
        'form': form,
        'formset': formset,
        'title': f'Edit Subdomain: {subdomain.name}',
        'subdomain': subdomain
    }
    return render(request, 'pages/edit_subdomain.html', context)


@user_passes_test(is_staff_user)
def edit_domain(request, pk):
    """
    Edit a Domain and its associated Group Level Maps.
    """
    domain = get_object_or_404(Domain, pk=pk)
    if request.method == 'POST':
        form = DomainForm(request.POST, instance=domain)
        formset = DomainGroupLevelMapFileFormSet(request.POST, request.FILES, instance=domain)
        if form.is_valid() and formset.is_valid():
            form.save()
            formset.save()
            messages.success(request, 'Domain updated successfully.')
            return redirect('edit_domain', pk=domain.pk)
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = DomainForm(instance=domain)
        formset = DomainGroupLevelMapFileFormSet(instance=domain)

    context = {
        'form': form,
        'formset': formset,
        'title': f'Edit Domain: {domain.name}',
        'domain': domain
    }
    return render(request, 'pages/edit_domain.html', context)

def get_subdomains(request):
    """
    AJAX endpoint that returns subdomains for a given domain_id.
    Expected GET params:
    - domain_id: int
    - search: str (optional)
    """
    domain_id = request.GET.get('domain_id', None)
    search_term = request.GET.get('search', '')

    if not domain_id:
        return JsonResponse([], safe=False)

    try:
        domain = Domain.objects.get(pk=domain_id)
    except Domain.DoesNotExist:
        return JsonResponse([], safe=False)

    qs = domain.subdomains.all()
    if search_term:
        qs = qs.filter(name__icontains=search_term)

    results = []
    for s in qs:
        results.append({'id': s.id, 'text': s.name})
    return JsonResponse(results, safe=False)

@user_passes_test(is_staff_user)
def add_new_symptom(request):
    """
    Add a new Symptom to the DB.
    """
    domain_selected = None
    if request.method == 'POST':
        posted_domain_id = request.POST.get('domain')
        if posted_domain_id:
            try:
                domain_selected = Domain.objects.get(pk=posted_domain_id)
            except Domain.DoesNotExist:
                domain_selected = None

        form = AddSymptomForm(request.POST, domain_selected=domain_selected)
        if form.is_valid():
            name = form.cleaned_data['name']
            domain = form.cleaned_data['domain']
            subdomain = form.cleaned_data['subdomain']
            description = form.cleaned_data['description']
            internal_use_only = form.cleaned_data['internal_use_only']
            synonyms = form.cleaned_data['synonyms']
            mesh_terms = form.cleaned_data['mesh_terms']

            symptom = Symptom.objects.create(
                name=name,
                description=description,
                domain=domain,
                subdomain=subdomain,
                internal_use_only=internal_use_only,
                user=request.user
            )

            # Add synonyms
            for syn in synonyms:
                Synonym.objects.create(name=syn, symptom=symptom, user=request.user)

            # Add mesh terms
            for mt in mesh_terms:
                MeshTerm.objects.create(name=mt, symptom=symptom, user=request.user)

            messages.success(request, 'New symptom added successfully.')
            return redirect('edit_symptom', pk=symptom.pk)
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = AddSymptomForm()

    return render(request, 'pages/add_symptom.html', {'form': form, 'title': 'Add New Symptom'})