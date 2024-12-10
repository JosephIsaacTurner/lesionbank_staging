# pages/views/training_course_views.py

from io import BytesIO
import gzip

import nibabel as nib
import numpy as np
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.db import transaction
from django.db.models import Max, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from nilearn.maskers import NiftiLabelsMasker
from sqlalchemy_utils.db_utils import fetch_atlas_3209c91v

from pages.forms import LevelCreationForm, UserLevelProgressForm
from pages.models import Level, UserLevelProgress


def is_staff_user(user):
    return user.is_staff or user.is_superuser


def load_nifti_from_in_memory_file(file_obj):
    """
    Load a Nifti1Image from an UploadedFile or file-like object.

    Args:
        file_obj (UploadedFile or file-like object): The NIfTI file.

    Returns:
        nib.Nifti1Image: The loaded NIfTI image.

    Raises:
        ValueError: If the file format is unsupported.
    """
    file_obj.seek(0)
    file_content = file_obj.read()

    if file_obj.name.lower().endswith('.nii.gz'):
        gzip_file = gzip.GzipFile(fileobj=BytesIO(file_content))
        file_holder = nib.FileHolder(fileobj=gzip_file)
    elif file_obj.name.lower().endswith('.nii'):
        file_holder = nib.FileHolder(fileobj=BytesIO(file_content))
    else:
        raise ValueError("Unsupported NIfTI file format. Only .nii and .nii.gz are supported.")

    nifti_image = nib.Nifti1Image.from_file_map({'header': file_holder, 'image': file_holder})
    return nifti_image


def calculate_score(user_uploaded_mask_file, true_mask_file):
    """
    Calculate the Dice coefficient between user-uploaded mask and true mask.

    Args:
        user_uploaded_mask_file (UploadedFile or file-like object): The user's uploaded NIfTI mask.
        true_mask_file (file-like object): The true mask fetched from S3.

    Returns:
        float: Dice coefficient score multiplied by 100.
    """
    masker = NiftiLabelsMasker(labels_img=fetch_atlas_3209c91v().maps)
    user_img = load_nifti_from_in_memory_file(user_uploaded_mask_file)
    true_img = load_nifti_from_in_memory_file(true_mask_file)

    user_masked_data = masker.fit_transform(user_img).astype(bool).astype(int)
    true_masked_data = masker.fit_transform(true_img).astype(bool).astype(int)

    intersection = np.sum(user_masked_data * true_masked_data)
    sum_masks = np.sum(user_masked_data) + np.sum(true_masked_data)
    dice_coefficient = (2.0 * intersection) / sum_masks if sum_masks != 0 else 0

    return dice_coefficient * 100


@login_required
def lesion_tracing_completion_view(request):
    user = request.user
    passing_score_threshold = 55
    total_levels = Level.objects.count()
    user_passed_levels = UserLevelProgress.objects.filter(
        user=user, score__gte=passing_score_threshold
    ).count()

    if user_passed_levels == total_levels:
        levels = Level.objects.all().order_by('level_number')
        user_progress = UserLevelProgress.objects.filter(user=user, level__in=levels)

        level_scores = [
            {
                'level_number': level.level_number,
                'level_name': level.name,
                'score': user_progress.filter(level=level).first().score
                if user_progress.filter(level=level).first()
                else None,
            }
            for level in levels
        ]

        completion_date = user_progress.aggregate(max_date=Max('date_completed'))['max_date']

        context = {
            'user': user,
            'level_scores': level_scores,
            'completion_date': completion_date,
        }
        return render(request, 'pages/lesion_tracing_completion.html', context)

    messages.error(request, "You have not completed all levels yet.")
    return redirect('lesion_tracing_practice')


@login_required
def lesion_tracing_practice_view(request, level_id=1):
    user = request.user
    level = get_object_or_404(Level, id=level_id)
    passing_score_threshold = 55

    highest_completed = UserLevelProgress.objects.filter(
        user=user,
        score__gte=passing_score_threshold
    ).aggregate(highest=Max('level__level_number'))['highest'] or 0

    allowed_level_number = highest_completed + 1

    if level.level_number > allowed_level_number:
        redirect_level = Level.objects.filter(level_number=allowed_level_number).first()
        if not redirect_level:
            redirect_level = Level.objects.order_by('-level_number').first()

        messages.error(request, "You cannot access this level yet. Please complete previous levels first.")
        return redirect('lesion_tracing_practice', level_id=redirect_level.id)

    user_progress, created = UserLevelProgress.objects.get_or_create(user=user, level=level)
    user_already_submitted = user_progress.score is not None
    user_passed = user_progress.score >= passing_score_threshold if user_already_submitted else False
    score = user_progress.score

    if request.method == 'POST':
        form = UserLevelProgressForm(request.POST, request.FILES)
        if form.is_valid():
            uploaded_file = form.cleaned_data['user_uploaded_mask']
            new_score = calculate_score(uploaded_file, level.lesion_mask_path)

            with transaction.atomic():
                if user_progress.score is None or new_score > user_progress.score:
                    user_progress.score = new_score
                    if new_score >= passing_score_threshold:
                        user_progress.date_completed = timezone.now()
                    user_progress.save()
                    messages.success(request, f'Your submission was successful. Your new score is {new_score}')
                else:
                    messages.info(request, 'Your submission was successful, but your score did not improve.')
            return redirect('lesion_tracing_practice', level_id=level.id)
    else:
        form = UserLevelProgressForm()

    next_level = Level.objects.filter(level_number__gt=level.level_number).order_by('level_number').first()
    previous_level = Level.objects.filter(level_number__lt=level.level_number).order_by('-level_number').first()

    total_levels = Level.objects.count()
    user_passed_levels = UserLevelProgress.objects.filter(
        user=user, score__gte=passing_score_threshold
    ).count()
    user_completed_all_levels = user_passed_levels == total_levels

    context = {
        'level': level,
        'user_already_submitted': user_already_submitted,
        'user_completed_all_levels': user_completed_all_levels,
        'user_passed': user_passed,
        'score': score,
        'form': form,
        'next_level': next_level,
        'previous_level': previous_level,
        'page_name': 'lesion_tracing_practice',
        'title': f'Lesion Tracing Practice - Level {level.level_number}',
    }

    return render(request, 'pages/lesion_tracing_practice.html', context)


@user_passes_test(is_staff_user)
def create_level_view(request):
    if request.method == 'POST':
        form = LevelCreationForm(request.POST, request.FILES)
        if form.is_valid():
            level = form.save()
            messages.success(request, f'Level {level.level_number} created successfully!')
            return redirect('lesion_tracing_practice', level_id=level.id)
        messages.error(request, 'Please correct the errors below.')
    else:
        form = LevelCreationForm()

    context = {
        'form': form,
        'page_name': 'create_level',
        'title': 'Create New Level',
    }
    return render(request, 'pages/create_level.html', context)