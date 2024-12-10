# pages/tasks/analyze.py


import environ
import os
import gzip
import re
from io import BytesIO
import time

import boto3
import numpy as np
import pandas as pd
from PIL import Image
from botocore.client import Config
from celery import shared_task
from nilearn.maskers import NiftiMasker
import nibabel as nib
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from tqdm import tqdm

from sqlalchemy_utils.db_utils import determine_filetype, fetch_2mm_mni152_mask
from sqlalchemy_utils.db_session import get_session
from sqlalchemy_utils.models_sqlalchemy_orm import (
    Subject,
    Symptom,
    Domain,
    Subdomain,
    ConnectivityFile,
)
from scipy.stats import ttest_1samp

from pfctoolkit import tools
from pfctoolkit import config
from pfctoolkit import mapping
from pfctoolkit import datasets

env = environ.Env()

DO_ACCESS_KEY_ID = env('DO_SPACES_ACCESS_KEY_ID')
DO_SECRET_ACCESS_KEY = env('DO_SPACES_SECRET_ACCESS_KEY')
DO_STORAGE_BUCKET_NAME = env('DO_SPACES_BUCKET_NAME')
DO_S3_ENDPOINT_URL = env('DO_SPACES_ENDPOINT_URL')
DO_SPACES_LOCATION = env('DO_SPACES_LOCATION', default='nyc3')
DO_LOCATION = env('DO_LOCATION')
DO_S3_CUSTOM_DOMAIN = f'{DO_STORAGE_BUCKET_NAME}.{DO_SPACES_LOCATION}.digitaloceanspaces.com'


def get_s3_client():
    """
    Create and return a boto3 client configured for DigitalOcean Spaces.

    Returns:
        boto3.client: Configured S3 client.
    """
    session = boto3.session.Session()
    client = session.client(
        's3',
        config=Config(s3={'addressing_style': 'virtual'}),
        region_name=DO_SPACES_LOCATION,
        endpoint_url=DO_S3_ENDPOINT_URL,
        aws_access_key_id=DO_ACCESS_KEY_ID,
        aws_secret_access_key=DO_SECRET_ACCESS_KEY,
    )
    return client


def fetch_from_s3(filepath):
    """
    Fetch and load files from DigitalOcean Spaces using boto3.

    Parameters:
        filepath (str): Path to the file within the bucket.

    Returns:
        Various: Loaded file data depending on the file type.

    Raises:
        Exception: If there is an error fetching the file from S3.
        ValueError: If the file type is unsupported.
    """
    bucket_name = DO_STORAGE_BUCKET_NAME
    s3_client = get_s3_client()

    try:
        response = s3_client.get_object(Bucket=bucket_name, Key=os.path.join(DO_LOCATION, filepath))
        file_data = response['Body'].read()
    except Exception as e:
        raise Exception(f"Error fetching file from S3: {str(e)}")

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


def get_taxonomy_files(is_staff, taxonomy_level: str = "symptom") -> pd.DataFrame:
    """
    Create a DataFrame where each row represents a subject with connectivity files,
    and columns represent either symptoms, subdomains, or domains based on the taxonomy_level.

    Args:
        is_staff (bool): Indicates if the user is a staff member.
        taxonomy_level (str): One of ["symptom", "subdomain", "domain"].

    Returns:
        pd.DataFrame: DataFrame with connectivity file paths and binary columns for taxonomy items.

    Raises:
        ValueError: If taxonomy_level is not one of the specified options.
    """
    if taxonomy_level not in ["symptom", "subdomain", "domain"]:
        raise ValueError("taxonomy_level must be one of: symptom, subdomain, domain")

    session = get_session()

    try:
        # Retrieve subjects with relevant connectivity files
        subjects_with_conn = (
            session.query(Subject)
            .join(Subject.connectivity_files)
            .filter(ConnectivityFile.filetype.in_(['nii', 'nii.gz']))
            .distinct()
            .all()
        )

        if not is_staff:
            subjects_with_conn = [s for s in subjects_with_conn if not s.internal_use_only]

        # Prepare data for DataFrame
        data = []
        for subject in subjects_with_conn:
            conn_file = next(
                (cf.path for cf in subject.connectivity_files if cf.filetype in ['nii', 'nii.gz']),
                None
            )
            if conn_file:
                data.append({'subject_id': subject.id, 'conn': conn_file})

        df = pd.DataFrame(data)
        if df.empty:
            return df

        subject_ids = [s.id for s in subjects_with_conn]

        if taxonomy_level == "symptom":
            taxonomy_items = (
                session.query(Symptom)
                .join(Symptom.subjects)
                .filter(Subject.id.in_(subject_ids))
                .distinct()
                .all()
            )
            if not is_staff:
                taxonomy_items = [s for s in taxonomy_items if not s.internal_use_only]

            for symptom in taxonomy_items:
                df[f"symptom_{symptom.name}"] = df['subject_id'].apply(
                    lambda x: 1 if symptom in session.query(Subject).get(x).symptoms else 0
                )

        elif taxonomy_level == "subdomain":
            taxonomy_items = (
                session.query(Subdomain)
                .join(Subdomain.symptoms)
                .join(Symptom.subjects)
                .filter(Subject.id.in_(subject_ids))
                .distinct()
                .all()
            )

            for subdomain in taxonomy_items:
                df[f"subdomain_{subdomain.name}"] = df['subject_id'].apply(
                    lambda x: 1 if any(
                        symptom in session.query(Subject).get(x).symptoms
                        for symptom in subdomain.symptoms
                    ) else 0
                )

        else:  # domain
            taxonomy_items = (
                session.query(Domain)
                .join(Domain.subdomains)
                .join(Subdomain.symptoms)
                .join(Symptom.subjects)
                .filter(Subject.id.in_(subject_ids))
                .distinct()
                .all()
            )

            for domain in taxonomy_items:
                df[f"domain_{domain.name}"] = df['subject_id'].apply(
                    lambda x: 1 if any(
                        symptom in session.query(Subject).get(x).symptoms
                        for subdomain in domain.subdomains
                        for symptom in subdomain.symptoms
                    ) else 0
                )
    finally:
        session.close()

    return df


def get_taxonomy_columns(df: pd.DataFrame, taxonomy_level: str) -> list:
    """
    Retrieve all columns that correspond to a specific taxonomy level.

    Args:
        df (pd.DataFrame): DataFrame containing taxonomy columns.
        taxonomy_level (str): One of ["symptom", "subdomain", "domain"].

    Returns:
        list: List of column names for the specified taxonomy level.
    """
    return [col for col in df.columns if col.startswith(f"{taxonomy_level}_")]


def save_to_s3(nifti_image: nib.Nifti1Image, s3_path: str) -> str:
    buffer = BytesIO()
    nifti_image.to_file_map({'image': nib.FileHolder(fileobj=buffer)})
    buffer.seek(0)
    
    # Compress the data using gzip
    gzipped_buffer = BytesIO()
    with gzip.GzipFile(fileobj=gzipped_buffer, mode='wb') as gz_file:
        gz_file.write(buffer.getvalue())
    gzipped_buffer.seek(0)
    
    # Save to S3 using Django's default storage
    file_content = ContentFile(gzipped_buffer.read())
    saved_path = default_storage.save(s3_path, file_content)
    return saved_path


@shared_task(bind=True)
def decode_task_wrapper(self, taxonomy_level, user_uploaded_nifti_data, is_staff):
    """
    Wrapper for decode_task to handle progress updates.

    Args:
        taxonomy_level (str): The taxonomy level to group by.
        user_uploaded_nifti_data (bytes): The raw NIFTI data uploaded by the user.
        is_staff (bool): Indicates if the user is a staff member.

    Returns:
        dict: The result from decode_task.
    """
    return decode_task(taxonomy_level, user_uploaded_nifti_data, is_staff, task_instance=self)


@shared_task
def decode_task(taxonomy_level, user_uploaded_nifti_data, is_staff, task_instance=None):
    """
    Decode a NIFTI image and group results by taxonomy level.
    This function runs asynchronously as a Celery task.

    Args:
        taxonomy_level (str): The taxonomy level to group by ("symptom", "subdomain", "domain").
        user_uploaded_nifti_data (bytes): The raw NIFTI data uploaded by the user.
        is_staff (bool): Indicates if the user is a staff member.

    Returns:
        dict: Contains grouped results and raw results, or error messages.
    """
    # Reconstruct the in-memory NIFTI image
    if not isinstance(user_uploaded_nifti_data, nib.Nifti1Image):
        in_memory_nifti = nib.Nifti1Image.from_bytes(user_uploaded_nifti_data)
    else:
        in_memory_nifti = user_uploaded_nifti_data

    # Get the base dataframe with all taxonomy columns
    df = get_taxonomy_files(is_staff, taxonomy_level)
    if df.empty:
        return {'error': 'No taxonomy files found.'}

    # Set up the masker
    masker = NiftiMasker(mask_img=fetch_2mm_mni152_mask())
    masker.fit()

    # Transform the user uploaded NIFTI
    user_uploaded_nifti = np.squeeze(masker.transform(in_memory_nifti))

    df['spatial_correl'] = 0

    # Calculate correlations, but instead of df.apply, df.iterrows()
    for index, row in df.iterrows():
        df.loc[index, 'spatial_correl'] = np.corrcoef(user_uploaded_nifti, np.squeeze(masker.transform(fetch_from_s3(row['conn']))))[0, 1]
        if task_instance:
            task_instance.update_state(
                state='PROGRESS',
                meta={
                    'current': index,
                    'total': len(df),
                    'progress': int((index / len(df)) * 100),
                    'status': f'Calculating correlation for subject {index + 1} of {len(df)}'
                }
            )

    # Get relevant taxonomy columns
    taxonomy_cols = get_taxonomy_columns(df, taxonomy_level)
    if not taxonomy_cols:
        return {'error': f'No columns found for taxonomy level: {taxonomy_level}'}

    # Create results for each taxonomy item
    results = []
    for col in taxonomy_cols:
        relevant_correlations = df[df[col] == 1]['spatial_correl']
        if not relevant_correlations.empty:
            # Do a one-sample t-test on the correlations to see if they are significantly different from 0
            t_stat, p_val = ttest_1samp(relevant_correlations, 0)
            taxonomy_name = col.replace(f"{taxonomy_level}_", "")  # Remove prefix
            results.append({
                'taxonomy_item': taxonomy_name,
                'mean_correlation': relevant_correlations.mean(),
                't_statistic': t_stat,
                'std_correlation': relevant_correlations.std(),
                'n_subjects': len(relevant_correlations),
                'max_correlation': relevant_correlations.max(),
                'min_correlation': relevant_correlations.min()
            })

    # Convert results to DataFrame and sort
    results_df = pd.DataFrame(results)
    if not results_df.empty:
        results_df = results_df.sort_values('mean_correlation', ascending=False)

    # Return both grouped results and raw results
    return {
        'grouped_results': results_df.to_dict(orient='records'),
        'raw_results': df.to_dict(orient='records')
    }


def decode_from_generated_connectivity_map(paths_dict, taxonomy_level='symptom', is_staff=False, task_instance=None):
    connectivity_map_s3_path = paths_dict['connectivity_path']
    roi_s3_path = paths_dict['roi_path']

    connectivity_map_file = fetch_from_s3(connectivity_map_s3_path)
    results = decode_task(taxonomy_level, connectivity_map_file, is_staff, task_instance=task_instance)

    # Add URLs to the results
    results.update({
        'connectivity_map_url': default_storage.url(connectivity_map_s3_path),
        'lesion_mask_url': default_storage.url(roi_s3_path)
    })

    return results


def compute_connectivity_map(nifti_data_bytes, task_instance=None):
    try:
        roi_img = nib.Nifti1Image.from_bytes(nifti_data_bytes)
        pcc_config = config.Config(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'GSP1000_MF_91v_3209c.json'), stat='t', use_default_dir=False)
        brain_mask = datasets.get_img(pcc_config.get("mask"))
        roi_paths = tools.load_roi(roi_img)
        chunks = tools.get_chunks(roi_paths, pcc_config)
        atlas = {}
        current_timestamp_int = int(time.time())
        roi_path = save_to_s3(roi_img, f"generated_content/{current_timestamp_int}_roi.nii.gz")

        total_chunks = len(chunks)
        processed_chunks = 0
        progress = 0

        print(f"Found {total_chunks} chunks to process.")
        
        if task_instance:
            task_instance.update_state(
                state='PROGRESS',
                meta={
                    'current': processed_chunks,
                    'total': total_chunks,
                    'progress': progress,
                    'status': f'Processing chunk {processed_chunks} of {total_chunks}'
                }
            )

        for chunk in chunks:
            contribution = mapping.process_chunk(chunk, chunks[chunk], pcc_config, 't')
            atlas = mapping.update_atlas(contribution, atlas, 't')
            processed_chunks += 1
            progress = int((processed_chunks / total_chunks) * 100)
            
            print(f"Processed {processed_chunks} chunks. Progress: {progress}%")
            
            if task_instance:
                task_instance.update_state(
                    state='PROGRESS',
                    meta={
                        'current': processed_chunks,
                        'total': total_chunks,
                        'progress': progress,
                        'status': f'Processing chunk {processed_chunks} of {total_chunks}'
                    }
                )

        maps = mapping.publish_atlas(atlas, "", pcc_config, 't', save_to_dir=False)

        first_map = maps[0]
        for key, value in first_map.items():
            filename = f"generated_content/{current_timestamp_int}_connectivity.nii.gz"
            connectivity_path = save_to_s3(value, filename)
            return {'connectivity_path': connectivity_path, 'roi_path': roi_path}

        raise ValueError("No connectivity maps were generated.")
        
    except Exception as e:
        print(f"Error in compute_connectivity_map: {str(e)}")
        raise


@shared_task(bind=True)
def run_full_lesion_analysis(self, nifti_data_bytes, taxonomy_level='symptom', is_staff=False):
    try:
        # Step 1: Compute Connectivity Map
        self.update_state(
            state='PROGRESS',
            meta={
                'current_step': 1,
                'total_steps': 2,
                'progress': 10,
                'status': 'Starting connectivity map computation...'
            }
        )
        compute_result = compute_connectivity_map(nifti_data_bytes, task_instance=self)
        self.update_state(
            state='PROGRESS',
            meta={
                'current_step': 1,
                'total_steps': 2,
                'progress': 50,
                'status': 'Connectivity map computation completed.'
            }
        )

        # Step 2: Decode from Generated Connectivity Map
        self.update_state(
            state='PROGRESS',
            meta={
                'current_step': 2,
                'total_steps': 2,
                'progress': 60,
                'status': 'Starting decoding of connectivity map...'
            }
        )
        paths_dict = compute_result
        decode_result = decode_from_generated_connectivity_map(paths_dict, taxonomy_level, is_staff, task_instance=self)
        self.update_state(
            state='PROGRESS',
            meta={
                'current_step': 2,
                'total_steps': 2,
                'progress': 100,
                'status': 'Decoding completed.'
            }
        )
        return decode_result

    except Exception as e:
        print(f"Error in run_full_lesion_analysis: {str(e)}")
        raise
