# pages/templatetags/custom_filters.py
from django import template
import os

register = template.Library()

@register.filter(name='has_extension')
def has_extension(value, extensions):
    """
    Checks if the file name ends with any of the provided extensions.
    Usage: {{ file.path.name|has_extension:".nii .nii.gz" }}
    """
    ext_list = extensions.split()
    return any(value.endswith(ext) for ext in ext_list)

@register.filter(name='basename')
def basename(value):
    """
    Returns the base name of a file path.
    Usage: {{ file.path.name|basename }}
    """
    return os.path.basename(value)