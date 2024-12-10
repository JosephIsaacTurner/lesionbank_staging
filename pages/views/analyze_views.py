# pages/views/analyze_views.py 

from django.shortcuts import render
from django.contrib import messages
import environ
import os
from sqlalchemy_utils.db_utils import determine_filetype, fetch_2mm_mni152_mask
from sqlalchemy_utils.db_session import get_session
from sqlalchemy_utils.models_sqlalchemy_orm import Subject, Symptom, Domain, Subdomain, ConnectivityFile
import numpy as np
import nibabel as nib
from PIL import Image
import gzip
from io import BytesIO
import boto3
from botocore.client import Config
from nilearn.maskers import NiftiMasker
import pandas as pd
from pages.forms import NiftiUploadForm
from pages.tasks import decode_task_wrapper, run_full_lesion_analysis
from celery.result import AsyncResult
from django.http import JsonResponse
from django.shortcuts import redirect
from django.contrib.auth.decorators import login_required
import json
import numpy as np
import nibabel as nib
from nibabel.affines import apply_affine
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
import os
import gzip
from io import BytesIO
from django.views.decorators.csrf import csrf_protect
from celery import chain
from pages.models import UsageLog

env = environ.Env()

DO_ACCESS_KEY_ID = env('DO_SPACES_ACCESS_KEY_ID')
DO_SECRET_ACCESS_KEY = env('DO_SPACES_SECRET_ACCESS_KEY')
DO_STORAGE_BUCKET_NAME = env('DO_SPACES_BUCKET_NAME')
DO_S3_ENDPOINT_URL = env('DO_SPACES_ENDPOINT_URL')
DO_SPACES_LOCATION = env('DO_SPACES_LOCATION', default='nyc3')
DO_LOCATION = env('DO_LOCATION')
DO_S3_CUSTOM_DOMAIN = f'{DO_STORAGE_BUCKET_NAME}.{DO_SPACES_LOCATION}.digitaloceanspaces.com'


def get_s3_client():
    """Create and return a boto3 client configured for DigitalOcean Spaces"""
    env = environ.Env()
    
    session = boto3.session.Session()
    client = session.client('s3',
        config=Config(s3={'addressing_style': 'virtual'}),
        region_name=env('DO_SPACES_LOCATION', default='nyc3'),
        endpoint_url=env('DO_SPACES_ENDPOINT_URL'),
        aws_access_key_id=env('DO_SPACES_ACCESS_KEY_ID'),
        aws_secret_access_key=env('DO_SPACES_SECRET_ACCESS_KEY'),
    )
    
    return client


def fetch_from_s3(filepath):
    """
    Fetch and load files from DigitalOcean Spaces using boto3
    
    Parameters:
    filepath (str): Path to file within the bucket
    
    Returns:
    Various: Loaded file data depending on the file type
    """
    env = environ.Env()
    bucket_name = env('DO_SPACES_BUCKET_NAME')
    
    # Get S3 client
    s3_client = get_s3_client()
    
    # Get the file from S3
    try:
        response = s3_client.get_object(Bucket=bucket_name, Key=os.path.join(DO_LOCATION, filepath))
        file_data = response['Body'].read()
    except Exception as e:
        raise Exception(f"Error fetching file from S3: {str(e)}")
    
    # Determine file type and process accordingly
    extension = determine_filetype(filepath)
    
    if extension == 'nii.gz':
        fh = nib.FileHolder(fileobj=gzip.GzipFile(fileobj=BytesIO(file_data)))
        return nib.Nifti1Image.from_file_map({'header': fh, 'image': fh})
    
    elif extension == 'nii':
        fh = nib.FileHolder(fileobj=BytesIO(file_data))
        return nib.Nifti1Image.from_file_map({'header': fh, 'image': fh})
    
    elif extension == 'npy':
        return np.load(BytesIO(file_data), allow_pickle=True)
    
    elif extension in ['png', 'jpg', 'jpeg']:
        return Image.open(BytesIO(file_data))
    
    else:
        raise ValueError(f"Unsupported file type: {extension}")
    

@login_required
def analyze_view(request):
    if request.method == 'POST':
        UsageLog.objects.create(user=request.user, page_name='decode_map')
        form = NiftiUploadForm(request.POST, request.FILES)
        if form.is_valid():
            user_map = form.process_nifti()
            taxonomy_level = form.cleaned_data['taxonomy_level']

            # Store taxonomy_level in session
            request.session['taxonomy_level'] = taxonomy_level

            # Serialize the in-memory NIFTI image
            user_map_data = user_map.to_bytes()

            is_staff = request.user.is_staff

            # Start the Celery task
            task = decode_task_wrapper.delay(taxonomy_level, user_map_data, is_staff)

            context = {
                'page_name': 'Decode',
                'task_id': task.id,
            }
            return render(request, 'pages/decode_progress.html', context)
        else:
            messages.error(request, 'Form is invalid.')
    else:
        form = NiftiUploadForm()
    context = {
        'page_name': 'Analyze',
        'form': form,
    }
    return render(request, 'pages/analyze.html', context)


def decode_task_status(request, task_id):
    try:
        result = AsyncResult(task_id)
        print(f"Task status check - ID: {task_id}, State: {result.state}")  # Debug line

        if result.state == 'SUCCESS':
            response = {
                'state': 'SUCCESS',
            }
        elif result.state == 'FAILURE':
            response = {
                'state': 'FAILURE',
                'error': str(result.result),
            }
        elif result.state == 'PROGRESS':
            info = result.info or {}
            response = {
                'state': 'PROGRESS',
                'current': info.get('current', 0),
                'total': info.get('total', 1),
                'progress': info.get('progress', 0),
                'status': info.get('status', ''),
            }
        else:
            response = {'state': result.state}
        
        print(f"Response: {response}")  # Debug line
        return JsonResponse(response)
    except Exception as e:
        print(f"Error in decode_task_status: {str(e)}")  # Debug line
        response = {
            'state': 'FAILURE',
            'error': f"An unexpected error occurred: {str(e)}",
        }
        return JsonResponse(response)


def decode_results_view(request):
    task_id = request.GET.get('task_id')
    if not task_id:
        messages.error(request, 'No task ID provided.')
        return redirect('decode')

    result = AsyncResult(task_id)
    if result.state != 'SUCCESS':
        messages.error(request, 'Task is not completed yet.')
        return redirect('decode')

    if 'error' in result.result:
        messages.error(request, result.result['error'])
        return redirect('decode')

    context = {
        'page_name': 'Decode_Results',
        'taxonomy_level': request.session.get('taxonomy_level', 'symptom'),
        'grouped_results': result.result.get('grouped_results', []),
        'raw_results': result.result.get('raw_results', []),
    }
    return render(request, 'pages/decode_results.html', context)


@csrf_exempt  # Remove this in production and handle CSRF tokens properly
def voxel_to_nifti_view(request):
    if request.method == 'POST':
        UsageLog.objects.create(user=request.user, page_name='browser_based_segmentation')
        try:
            # Load the mask image
            mask_path = os.path.join('static', 'images', 'MNI152_T1_2mm_brain_mask.nii.gz')
            mask_img = nib.load(mask_path)
            mask_data = mask_img.get_fdata()
            affine = mask_img.affine
            inverse_affine = np.linalg.inv(affine)
            data_shape = mask_data.shape

            # Get the JSON data from the request body
            body_unicode = request.body.decode('utf-8')
            voxel_list = json.loads(body_unicode)

            # Extract MNI coordinates and values
            mni_coords = np.array([voxel[:3] for voxel in voxel_list])
            values = np.array([voxel[3] for voxel in voxel_list])

            # Convert MNI coordinates to voxel indices
            voxel_indices = apply_affine(inverse_affine, mni_coords)
            voxel_indices = np.round(voxel_indices).astype(int)

            # Create an empty data array with the same shape as the mask
            data_array = np.zeros(data_shape)

            # Set the values at the voxel indices
            valid_indices = []
            valid_values = []
            for idx, value in zip(voxel_indices, values):
                x, y, z = idx
                # Ensure indices are within bounds
                if (0 <= x < data_shape[0]) and (0 <= y < data_shape[1]) and (0 <= z < data_shape[2]):
                    valid_indices.append([x, y, z])
                    valid_values.append(value)

            valid_indices = np.array(valid_indices).T  # Transpose to separate x, y, z indices
            data_array[valid_indices[0], valid_indices[1], valid_indices[2]] = valid_values

            # Create a new NIfTI image
            new_img = nib.Nifti1Image(data_array, affine)
            masker = NiftiMasker(mask_img=mask_img).fit()
            new_img = masker.inverse_transform(np.squeeze(masker.transform(new_img)))

            # Save the image to a BytesIO object
            img_bytes = BytesIO()
            new_img.to_file_map({'image': nib.FileHolder(fileobj=img_bytes)})
            img_bytes.seek(0)  # Reset the buffer's position to the beginning

            # Compress the image
            compressed_bytes = BytesIO()
            with gzip.GzipFile(fileobj=compressed_bytes, mode='wb') as f_out:
                f_out.write(img_bytes.getvalue())
            compressed_bytes.seek(0)

            # Prepare the HTTP response
            response = HttpResponse(compressed_bytes.read(), content_type='application/gzip')
            response['Content-Disposition'] = 'attachment; filename="segmented_image.nii.gz"'

            return response

        except Exception as e:
            return JsonResponse({'error': str(e)}, status=400)
    else:
        return JsonResponse({'message': 'Only POST requests are allowed.'}, status=405)
    


@login_required
@csrf_protect
def analyze_voxels_view(request):
    if request.method == 'POST':
        UsageLog.objects.create(user=request.user, page_name='analyze_lesion_connectivity')
        try:
           # Load the mask image
            mask_path = os.path.join('static', 'images', 'MNI152_T1_2mm_brain_mask.nii.gz')
            mask_img = nib.load(mask_path)
            mask_data = mask_img.get_fdata()
            affine = mask_img.affine
            inverse_affine = np.linalg.inv(affine)
            data_shape = mask_data.shape

            # Get the JSON data from the request body
            body_unicode = request.body.decode('utf-8')
            voxel_list = json.loads(body_unicode)

            # Extract MNI coordinates and values
            mni_coords = np.array([voxel[:3] for voxel in voxel_list])
            values = np.array([voxel[3] for voxel in voxel_list])

            # Convert MNI coordinates to voxel indices
            voxel_indices = apply_affine(inverse_affine, mni_coords)
            voxel_indices = np.round(voxel_indices).astype(int)

            # Create an empty data array with the same shape as the mask
            data_array = np.zeros(data_shape)

            # Set the values at the voxel indices
            valid_indices = []
            valid_values = []
            for idx, value in zip(voxel_indices, values):
                x, y, z = idx
                # Ensure indices are within bounds
                if (0 <= x < data_shape[0]) and (0 <= y < data_shape[1]) and (0 <= z < data_shape[2]):
                    valid_indices.append([x, y, z])
                    valid_values.append(value)

            valid_indices = np.array(valid_indices).T  # Transpose to separate x, y, z indices
            data_array[valid_indices[0], valid_indices[1], valid_indices[2]] = valid_values

            # Create a new NIfTI image
            new_img = nib.Nifti1Image(data_array, affine)
            masker = NiftiMasker(mask_img=mask_img).fit()
            new_img = masker.inverse_transform(np.squeeze(masker.transform(new_img)))

            # Save the image to a BytesIO object
            img_bytes = BytesIO()
            new_img.to_file_map({'image': nib.FileHolder(fileobj=img_bytes)})
            img_bytes.seek(0)  # Reset the buffer's position to the beginning

            # Read the bytes from the buffer
            nifti_data_bytes = img_bytes.read()

            # Get user info
            is_staff = request.user.is_staff
            taxonomy_level = 'symptom'  # You can adjust this as needed

            # Run the full analysis task
            task_result = run_full_lesion_analysis.apply_async(args=(nifti_data_bytes, taxonomy_level, is_staff))

            # Return the task ID to the client
            return JsonResponse({'task_id': task_result.id})

        except Exception as e:
            # Log the error for debugging purposes
            # logger.error(f"Error in analyze_voxels_view: {str(e)}")
            return JsonResponse({'error': str(e)}, status=400)
    else:
        return JsonResponse({'message': 'Only POST requests are allowed.'}, status=405)
    

@login_required
def analyze_progress_view(request):
    task_id = request.GET.get('task_id')
    if not task_id:
        messages.error(request, 'No task ID provided.')
        return redirect('analyze')

    context = {
        'page_name': 'Analyze Progress',
        'task_id': task_id,
    }
    return render(request, 'pages/analyze_progress.html', context)


def analyze_task_status(request, task_id):
    try:
        result = AsyncResult(task_id)
        print(f"Task status check - ID: {task_id}, State: {result.state}")  # Debug line

        if result.state == 'SUCCESS':
            response = {
                'state': 'SUCCESS',
            }
        elif result.state == 'FAILURE':
            response = {
                'state': 'FAILURE',
                'error': str(result.result),  # Ensure this is a serializable string
            }
        elif result.state == 'PROGRESS':
            info = result.info or {}
            response = {
                'state': 'PROGRESS',
                'current_step': info.get('current_step', 1),
                'total_steps': info.get('total_steps', 2),
                'progress': info.get('progress', 0),
                'status': info.get('status', '')
            }
        else:
            response = {'state': result.state}
        
        print(f"Response: {response}")  # Debug line
        return JsonResponse(response)
    except Exception as e:
        print(f"Error in analyze_task_status: {str(e)}")  # Debug line
        response = {
            'state': 'FAILURE',
            'error': f"An unexpected error occurred: {str(e)}",
        }
        return JsonResponse(response)


@login_required
def analyze_results_view(request):
    task_id = request.GET.get('task_id')
    if not task_id:
        messages.error(request, 'No task ID provided.')
        return redirect('analyze')

    result = AsyncResult(task_id)
    if result.state != 'SUCCESS':
        messages.error(request, 'Task is not completed yet.')
        return redirect('analyze_progress')

    task_result = result.result
    if 'error' in task_result:
        messages.error(request, task_result['error'])
        return redirect('analyze')

    context = {
        'page_name': 'Analysis_Results',
        'grouped_results': task_result.get('grouped_results', []),
        'raw_results': task_result.get('raw_results', []),
        'connectivity_map_url': task_result.get('connectivity_map_url'),
        'lesion_mask_url': task_result.get('lesion_mask_url'),
    }
    return render(request, 'pages/analyze_results.html', context)
