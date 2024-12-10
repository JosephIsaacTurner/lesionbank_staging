# pages/views/faq_views.py

from django.shortcuts import render
from pages.models import Domain


def faq_view(request):
    """
    Renders the FAQ page with comprehensive taxonomy data, including domains, subdomains, and symptoms.
    """
    # Fetch all domains along with their related subdomains and symptoms
    domains = Domain.objects.prefetch_related('subdomains__symptoms').all()

    taxonomy = []
    for domain in domains:
        if domain.name == 'Social Processes':
            continue
        domain_data = {
            'name': domain.name,
            'description': domain.description,
            'subdomains': []
        }

        # Fetch related subdomains for the current domain
        subdomains = domain.subdomains.all()
        for subdomain in subdomains:
            subdomain_data = {
                'name': subdomain.name,
                'description': subdomain.description,
                'symptoms': list(subdomain.symptoms.values('name', 'description'))
            }
            domain_data['subdomains'].append(subdomain_data)

        taxonomy.append(domain_data)

    context = {
        'page_name': 'FAQ',
        'taxonomy': taxonomy,
    }

    return render(request, 'pages/faq.html', context)