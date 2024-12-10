# pages/decorators.py

from functools import wraps
from django.shortcuts import get_object_or_404, redirect
from django.contrib import messages
from .models import Subject

def user_can_edit_subject(view_func):
    """
    Decorator to check if the user is a staff member or the creator of the Subject.
    """
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        subject_id = kwargs.get('subject_id')  # Ensure 'subject_id' is in kwargs
        if subject_id is None:
            raise ValueError("subject_id must be provided in the URL pattern.")
        
        subject = get_object_or_404(Subject, id=subject_id)
        
        # Authorization Check
        if not (request.user.is_staff or subject.user == request.user):
            messages.error(request, 'You do not have permission to edit this subject.')
            return redirect('subject_detail', subject_id=subject_id)

        kwargs['subject'] = subject
        return view_func(request, *args, **kwargs)
    
    return _wrapped_view
