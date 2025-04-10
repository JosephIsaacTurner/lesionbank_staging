from sklearn.utils import Bunch
from nilearn.datasets import load_mni152_brain_mask, fetch_atlas_juelich as fetch_atlas_juelich_nilearn, fetch_atlas_aal as fetch_atlas_aal_nilearn, fetch_atlas_harvard_oxford as fetch_atlas_harvard_oxford_nilearn
from nilearn.maskers import NiftiMasker, NiftiLabelsMasker
from nilearn.image import resample_img
from nibabel.affines import apply_affine
import os
import numpy as np
import pandas as pd
import nibabel as nib
import hashlib
import json
import logging
from typing import List, Optional, Tuple, Union, Dict
from sqlalchemy.exc import NoSuchTableError
from sqlalchemy_utils.models_sqlalchemy_orm import User, Base, Parcellation, Parcel, VoxelwiseValue, ParcelwiseConnectivityValue, ParcelwiseROIValue, ParcelwiseGroupLevelMapValue, Domain, Subdomain, Symptom, Synonym, MeshTerm, ResearchPaper, Subject, Connectome, ConnectivityFile, ROIFile, GroupLevelMapFile, Cause, Sex, Handedness, StatisticType, Dimension, ImageModality, PatientCohort, CoordinateSpace, CaseReport, MapType, Level, CaseReportSymptom
from sqlalchemy.orm import Session as _Session
from sqlalchemy import  and_, select
import warnings
import gzip
from io import BytesIO
from django.core.files.storage import default_storage
from PIL import Image
import environ
from pathlib import Path
from django.contrib.auth.hashers import make_password
from datetime import datetime
from django.conf import settings
from django.core.files.base import ContentFile
import re
from sqlalchemy.exc import IntegrityError
import os
import boto3
import environ
from botocore.client import Config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize environ
env = environ.Env()

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Read .env file
environ.Env.read_env(str(BASE_DIR / '.env'))

if not settings.configured:
    settings.configure()

# Initialize environment variables
DO_ACCESS_KEY_ID = env('DO_SPACES_ACCESS_KEY_ID')
DO_SECRET_ACCESS_KEY = env('DO_SPACES_SECRET_ACCESS_KEY')
DO_STORAGE_BUCKET_NAME = env('DO_SPACES_BUCKET_NAME')
DO_S3_ENDPOINT_URL = env('DO_SPACES_ENDPOINT_URL')
DO_SPACES_LOCATION = env('DO_SPACES_LOCATION', default='nyc3')
DO_LOCATION = env('DO_LOCATION')

"""Random helper functions"""

def numpy_to_python_type(value): return float(value) if hasattr(value, "dtype") and np.issubdtype(value.dtype, np.floating) else int(value) if hasattr(value, "dtype") and np.issubdtype(value.dtype, np.integer) else value

def md5_hash(input_data: Union[str, bytes, object]) -> str:
    """
    Computes the MD5 hash of the input data.
    
    Args:
        input_data (Union[str, bytes, object]): The input data can be a file path (str), bytes object, 
                                                or an instance of a class that can be converted to bytes.
        
    Returns:
        str: The MD5 hash of the input data.

    Notes:
        - The MD5 of the in-memory data will be different from the MD5 of the file on disk. 
        - I am not aware of any good workaround for this.
    """
    md5 = hashlib.md5()
    
    if isinstance(input_data, str):
        with open(input_data, 'rb') as f:
            for chunk in iter(lambda: f.read(4096), b""):
                md5.update(chunk)
    elif isinstance(input_data, bytes):
        md5.update(input_data)
    elif hasattr(input_data, 'to_bytes'):
        md5.update(input_data.to_bytes())
    elif hasattr(input_data, 'get_data'):
        md5.update(input_data.get_data().tobytes())
    elif hasattr(input_data, 'get_fdata'):
        md5.update(input_data.get_fdata().tobytes())
    elif isinstance(input_data, np.ndarray):
        md5.update(input_data.tobytes())
    elif hasattr(input_data, 'tobytes'):
        md5.update(input_data.tobytes())
    else:
        raise TypeError("Input data must be a string (file path), bytes object, or an instance with a 'to_bytes' or 'get_data' method.")
    
    return md5.hexdigest()

def determine_filetype(filepath: str) -> str:
    """
    Determines the filetype of a file based on its extension.
    """
    filetype_checks = {
        'nii.gz': lambda f: f.endswith('.nii.gz'),
        'nii': lambda f: '.nii' in f and not f.endswith('.nii.gz'),
        'npy': lambda f: f.endswith('.npy'),
        'npz': lambda f: f.endswith('.npz'),
        'gii': lambda f: f.endswith('.gii') or '.gii' in f,
        'mgz': lambda f: f.endswith('.mgz'),
        'surf': lambda f: any(s in f.lower() for s in ['lh.', 'rh.', '.surf']),
        'label': lambda f: '.label' in f.lower(),
        'annot': lambda f: '.annot' in f.lower(),
        'fsaverage': lambda f: 'fsaverage' in f.lower(),
        'freesurfer': lambda f: any(s in f.lower() for s in ['aparc', 'aseg', 'bert', 'curv', 'sulc', 'thickness']),
        'png': lambda f: f.endswith('.png'),
        'jpg': lambda f: f.endswith('.jpg') or f.endswith('.jpeg'),
        'trk.gz': lambda f: f.endswith('.trk.gz'),
        'trk': lambda f: f.endswith('.trk'),
        'edge': lambda f: f.endswith('.edge'),
        'mat': lambda f: f.endswith('.mat'),
        'jpeg': lambda f: f.endswith('.jpeg'),
        'gif': lambda f: f.endswith('.gif'),
        'pdf': lambda f: f.endswith('.pdf'),
        'txt': lambda f: f.endswith('.txt'),
        'csv': lambda f: f.endswith('.csv'),
        'xls': lambda f: f.endswith('.xls'),
        'xlsx': lambda f: f.endswith('.xlsx')
    }

    for filetype, check in filetype_checks.items():
        if check(filepath):
            return filetype
    
    return 'unknown'

def determine_coordinate_space(shape: Tuple[int, int, int], affine: np.ndarray) -> str:
    if shape == (91, 109, 91) and any(
        np.allclose(affine, ref_affine)
        for ref_affine in [
            np.array([[2.0, 0.0, 0.0, -90.0], [0.0, 2.0, 0.0, -126.0], [0.0, 0.0, 2.0, -72.0], [0.0, 0.0, 0.0, 1.0]]),
            np.array([[-2.0, 0.0, 0.0, 90.0], [0.0, 2.0, 0.0, -126.0], [0.0, 0.0, 2.0, -72.0], [0.0, 0.0, 0.0, 1.0]]),
        ]
    ):
        return '2mm'
    elif shape == (182, 218, 182) and any(
        np.allclose(affine, ref_affine)
        for ref_affine in [
            np.array([[1.0, 0.0, 0.0, -91.0], [0.0, 1.0, 0.0, -126.0], [0.0, 0.0, 1.0, -72.0], [0.0, 0.0, 0.0, 1.0]]),
            np.array([[-1.0, 0.0, 0.0, 91.0], [0.0, 1.0, 0.0, -126.0], [0.0, 0.0, 1.0, -72.0], [0.0, 0.0, 0.0, 1.0]]),
        ]
    ):
        return '1mm'
    else:
        return 'unknown'
    
def save_to_s3(array: np.ndarray, s3_path: str) -> str:
    buffer = BytesIO()
    np.save(buffer, array)
    buffer.seek(0)
    file_content = ContentFile(buffer.read())
    saved_path = default_storage.save(s3_path, file_content)
    return saved_path
    
def fetch_from_s3(filepath):
    extension = determine_filetype(filepath)

    with default_storage.open(filepath) as file:
        file_data = file.read()

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

"""Functions for manipulating imaging data itself"""

def fetch_2mm_mni152_mask(resolution=2):
    """Loads the MNI152 template in 2mm resolution with shape = (91, 109, 91)"""
    target_shape = (91, 109, 91)
    target_affine = np.array([[2, 0, 0, -90],
                              [0, 2, 0, -126],
                              [0, 0, 2, -72],
                              [0, 0, 0, 1]])
    return resample_img(
        load_mni152_brain_mask(resolution=resolution, threshold=0.10),
        target_affine=target_affine,
        target_shape=target_shape,
        interpolation='nearest'
    )

def add_name_attribute(name):
    def decorator(func):
        def wrapper(*args, **kwargs):
            result = func(*args, **kwargs)
            result.name = name
            return result
        return wrapper
    return decorator

@add_name_attribute('Harvard-Oxford Atlas')
def fetch_atlas_harvard_oxford(*args, **kwargs):
    return fetch_atlas_harvard_oxford_nilearn(*args, **kwargs)

@add_name_attribute('Juelich Atlas')
def fetch_atlas_juelich(*args, **kwargs):
    return fetch_atlas_juelich_nilearn(*args, **kwargs)

def fetch_atlas_biancardi_brainstem(data_dir='/Users/jt041/repos/db_engineering/biancardi_brainstem_atlas'):
    """
    Fetch the brainstem nuclei atlas and return as a Bunch object.
    
    Parameters:
    - data_dir: str, optional
        Path to the directory containing the atlas files.
    
    Returns:
    - Bunch object with 'maps', 'labels', and 'description'.
    """
    atlas_img_path = os.path.join(data_dir, 'brainstem_nuclei_atlas_2mm.nii.gz')
    labels_csv_path = os.path.join(data_dir, 'brainstem_nuclei_labels.csv')
    
    # Load the atlas image
    atlas_img = nib.load(atlas_img_path)
    
    # Load the labels
    labels_df = pd.read_csv(labels_csv_path)
    labels = labels_df['labels'].tolist()
    
    # Create and return the Bunch object
    atlas_bunch = Bunch(
        name='Biancardi Brainstem Nuclei Atlas',
        maps=atlas_img,
        labels=labels,
        description="Brainstem nuclei atlas resampled to 2mm MNI152 space.",
        filename=atlas_img_path
    )
    
    return atlas_bunch

def fetch_atlas_3209c91v():
    """Fetches the 3209c91v parcellation of the MNI152 brain."""
    path = os.path.join(os.path.dirname(__file__),'data/3209c91v.nii.gz')
    img = nib.load(path)
    unique_values = np.unique(img.get_fdata())
    unique_values = unique_values.astype(int).tolist()
    labels = ['Background' if value == 0 else f'Chunk {value}' for value in unique_values]
    description = """Parcellation of 2mm MNI152 brain voxels into 
                    3209 equally sized chunks of 91 voxels, 
                    courtesy of William Drew (MD/PhD Candidate at Columbia University)."""
    atlas_dict = {
        'name': '3209c91v',
        'filename': path,
        'maps': img,
        'labels': labels,
        'description': description
    }
    return Bunch(**atlas_dict)

def fetch_atlas_aal():
    """
    Fetches the AAL atlas from Nilearn, and modifies it to have consecutive indices.
    This step is necessary for compatibility with other atlas/parcellation schemes,
    and for using the NiftiLabelsMasker in Nilearn.
    """

    atlas = fetch_atlas_aal_nilearn()
    
    original_indices = [int(idx) for idx in atlas.indices]
    labels = atlas.labels
    consecutive_indices = list(range(1, len(original_indices) + 1))
    index_mapping = dict(zip(original_indices, consecutive_indices))

    atlas_img = nib.load(atlas.maps)
    atlas_data = atlas_img.get_fdata()

    modified_atlas_data = np.zeros_like(atlas_data)
    
    for original_idx, new_idx in index_mapping.items():
        modified_atlas_data[atlas_data == original_idx] = int(new_idx)

    modified_atlas_img = nib.Nifti1Image(modified_atlas_data.astype(np.int32), atlas_img.affine, atlas_img.header)

    modified_labels = ['Background'] + labels
    modified_indices = [0] + consecutive_indices

    modified_atlas = Bunch(
        name='AAL',
        maps=modified_atlas_img,
        labels=modified_labels,
        indices=modified_indices,
        description=atlas.description
    )

    return modified_atlas

def apply_parcellation(voxelwise_map, parcellation, strategy='mean', return_region_ids=False):
    """
    Uses nilearn to apply a parcellation to a brain map.
    Returns a 1d array of the parcel values.
    Can take the mean or sum of the data in each parcel (if both are true, it will take the mean).
    
    Params:
    - voxelwise_map: a 3d NIfTI image of the data.
    - parcellation: an sklearn bunch object with 'maps' and 'labels' attributes.
    - strategy: 'mean' or 'sum'
    Returns:
    - data: a 2d array of the data in each parcel of shape (n_samples, n_parcels)
    """    
    masker = NiftiLabelsMasker(labels_img=parcellation.maps, 
                               labels=parcellation.labels,
                               strategy=strategy)
    data = masker.fit_transform(voxelwise_map)
    if return_region_ids:
        region_ids = np.array(list(masker.region_ids_.values())[1:])
        return data, region_ids
    return data.astype(float)

"""SQL helper functions"""

def get_user_id(session: _Session, username: str = "josephturner") -> int:
    user = session.query(User).filter_by(username=username).first()
    if not user:
        user = User(
            username="josephturner",
            email="jiturner@bwh.harvard.edu",
            password=make_password(env('DEFAULT_PASSWORD')),
            first_name="Joseph",
            last_name="Turner",
            is_superuser=True,
            is_staff=True,
            is_active=True,
            date_joined=datetime.now()
        )
        session.add(user)
        session.commit()
    return user.id

def get_file_id(filepath, table, session):
    """
    Uses SQLAlchemy to get {map_type}_files.id where {map_type}_files.path = filepath.
    """
    result = session.query(table.id).filter(table.path == filepath).first()
    return result.id if result else None

def get_parcellation_id(parcellation_name, session):
    """
    Uses SQLAlchemy to get the id where parcellations.name = parcellation_name.
    """
    return session.query(Parcellation.id).filter(Parcellation.name == parcellation_name).scalar()

def get_parcel_id(parcellation_id, parcel_value, session):
    """
    Uses SQLAlchemy to get parcel.id where parcellations.id = parcellation_id AND parcels.value = parcel_value.
    """
    return session.query(Parcel.id).filter(Parcel.parcellation_id == parcellation_id, Parcel.value == parcel_value).scalar()

def get_labels_at_xyz(x: int, y: int, z: int, session: _Session) -> List[Tuple[Optional[str], Optional[str]]]:
    """
    Uses SQLAlchemy to get the labels of all parcels at the given MNI152 coordinates.
    Returns a list of tuples, where each tuple contains the label and the parcellation name.
    Note: Shouldn't there be a more efficient way to do this in one query? Regular SQL can do this with chained joins.
    """
    # Query to find all parcel_ids in VoxelwiseValue where the mni_x, mni_y, mni_z values match
    voxels = session.query(VoxelwiseValue).filter(
        and_(
            VoxelwiseValue.mni152_x == x,
            VoxelwiseValue.mni152_y == y,
            VoxelwiseValue.mni152_z == z
        )
    ).all()

    if not voxels:
        return []

    results = []

    for voxel in voxels:
        parcel = session.query(Parcel).filter(Parcel.id == voxel.parcel_id).first()
        if parcel is None:
            continue
        parcellation = session.query(Parcellation).filter(Parcellation.id == parcel.parcellation_id).first()
        if parcellation is None:
            continue
        results.append((parcel.label, parcellation.name))

    return results

def get_files_at_xyz(x: int, y: int, z: int, map_type: str, session: _Session) -> Dict[int, float]:
    """
    Returns a dict mapping subject_id to maximum value at the specified coordinates and map_type.
    """
    # Query to find all parcel_ids in VoxelwiseValue where the mni_x, mni_y, mni_z values match
    voxels = session.query(VoxelwiseValue).filter(
        and_(
            VoxelwiseValue.mni152_x == x,
            VoxelwiseValue.mni152_y == y,
            VoxelwiseValue.mni152_z == z
        )
    ).all()

    if not voxels:
        return {}

    # Determine the correct table and file relationship based on map_type
    if map_type == 'connectivity':
        ArrayTable = ParcelwiseConnectivityValue
        FileTable = ConnectivityFile
        file_id_attr = 'connectivity_file_id'
    elif map_type == 'roi':
        ArrayTable = ParcelwiseROIValue
        FileTable = ROIFile
        file_id_attr = 'roi_file_id'
    elif map_type == 'group_level_map':
        ArrayTable = ParcelwiseGroupLevelMapValue
        FileTable = GroupLevelMapFile
        file_id_attr = 'group_level_map_file_id'
    else:
        raise ValueError(f"Unknown map_type: {map_type}. Valid types are 'connectivity', 'roi', 'group_level_map'.")

    subject_value_dict = {}

    for voxel in voxels:
        # Query the appropriate ArrayTable for the given parcel_id
        arrays = session.query(ArrayTable).filter(ArrayTable.parcel_id == voxel.parcel_id).all()
        for array in arrays:
            # Query the FileTable for the given file ID
            file_id = getattr(array, file_id_attr)
            file = session.query(FileTable).filter(FileTable.id == file_id).first()
            if file:
                subject_id = file.subject_id
                value = np.round(array.value,2)
                # Update the subject's maximum value
                if subject_id in subject_value_dict:
                    subject_value_dict[subject_id] = max(subject_value_dict[subject_id], value)
                else:
                    subject_value_dict[subject_id] = value

    print("Successfully retrieved files at coordinates.")

    return subject_value_dict

"""Functions for inserting data into SQL tables"""
def data_to_voxelwise_values_table(parcellation, session):
    """
    Converts a parcellation to a data array in MNI152 template space (using the fetch_2mm_mni152_mask mask).
    Needs columns for parcel_id, mni152_x, mni152_y, mni152_z, and user_id. The primary key is an incremented integer
    assigned by SQL.
    Use get_parcel_id to get the parcel_id, looking for the parcel with the same value and parcellation name.

        This is different from data_to_parcelwise_values_table because it is in MNI152 space, not in the parcellation space.

    Inserts into: `voxelwise_values` table in SQL.
    Saves a npz file with the voxel data.
    """
    mask_img = fetch_2mm_mni152_mask()
    masker = NiftiMasker(mask_img=mask_img).fit()
    
    parcellation_values = masker.transform(parcellation.maps).ravel().astype(int) # These are the parcel values at each voxel;
    mask_indices = np.nonzero(mask_img.get_fdata().astype(bool))
    coords = apply_affine(mask_img.affine, np.column_stack(mask_indices))
    parcel_id_map = {value: get_parcel_id(get_parcellation_id(parcellation.name, session), numpy_to_python_type(value), session) for value in np.unique(parcellation_values)}
    parcel_ids = np.array([parcel_id_map[numpy_to_python_type(value)] for value in parcellation_values])
    results = np.column_stack((parcel_ids, coords))

    default_user_id = get_user_id(session)
    
    # Prepare a list of dictionaries for bulk insertion
    records = [
        {
            'parcel_id': numpy_to_python_type(row[0]),
            'mni152_x': numpy_to_python_type(row[1]),
            'mni152_y': numpy_to_python_type(row[2]),
            'mni152_z': numpy_to_python_type(row[3]),
            'user_id': default_user_id  # Set the default user_id
        }
        for row in results
    ]
    
    # Check for existing records and filter out the redundant ones
    existing_records = set(
        (v.parcel_id, v.mni152_x, v.mni152_y, v.mni152_z) for v in session.query(
            VoxelwiseValue.parcel_id, VoxelwiseValue.mni152_x, VoxelwiseValue.mni152_y, VoxelwiseValue.mni152_z
        ).all()
    )
    
    new_records = [record for record in records if (
        record['parcel_id'], record['mni152_x'], record['mni152_y'], record['mni152_z']) not in existing_records]
    
    if new_records:
        session.bulk_insert_mappings(VoxelwiseValue, new_records)
        session.commit()

def file_to_file_table(filepath, parcellation, map_type, session, 
                       statistic_type=None, 
                       control_cohort=None, 
                       threshold=None,
                       research_paper_id=None,
                       subject_id=None,
                       connectome_id=None,
                       is_surface=False,
                       is_volume=False,
                       is_2d=False,
                       is_3d=False,
                       override_existing=False):
    """
    Converts a file to a row in the connectivity_files, roi_files, or group_level_map_files table (depending on map_type).
    """
    # Determine the appropriate table and record structure based on map_type
    record = {'path': filepath, 'md5': md5_hash(filepath), 'user_id': get_user_id(session)}
    table, record_updates = None, {}

    if map_type == 'connectivity':
        table, record_updates = ConnectivityFile, {
            'subject_id': subject_id, 'connectome_id': connectome_id, 'is_surface': is_surface,
            'is_volume': is_volume, 'statistic_type': statistic_type
        }
    elif map_type == 'roi':
        table, record_updates = ROIFile, {
            'subject_id': subject_id, 'is_2d': is_2d, 'is_3d': is_3d
        }
    elif map_type == 'group_level_map':
        table, record_updates = GroupLevelMapFile, {
            'research_paper_id': research_paper_id, 'control_cohort': control_cohort, 'threshold': threshold
        }
    else:
        raise ValueError("map_type must be 'connectivity', 'roi', or 'group_level_map'.")

    record.update(record_updates)
    record['parcellation_id'] = get_parcellation_id(parcellation.name, session)
    record['filetype'] = determine_filetype(filepath)

    try:
        # Check for existing file by path or md5
        existing_file = session.query(table).filter((table.path == filepath) | (table.md5 == record['md5'])).first()

        if existing_file:
            if override_existing:
                # Delete existing file and associated arrays
                session.query(table).filter_by(id=existing_file.id).delete(synchronize_session=False)
                logger.info(f"Overriding and deleting existing file with path {filepath} or md5 {record['md5']}.")
            else:
                logger.info(f"File with path {filepath} or md5 {record['md5']} already exists. Not overriding.")
                return

        # Add the new record
        session.add(table(**record))
        session.commit()
        logger.info(f"File with path {filepath} added to the database.")

    except NoSuchTableError:
        logger.error(f"Table {table.__tablename__} does not exist in the database.")
    except Exception as e:
        logger.error(f"An error occurred: {str(e)}")
        session.rollback()

def data_to_parcelwise_values_table(voxelwise_map, parcellation, map_type, session, strategy='mean', voxelwise_map_name=None):
    """
    Converts a parcelwise data array from apply_parcellation to a dataframe.
    Inserts into: parcelwise_connectivity_values, parcelwise_roi_values, or group_level_map_arrays table in SQL.
    """
    print("Inserting data into the database...")
    try:
        if voxelwise_map_name is None:
            voxelwise_map_name = voxelwise_map
        # Apply parcellation and get parcel IDs
        parcelwise_array, region_ids = apply_parcellation(voxelwise_map, parcellation, strategy=strategy, return_region_ids=True)
        parcel_ids = np.array([get_parcel_id(get_parcellation_id(parcellation.name, session), numpy_to_python_type(value), session) for value in region_ids])
        parcel_ids_values = np.column_stack((parcel_ids, parcelwise_array.ravel()))

        original_file_id = re.search(r"_file-(\d+)_", voxelwise_map_name).group(1) if re.search(r"_file-(\d+)_", voxelwise_map_name) else None
        new_file_id = int(original_file_id) + 1 if original_file_id else 1
        extension = determine_filetype(voxelwise_map_name)
        parcelwise_map_filepath = voxelwise_map_name.replace(f'.{extension}', f'_parcellation-{parcellation.name}.npy')
        if original_file_id:
            parcelwise_map_filepath = parcelwise_map_filepath.replace(f'_file-{original_file_id}', f'_file-{new_file_id}')
        save_to_s3(parcelwise_array.astype(np.float32), parcelwise_map_filepath)

        # Determine the appropriate table and file table based on map_type
        if map_type == 'connectivity':
            table = ParcelwiseConnectivityValue
            file_table = ConnectivityFile
        elif map_type == 'roi':
            table = ParcelwiseROIValue
            file_table = ROIFile
        elif map_type == 'group_level_map':
            table = ParcelwiseGroupLevelMapValue
            file_table = GroupLevelMapFile
        else:
            raise ValueError("map_type must be 'connectivity', 'roi', or 'group_level_map'.")

        file_in_db = session.query(file_table).filter(file_table.path == voxelwise_map_name).first()
        print(file_table, voxelwise_map_name)

        if not file_in_db:
            raise ValueError(f"No {file_table.__name__} found with path '{voxelwise_map_name}'.")

        print(file_in_db.id)  # Now, this should not raise an error if file_in_db exists

        default_user_id = get_user_id(session)
        parcellation_id = get_parcellation_id(parcellation.name, session)
        file_data = file_in_db.__dict__.copy()
        file_data.pop('_sa_instance_state', None)
        file_data.pop('id', None)
        file_data.pop('insert_date', None)
        file_data.update({
            'path': parcelwise_map_filepath,
            'md5': md5_hash(parcelwise_array),
            'parcellation_id': parcellation_id,
            'filetype': 'npy',
            'user_id': default_user_id,
        })
        new_file = file_table(**file_data)
        session.add(new_file)
        session.flush()

        # Prepare records for insertion
        records = [
            {
                f'{map_type}_file_id': new_file.id,
                'parcel_id': numpy_to_python_type(row[0]),
                'value': numpy_to_python_type(row[1]),
                'user_id': default_user_id  # Set the default user_id
            }
            for row in parcel_ids_values
        ]

        # Check for existing records
        existing_records = set(
            (r.parcel_id, r.value) for r in session.query(
                table.parcel_id, table.value
            ).filter_by(**{f'{map_type}_file_id': new_file.id}).all()
        )

        # Filter new records to insert
        new_records = [record for record in records if (record['parcel_id'], record['value']) not in existing_records]

        # Optional: Filter out where the value is 0
        new_records = [record for record in new_records if record['value'] != 0]

        # Insert new records if any
        if new_records:
            session.bulk_insert_mappings(table, new_records)
            session.commit()
            print(f"Data added to the {map_type}_arrays table in the database.")
        else:
            print("No new records to add")

    except Exception as e:
        print(f"An error occurred: {str(e)}")
        session.rollback()
    finally:
        session.close()
    
def parcellation_to_parcellation_table(parcellation, session: _Session):
    """
    Converts a parcellation to a row in the parcellations table.
    Parcellation: a nilearn parcellation object. Must have name, description, path.
    """
    try:
        # Check if the parcellation already exists
        existing_parcellation = session.query(Parcellation).filter_by(name=parcellation.name).first()
        
        if existing_parcellation:
            print(f"Parcellation with name {parcellation.name} already exists.")
            return
        
        default_user_id = get_user_id(session)
        
        record = {
            'name': parcellation.name,
            'description': parcellation.description,
            'user_id': default_user_id  # Set the default user_id
        }
        
        if getattr(parcellation, 'filename', None):
            record['path'] = parcellation.filename
            record['md5'] = md5_hash(parcellation.filename)
        else:
            record['md5'] = md5_hash(parcellation.maps)
        
        session.add(Parcellation(**record))
        session.commit()
        print(f"Parcellation with name {parcellation.name} added to the database.")
    except Exception as e:
        print(f"An error occurred: {str(e)}")
        session.rollback()
    finally:
        session.close()

def delete_dependent_arrays_and_return_data(parcellation_id: int, session: _Session) -> dict:
    data = {
        'voxelwise_values': [],
        'parcelwise_connectivity_values': [],
        'parcelwise_roi_values': [],
        'group_level_map_arrays': []
    }
    
    try:
        # Delete and return data for VoxelwiseValue
        voxelwise_values = session.query(VoxelwiseValue).join(Parcel).filter(Parcel.parcellation_id == parcellation_id).all()
        for v in voxelwise_values:
            data['voxelwise_values'].append({
                'id': v.id,
                'mni152_x': v.mni152_x,
                'mni152_y': v.mni152_y,
                'mni152_z': v.mni152_z,
                'parcel_id': v.parcel_id,
                'user_id': v.user_id
            })
        session.query(VoxelwiseValue).filter(VoxelwiseValue.id.in_([v.id for v in voxelwise_values])).delete(synchronize_session=False)

        # Delete and return data for ParcelwiseConnectivityValue
        parcelwise_connectivity_values = session.query(ParcelwiseConnectivityValue).join(Parcel).filter(Parcel.parcellation_id == parcellation_id).all()
        for c in parcelwise_connectivity_values:
            data['parcelwise_connectivity_values'].append({
                'id': c.id,
                'value': c.value,
                'connectivity_file_id': c.connectivity_file_id,
                'parcel_id': c.parcel_id,
                'user_id': c.user_id
            })
        session.query(ParcelwiseConnectivityValue).filter(ParcelwiseConnectivityValue.id.in_([c.id for c in parcelwise_connectivity_values])).delete(synchronize_session=False)

        # Delete and return data for ParcelwiseROIValue
        parcelwise_roi_values = session.query(ParcelwiseROIValue).join(Parcel).filter(Parcel.parcellation_id == parcellation_id).all()
        for r in parcelwise_roi_values:
            data['parcelwise_roi_values'].append({
                'id': r.id,
                'value': r.value,
                'roi_file_id': r.roi_file_id,
                'parcel_id': r.parcel_id,
                'user_id': r.user_id
            })
        session.query(ParcelwiseROIValue).filter(ParcelwiseROIValue.id.in_([r.id for r in parcelwise_roi_values])).delete(synchronize_session=False)

        # Delete and return data for ParcelwiseGroupLevelMapValue
        group_level_map_arrays = session.query(ParcelwiseGroupLevelMapValue).join(Parcel).filter(Parcel.parcellation_id == parcellation_id).all()
        for g in group_level_map_arrays:
            data['group_level_map_arrays'].append({
                'id': g.id,
                'value': g.value,
                'group_level_map_files_id': g.group_level_map_files_id,
                'parcel_id': g.parcel_id,
                'user_id': g.user_id
            })
        session.query(ParcelwiseGroupLevelMapValue).filter(ParcelwiseGroupLevelMapValue.id.in_([g.id for g in group_level_map_arrays])).delete(synchronize_session=False)
        
        session.commit()
    except Exception as e:
        print(f"An error occurred: {str(e)}")
        session.rollback()
    finally:
        session.close()
    
    return data

def reinsert_dependent_arrays(data: dict, session: _Session):
    """
    Reinserts dependent arrays into their respective tables.
    """
    try:
        if data['voxelwise_values']:
            session.bulk_insert_mappings(VoxelwiseValue, data['voxelwise_values'])
        
        if data['parcelwise_connectivity_values']:
            session.bulk_insert_mappings(ParcelwiseConnectivityValue, data['parcelwise_connectivity_values'])
        
        if data['parcelwise_roi_values']:
            session.bulk_insert_mappings(ParcelwiseROIValue, data['parcelwise_roi_values'])
        
        if data['group_level_map_arrays']:
            session.bulk_insert_mappings(ParcelwiseGroupLevelMapValue, data['group_level_map_arrays'])
        
        session.commit()
        print("Finished reinserting dependent arrays.")
    except Exception as e:
        print(f"An error occurred: {str(e)}")
        session.rollback()
    finally:
        session.close()

def parcellation_to_parcels_table(parcellation: Bunch, session: _Session, override_existing: Optional[bool] = False):
    """
    Converts a parcellation to a list of parcels, and inserts them into the parcels table.
    The parcels table has columns id, value, label, parcellation_id, along with user_id and insert_date.
    The function works just fine, but we want to add the option for override_existing. 
    This could be complex because voxelwise_values, parcelwise_connectivity_values, parcelwise_roi_values, and group_level_map_arrays all depend on parcels.
    We want a function that deletes the arrays that depend on parcels, but returns the data in them as a dictionary, so that
    we can re-build them after the parcels are re-inserted (overridden).
    """
    try:
        # Ensure the parcellation record exists and get its ID
        parcellation_record = session.query(Parcellation).filter_by(name=parcellation.name).first()
        if not parcellation_record:
            parcellation_to_parcellation_table(parcellation, session)
            parcellation_record = session.query(Parcellation).filter_by(name=parcellation.name).first()
        
        parcellation_id = parcellation_record.id

        # Prepare the masker and labels
        image = fetch_2mm_mni152_mask()
        masker = NiftiLabelsMasker(labels_img=parcellation.maps, labels=parcellation.labels, strategy='mean')
        masker.fit_transform(image)
        labels = parcellation.labels
        parcel_values = masker.labels_img_.get_fdata().ravel()
        unique_values = np.unique(parcel_values)
        
        if len(labels) != len(unique_values):
            warnings.warn("Mismatch between the number of labels and unique parcel values. "
                          "Got {} labels and {} unique values.".format(len(labels), len(unique_values)))
        
        parcel_value_label_pairs = {int(value): labels[int(value)] for value in unique_values}

        # Get default user ID
        default_user_id = get_user_id(session)

        # Build the parcel records
        all_records = [
            {'parcellation_id': parcellation_id, 'value': int(value), 'label': label, 'user_id': default_user_id}
            for value, label in parcel_value_label_pairs.items()
        ]

        if override_existing:
            dependent_data = delete_dependent_arrays_and_return_data(parcellation_id, session)
            session.query(Parcel).filter_by(parcellation_id=parcellation_id).delete(synchronize_session=False)
            session.bulk_insert_mappings(Parcel, all_records)
            reinsert_dependent_arrays(dependent_data, session)
        else:
            existing_parcels = set(
                (p.parcellation_id, p.value) for p in session.query(Parcel.parcellation_id, Parcel.value)
                .filter_by(parcellation_id=parcellation_id).all()
            )

            new_records = [
                record for record in all_records if (record['parcellation_id'], record['value']) not in existing_parcels
            ]

            if new_records:
                session.bulk_insert_mappings(Parcel, new_records)
        
        session.commit()
    except Exception as e:
        print(f"An error occurred: {str(e)}")
        session.rollback()
    finally:
        session.close()

"""
Functions to pre-populate certain tables with data from JSON files.
"""

def remove_symptom_from_db(id: int, session: _Session) -> dict:
    """
    Removes a symptom and associated synonyms from the database, but returns a JSON copy of the symptom data and its synonyms.

    Args:
        id (int): The ID of the symptom to remove.
        session (Session): The SQLAlchemy session object for database operations.

    Returns:
        dict: A dictionary containing the symptom data and its synonyms.
    """
    # Query the symptom by ID
    symptom = session.query(Symptom).filter_by(id=id).one_or_none()
    
    if not symptom:
        raise ValueError(f"No symptom found with ID {id}")

    # Extract symptom data
    symptom_data = {
        "name": symptom.name,
        "description": symptom.description,
        "domain_id": symptom.domain_id,
        "subdomain_id": symptom.subdomain_id,
        "synonyms": [synonym.name for synonym in symptom.synonyms],
        "mesh_terms": [mesh_term.name for mesh_term in symptom.mesh_terms]
    }

    # Remove associated synonyms and mesh terms
    session.query(Synonym).filter_by(symptom_id=id).delete()
    session.query(MeshTerm).filter_by(symptom_id=id).delete()

    # Remove the symptom
    session.delete(symptom)
    session.commit()

    # Update user_id for tracking
    default_user_id = get_user_id(session)
    symptom.user_id = default_user_id
    session.commit()

    return symptom_data

def insert_map_types_from_json(json_path: str, session: _Session, override_existing: Optional[bool] = False):
    """
    Parses a JSON file and inserts MapTypes into the database, avoiding duplicates.

    Args:
        json_path (str): The path to the JSON file containing MapType data.
        session (Session): The SQLAlchemy session object for database operations.
        override_existing (bool): If True, existing records will be replaced with new data.
    """
    try:
        with open(json_path, 'r') as file:
            map_types_data = json.load(file)

        default_user_id = get_user_id(session)

        for map_type_data in map_types_data:
            existing_map_type = session.execute(
                select(MapType).filter_by(name=map_type_data['name'])
            ).scalar_one_or_none()

            if existing_map_type is None:
                new_map_type = MapType(
                    name=map_type_data.get('name'),
                    description=map_type_data.get('description'),
                    user_id=default_user_id  # Set the default user_id
                )
                session.add(new_map_type)
                print(f"Added new MapType: {new_map_type.name}")
            elif override_existing:
                session.delete(existing_map_type)
                session.flush()  # Ensure the existing MapType is removed
                new_map_type = MapType(
                    name=map_type_data.get('name'),
                    description=map_type_data.get('description'),
                    user_id=default_user_id  # Set the default user_id
                )
                session.add(new_map_type)
                print(f"Replaced existing MapType: {new_map_type.name}")
            else:
                print(f"MapType '{existing_map_type.name}' already exists. Skipping.")

        session.commit()

        map_types = session.query(MapType).all()
        print(f"There are now {len(map_types)} MapTypes in the database.")

    except Exception as e:
        print(f"An error occurred: {str(e)}")
        session.rollback()
    finally:
        session.close()

def insert_dimensions_from_json(json_path: str, session: _Session, override_existing: Optional[bool] = False):
    """
    Parses a JSON file and inserts statistic types into the database, avoiding duplicates.

    Args:
        json_path (str): The path to the JSON file containing dimension data.
        session (Session): The SQLAlchemy session object for database operations.
        override_existing (bool): If true, existing records will be replaced with new data.
    
    Returns:
        None
    """
    try:
        with open(json_path, 'r') as file:
            dimensions_data = json.load(file)

        default_user_id = get_user_id(session)

        for dimension in dimensions_data:
            existing_dimension = session.execute(
                select(Dimension).filter_by(name=dimension['name'])
            ).scalar_one_or_none()

            if existing_dimension is None:
                new_dimension = Dimension(
                    name=dimension.get('name'),
                    description=dimension.get('description'),
                    user_id=default_user_id  # Set the default user_id
                )
                session.add(new_dimension)
            elif override_existing:
                session.delete(existing_dimension)
                session.flush()
                new_dimension = Dimension(
                    name=dimension.get('name'),
                    description=dimension.get('description'),
                    user_id=default_user_id  # Set the default user_id
                )
                session.add(new_dimension)

        session.commit()

        dimensions = session.query(Dimension).all()
        print(f"There are now {len(dimensions)} dimensions in the database.")

    except Exception as e:
        print(f"An error occurred: {str(e)}")
        session.rollback()
    finally:
        session.close()   

def insert_modalities_from_json(json_path: str, session: _Session, override_existing: Optional[bool] = False):
    """
    Parses a JSON file and inserts modalities into the database, avoiding duplicates.

    Args:
        json_path (str): The path to the JSON file containing modality data.
        session (Session): The SQLAlchemy session object for database operations.
        override_existing (bool): If true, existing records will be replaced with new data.
    
    Returns:
        None
    """
    try:
        with open(json_path, 'r') as file:
            modalities_data = json.load(file)

        default_user_id = get_user_id(session)

        for modality in modalities_data:
            existing_modality = session.execute(
                select(ImageModality).filter_by(name=modality['name'])
            ).scalar_one_or_none()

            if existing_modality is None:
                new_modality = ImageModality(
                    name=modality.get('name'),
                    description=modality.get('description'),
                    user_id=default_user_id  # Set the default user_id
                )
                session.add(new_modality)
            elif override_existing:
                session.delete(existing_modality)
                session.flush()
                new_modality = ImageModality(
                    name=modality.get('name'),
                    description=modality.get('description'),
                    user_id=default_user_id  # Set the default user_id
                )
                session.add(new_modality)

        session.commit()

        modalities = session.query(ImageModality).all()
        print(f"There are now {len(modalities)} modalities in the database.")

    except Exception as e:
        print(f"An error occurred: {str(e)}")
        session.rollback()
    finally:
        session.close()

def insert_statistic_types_from_json(json_path: str, session: _Session, override_existing: Optional[bool] = False):
    """
    Parses a JSON file and inserts statistic types into the database, avoiding duplicates.

    Args:
        json_path (str): The path to the JSON file containing statistic type data.
        session (Session): The SQLAlchemy session object for database operations.
        override_existing (bool): If true, existing records will be replaced with new data.
    
    Returns:
        None
    """
    try:
        with open(json_path, 'r') as file:
            statistic_types_data = json.load(file)

        default_user_id = get_user_id(session)

        for statistic_type in statistic_types_data:
            existing_statistic_type = session.execute(
                select(StatisticType).filter_by(name=statistic_type['name'])
            ).scalar_one_or_none()

            if existing_statistic_type is None:
                new_statistic_type = StatisticType(
                    name=statistic_type.get('name'),
                    code=statistic_type.get('code'),
                    description=statistic_type.get('description'),
                    user_id=default_user_id  # Set the default user_id
                )
                session.add(new_statistic_type)
            elif override_existing:
                session.delete(existing_statistic_type)
                session.flush()
                new_statistic_type = StatisticType(
                    name=statistic_type.get('name'),
                    code=statistic_type.get('code'),
                    description=statistic_type.get('description'),
                    user_id=default_user_id  # Set the default user_id
                )
                session.add(new_statistic_type)

        session.commit()

        statistic_types = session.query(StatisticType).all()
        print(f"There are now {len(statistic_types)} statistic types in the database.")

    except Exception as e:
        print(f"An error occurred: {str(e)}")
        session.rollback()
    finally:
        session.close()          

def insert_connectomes_from_json(json_path: str, session: _Session, override_existing: Optional[bool] = False):
    """
    Parses a JSON file and inserts connectomes into the database, avoiding duplicates.

    Args:
        json_path (str): The path to the JSON file containing connectome data.
        session (Session): The SQLAlchemy session object for database operations.
        override_existing (bool): If true, existing records will be replaced with new data.
    """
    try:
        with open(json_path, 'r') as file:
            connectomes_data = json.load(file)

        default_user_id = get_user_id(session)

        for connectome in connectomes_data:
            existing_connectome = session.execute(
                select(Connectome).filter_by(name=connectome['name'])
            ).scalar_one_or_none()

            if existing_connectome is None:
                new_connectome = Connectome(
                    name=connectome.get('name'),
                    connectome_type=connectome.get('connectome_type'),
                    description=connectome.get('description'),
                    user_id=default_user_id  # Set the default user_id
                )
                session.add(new_connectome)
            elif override_existing:
                session.delete(existing_connectome)
                session.flush()  # Ensure the existing connectome is removed
                new_connectome = Connectome(
                    name=connectome.get('name'),
                    connectome_type=connectome.get('connectome_type'),
                    description=connectome.get('description'),
                    user_id=default_user_id  # Set the default user_id
                )
                session.add(new_connectome)

        session.commit()

        connectomes = session.query(Connectome).all()
        print(f"There are now {len(connectomes)} connectomes in the database.")

    except Exception as e:
        print(f"An error occurred: {str(e)}")
        session.rollback()
    finally:
        session.close()

def insert_coordinate_spaces_from_json(json_path: str, session: _Session, override_existing: Optional[bool] = False):
    """
    Parses a JSON file and inserts coordinate spaces into the database, avoiding duplicates.

    Args:
        json_path (str): The path to the JSON file containing coordinate space data.
        session (Session): The SQLAlchemy session object for database operations.
        override_existing (bool): If true, existing records will be replaced with new data.
    """
    try:
        with open(json_path, 'r') as file:
            coordinate_spaces_data = json.load(file)

        default_user_id = get_user_id(session)

        for coordinate_space in coordinate_spaces_data:
            existing_coordinate_space = session.execute(
                select(CoordinateSpace).filter_by(name=coordinate_space['name'])
            ).scalar_one_or_none()

            if existing_coordinate_space is None:
                new_coordinate_space = CoordinateSpace(
                    name=coordinate_space.get('name'),
                    user_id=default_user_id
                )
                session.add(new_coordinate_space)
            elif override_existing:
                session.delete(existing_coordinate_space)
                session.flush()  # Ensure the existing coordinate space is removed
                new_coordinate_space = CoordinateSpace(
                    name=coordinate_space.get('name'),
                    user_id=default_user_id
                )
                session.add(new_coordinate_space)

        session.commit()

        coordinate_spaces = session.query(CoordinateSpace).all()
        print(f"There are now {len(coordinate_spaces)} coordinate spaces in the database.")

    except Exception as e:
        print(f"An error occurred: {str(e)}")
        session.rollback()
    finally:
        session.close()

def insert_handedness_from_json(json_path: str, session: _Session, override_existing: Optional[bool] = False):
    """
    Parses a JSON file and inserts handedness into the database, avoiding duplicates.

    Args:
        json_path (str): The path to the JSON file containing handedness data.
        session (Session): The SQLAlchemy session object for database operations.
        override_existing (bool): If true, existing records will be replaced with new data.
    """
    try:
        with open(json_path, 'r') as file:
            handedness_data = json.load(file)

        default_user_id = get_user_id(session)

        for handedness in handedness_data:
            existing_handedness = session.execute(
                select(Handedness).filter_by(name=handedness['name'])
            ).scalar_one_or_none()

            if existing_handedness is None:
                new_handedness = Handedness(
                    name=handedness.get('name'),
                    user_id=default_user_id  # Set the default user_id
                )
                session.add(new_handedness)
            elif override_existing:
                session.delete(existing_handedness)
                session.flush()  # Ensure the existing handedness is removed
                new_handedness = Handedness(
                    name=handedness.get('name'),
                    user_id=default_user_id  # Set the default user_id
                )
                session.add(new_handedness)

        session.commit()

        handedness_records = session.query(Handedness).all()
        print(f"There are now {len(handedness_records)} handedness records in the database.")

    except Exception as e:
        print(f"An error occurred: {str(e)}")
        session.rollback()
    finally:
        session.close()

def insert_sexes_from_json(json_path: str, session: _Session, override_existing: Optional[bool] = False):
    """
    Parses a JSON file and inserts sexes into the database, avoiding duplicates.

    Args:
        json_path (str): The path to the JSON file containing sex data.
        session (Session): The SQLAlchemy session object for database operations.
        override_existing (bool): If true, existing records will be replaced with new data.
    """
    try:
        with open(json_path, 'r') as file:
            sexes_data = json.load(file)

        default_user_id = get_user_id(session)

        for sex in sexes_data:
            existing_sex = session.execute(
                select(Sex).filter_by(name=sex['name'])
            ).scalar_one_or_none()

            if existing_sex is None:
                new_sex = Sex(
                    name=sex.get('name'),
                    user_id=default_user_id  # Set the default user_id
                )
                session.add(new_sex)
            elif override_existing:
                session.delete(existing_sex)
                session.flush()  # Ensure the existing sex is removed
                new_sex = Sex(
                    name=sex.get('name'),
                    user_id=default_user_id  # Set the default user_id
                )
                session.add(new_sex)

        session.commit()

        sexes = session.query(Sex).all()
        print(f"There are now {len(sexes)} sexes in the database.")

    except Exception as e:
        print(f"An error occurred: {str(e)}")
        session.rollback()
    finally:
        session.close()

def insert_domains_from_json(json_file_path: str, db_session: _Session, override_existing: Optional[bool] = False):
    """
    Parses a JSON file and inserts domains and subdomains into the database, avoiding duplicates.

    Args:
        json_file_path (str): The path to the JSON file containing domain data.
        db_session (Session): The SQLAlchemy session object for database operations.
        override_existing (bool): If true, existing records will be replaced with new data.
    """
    try:
        with open(json_file_path, 'r') as file:
            data = json.load(file)

        default_user_id = get_user_id(db_session)

        for domain_data in data:
            existing_domain = db_session.execute(
                select(Domain).filter_by(name=domain_data['name'])
            ).scalar_one_or_none()

            if existing_domain and override_existing:
                # Remove all symptoms associated with the existing domain
                associated_symptoms = db_session.query(Symptom).filter_by(domain_id=existing_domain.id).all()
                for symptom in associated_symptoms:
                    remove_symptom_from_db(symptom.id, db_session)
                
                # Delete all subdomains associated with the existing domain
                db_session.query(Subdomain).filter_by(domain_id=existing_domain.id).delete()
                db_session.flush()  # Ensure subdomains are removed

                # Delete the existing domain
                db_session.delete(existing_domain)
                db_session.flush()  # Ensure the existing domain is removed
                existing_domain = None  # Clear the reference to the existing domain

            if existing_domain is None:
                domain = Domain(
                    name=domain_data['name'],
                    description=domain_data.get('description', None),
                    user_id=default_user_id  # Set the default user_id
                )
                db_session.add(domain)
                db_session.flush()  # Ensure domain.id is populated
            else:
                domain = existing_domain

            for subdomain_data in domain_data.get('subdomains', []):
                existing_subdomain = db_session.execute(
                    select(Subdomain).filter_by(name=subdomain_data['name'], domain_id=domain.id)
                ).scalar_one_or_none()

                if existing_subdomain and override_existing:
                    db_session.delete(existing_subdomain)
                    db_session.flush()  # Ensure the existing subdomain is removed
                    existing_subdomain = None  # Clear the reference to the existing subdomain

                if existing_subdomain is None:
                    subdomain = Subdomain(
                        name=subdomain_data['name'],
                        description=subdomain_data.get('description', None),
                        domain_id=domain.id,
                        user_id=default_user_id  # Set the default user_id for subdomains
                    )
                    db_session.add(subdomain)

        db_session.commit()

        domains = db_session.query(Domain).all()
        print(f"There are now {len(domains)} domains in the database.")

        subdomains = db_session.query(Subdomain).all()
        print(f"There are now {len(subdomains)} subdomains in the database.")

    except Exception as e:
        print(f"An error occurred: {str(e)}")
        db_session.rollback()
    finally:
        db_session.close()


# Function to get S3 client
def get_s3_client():
    session = boto3.session.Session()
    client = session.client('s3',
        config=Config(s3={'addressing_style': 'virtual'}),
        region_name=DO_SPACES_LOCATION,
        endpoint_url=DO_S3_ENDPOINT_URL,
        aws_access_key_id=DO_ACCESS_KEY_ID,
        aws_secret_access_key=DO_SECRET_ACCESS_KEY,
    )
    return client


# Function to upload file to S3
def upload_to_s3(file_path, s3_key):
    s3_client = get_s3_client()
    bucket_name = DO_STORAGE_BUCKET_NAME
    try:
        s3_client.upload_file(os.path.join(DO_LOCATION, file_path), bucket_name, s3_key)
        print(f"✅ Uploaded {file_path} to S3 bucket '{bucket_name}' with key '{s3_key}'.")
    except Exception as e:
        print(f"❌ Error uploading {file_path} to S3: {str(e)}")
        raise


def insert_levels_from_json(json_file_path: str, db_session: _Session, override_existing: Optional[bool] = False):
    """
    Parses a JSON file and inserts levels into the database, avoiding duplicates.
    Uploads the original images and lesion masks to S3, and stores the S3 paths in the database.

    Args:
        json_file_path (str): The path to the JSON file containing level data.
        db_session (Session): The SQLAlchemy session object for database operations.
        override_existing (bool): If true, existing records will be replaced with new data.
    """

    try:
        with open(json_file_path, 'r') as file:
            data = json.load(file)
        
        json_dir = os.path.dirname(json_file_path)
        parent_dir = os.path.abspath(os.path.join(json_dir, os.pardir))

        for level_data in data:
            level_number = level_data.get('level_number')
            existing_level = db_session.execute(
                select(Level).filter_by(level_number=level_number)
            ).scalar_one_or_none()
            
            if existing_level and override_existing:
                # Delete the existing level (associated user_progress will be deleted due to cascade)
                db_session.delete(existing_level)
                db_session.flush()
                existing_level = None  # Clear the reference

            if existing_level is None:
                # Adjust the paths
                original_image_path = level_data.get('original_image_path', None)
                if original_image_path:
                    full_original_image_path = os.path.abspath(os.path.join(parent_dir, original_image_path))
                else:
                    full_original_image_path = None

                lesion_mask_path = level_data.get('lesion_mask_path', None)
                if lesion_mask_path:
                    full_lesion_mask_path = os.path.abspath(os.path.join(parent_dir, lesion_mask_path))
                else:
                    full_lesion_mask_path = None

                # Prepare S3 keys with zero-padded level numbers
                level_number_str = str(level_number).zfill(2)  # zero-pad to 2 digits if less than 10
                s3_base_key = os.path.join('traininglevels', level_number_str)

                # Upload files to S3 and get S3 paths
                if full_original_image_path and os.path.exists(full_original_image_path):
                    original_image_filename = os.path.basename(full_original_image_path)
                    original_image_s3_key = os.path.join(s3_base_key, original_image_filename)
                    upload_to_s3(full_original_image_path, original_image_s3_key)
                    original_image_s3_path = original_image_s3_key
                else:
                    original_image_s3_path = None

                if full_lesion_mask_path and os.path.exists(full_lesion_mask_path):
                    lesion_mask_filename = os.path.basename(full_lesion_mask_path)
                    lesion_mask_s3_key = os.path.join(s3_base_key, lesion_mask_filename)
                    upload_to_s3(full_lesion_mask_path, lesion_mask_s3_key)
                    lesion_mask_s3_path = lesion_mask_s3_key
                else:
                    lesion_mask_s3_path = None

                level = Level(
                    level_number=level_number,
                    name=level_data.get('name'),
                    description=level_data.get('description', None),
                    original_image_path=original_image_s3_path,
                    lesion_mask_path=lesion_mask_s3_path
                )
                db_session.add(level)
            else:
                print(f"ℹ️  Level {level_number} already exists. Skipping.")

        db_session.commit()

        levels = db_session.query(Level).all()
        print(f"✅ There are now {len(levels)} levels in the database.")

    except Exception as e:
        print(f"❌ An error occurred: {str(e)}")
        db_session.rollback()
    finally:
        db_session.close()

def insert_causes_from_json(json_path: str, session: _Session, override_existing: Optional[bool] = False):
    """
    Parses a JSON file and inserts causes into the database, avoiding duplicates.

    Args:
        json_path (str): The path to the JSON file containing cause data.
        session (Session): The SQLAlchemy session object for database operations.
        override_existing (bool): If true, existing records will be replaced with new data.
    """
    try:
        with open(json_path, 'r') as file:
            causes_data = json.load(file)

        default_user_id = get_user_id(session)

        for cause in causes_data:
            existing_cause = session.execute(
                select(Cause).filter_by(name=cause['name'])
            ).scalar_one_or_none()

            if existing_cause is None:
                new_cause = Cause(
                    name=cause.get('name'),
                    description=cause.get('description'),
                    user_id=default_user_id  # Set the default user_id
                )
                session.add(new_cause)
            elif override_existing:
                session.delete(existing_cause)
                session.flush()  # Ensure the existing cause is removed
                new_cause = Cause(
                    name=cause.get('name'),
                    description=cause.get('description'),
                    user_id=default_user_id  # Set the default user_id
                )
                session.add(new_cause)

        session.commit()

        causes = session.query(Cause).all()
        print(f"There are now {len(causes)} causes in the database.")

    except Exception as e:
        print(f"An error occurred: {str(e)}")
        session.rollback()
    finally:
        session.close()

def insert_symptoms_from_json(json_file_path: str, db_session: _Session, override_existing: Optional[bool] = False):
    """
    Parses a JSON file and inserts symptoms into the database, avoiding duplicates.

    Args:
        json_file_path (str): The path to the JSON file containing symptom data.
        db_session (Session): The SQLAlchemy session object for database operations.
        override_existing (bool): If true, existing records will be replaced with new data.
    """
    try:
        with open(json_file_path, 'r') as file:
            data = json.load(file)

        default_user_id = get_user_id(db_session)

        for symptom_data in data:
            # Find the corresponding Domain ID
            domain = db_session.execute(
                select(Domain).filter_by(name=symptom_data['domain'])
            ).scalar_one_or_none()

            if not domain:
                print(f"Domain '{symptom_data['domain']}' not found for symptom '{symptom_data['name']}'")
                continue

            # Find the corresponding Subdomain ID
            subdomain = db_session.execute(
                select(Subdomain).filter_by(name=symptom_data['subdomain'], domain_id=domain.id)
            ).scalar_one_or_none()

            if not subdomain:
                print(f"Subdomain '{symptom_data['subdomain']}' not found for symptom '{symptom_data['name']}'")
                continue

            # Check if the symptom already exists
            existing_symptom = db_session.execute(
                select(Symptom).filter_by(name=symptom_data['name'], domain_id=domain.id, subdomain_id=subdomain.id)
            ).scalar_one_or_none()

            if existing_symptom and override_existing:
                # Delete existing synonyms and mesh terms first
                db_session.query(Synonym).filter_by(symptom_id=existing_symptom.id).delete()
                db_session.query(MeshTerm).filter_by(symptom_id=existing_symptom.id).delete()
                db_session.flush()
                # Delete the existing symptom
                db_session.delete(existing_symptom)
                db_session.flush()
                existing_symptom = None

            if existing_symptom is None:
                # Insert the new symptom
                symptom = Symptom(
                    name=symptom_data['name'],
                    description=symptom_data.get('description', None),
                    domain_id=domain.id,
                    subdomain_id=subdomain.id,
                    user_id=default_user_id  # Set the default user_id
                )
                db_session.add(symptom)
                db_session.flush()  # Ensure symptom.id is populated

                # Insert synonyms
                for synonym_name in symptom_data.get('synonyms', []):
                    synonym = Synonym(
                        name=synonym_name,
                        symptom_id=symptom.id,
                        user_id=default_user_id  # Set the default user_id
                    )
                    db_session.add(synonym)

                # Insert mesh terms
                for mesh_term_name in symptom_data.get('mesh_terms', []):
                    mesh_term = MeshTerm(
                        name=mesh_term_name,
                        symptom_id=symptom.id,
                        user_id=default_user_id  # Set the default user_id
                    )
                    db_session.add(mesh_term)

        db_session.commit()

        symptoms = db_session.query(Symptom).all()
        print(f"There are now {len(symptoms)} symptoms in the database.")

        synonyms = db_session.query(Synonym).all()
        print(f"There are now {len(synonyms)} synonyms in the database.")

        mesh_terms = db_session.query(MeshTerm).all()
        print(f"There are now {len(mesh_terms)} mesh terms in the database.")

    except Exception as e:
        print(f"An error occurred: {str(e)}")
        db_session.rollback()
    finally:
        db_session.close()

def insert_cohorts_from_json(json_file_path: str, db_session: _Session, override_existing: Optional[bool] = False):
    """
    Parses a JSON file and inserts cohorts into the database, avoiding duplicates.

    Args:
        json_file_path (str): The path to the JSON file containing cohort data.
        db_session (Session): The SQLAlchemy session object for database operations.
        override_existing (bool): If true, existing records will be replaced with new data.
    """
    try:
        with open(json_file_path, 'r') as file:
            data = json.load(file)

        for cohort_data in data:
            # Check if the cohort already exists
            existing_cohort = db_session.execute(
                select(PatientCohort).filter_by(name=cohort_data['name'])
            ).scalar_one_or_none()

            if existing_cohort and override_existing:
                db_session.delete(existing_cohort)
                db_session.flush()
                existing_cohort = None

            if existing_cohort is None:
                # Insert the new cohort
                cohort = PatientCohort(
                    name=cohort_data['name'],
                    description=cohort_data.get('description', None)
                )
                db_session.add(cohort)

        db_session.commit()

        cohorts = db_session.query(PatientCohort).all()
        print(f"There are now {len(cohorts)} cohorts in the database.")

    except Exception as e:
        print(f"An error occurred: {str(e)}")
        db_session.rollback()
    finally:
        db_session.close()

def process_parcellation(parcellation: Bunch, session: _Session):
    """
    Process a parcellation and insert it into the database.
    """
    parcellation_to_parcellation_table(parcellation, session)
    parcellation_to_parcels_table(parcellation, session)
    data_to_voxelwise_values_table(parcellation, session)

def insert_default_users(json_path, session):
    # Load users from the JSON file
    with open(json_path, 'r') as file:
        users_data = json.load(file)
    
    for user_data in users_data:
        # Check if the user already exists by username or email
        existing_user = session.query(User).filter(
            (User.username == user_data['username']) |
            (User.email == user_data['email'])
        ).first()

        if existing_user:
            print(f"User with username '{user_data['username']}' or email '{user_data['email']}' already exists. Skipping.")
            continue

        # Convert date_joined to a datetime object
        date_joined = datetime.strptime(user_data['date_joined'], "%Y-%m-%d")
        
        # Hash the password
        hashed_password = make_password(user_data['password'])

        # Create a new User object
        new_user = User(
            username=user_data['username'],
            email=user_data.get('email'),
            password=hashed_password,
            first_name=user_data.get('first_name'),
            last_name=user_data.get('last_name'),
            is_superuser=user_data.get('is_superuser', False),
            is_staff=user_data.get('is_staff', False),
            is_active=user_data.get('is_active', True),
            date_joined=date_joined
        )
        
        # Add the new user to the session
        session.add(new_user)
        try:
            # Commit the session
            session.commit()
            print(f"Inserted user '{new_user.username}' successfully.")
        except IntegrityError:
            # If there is an IntegrityError, rollback the session
            session.rollback()
            print(f"Failed to insert user '{new_user.username}'. Integrity error occurred.")

def insert_case_report_from_json(json_file_path: str, db_session: _Session, override_existing: bool = False):
    try:
        # Load the JSON data
        with open(json_file_path, 'r') as file:
            data = json.load(file)
        
        # Check if the case report already exists by pubmed_id or doi
        existing_report = db_session.query(CaseReport).filter(
            (CaseReport.pubmed_id == data.get('pmid')) | (CaseReport.doi == data.get('doi'))
        ).first()
        
        if existing_report and not override_existing:
            print(f"Skipping insertion: CaseReport with PMID {data.get('pmid')} or DOI {data.get('doi')} already exists.")
            return
        
        # Create or update the case report
        if existing_report and override_existing:
            print(f"Updating existing CaseReport with PMID {data.get('pmid')} or DOI {data.get('doi')}.")
            case_report = existing_report
        else:
            print(f"Inserting new CaseReport with PMID {data.get('pmid')} or DOI {data.get('doi')}.")
            case_report = CaseReport()

        # Get user_id 
        user_id = get_user_id(db_session)
        case_report.user_id = user_id

        # Set other case report attributes
        case_report.doi = data.get('doi')
        case_report.pubmed_id = data.get('pmid')
        case_report.title = data.get('title')
        case_report.first_author = data.get('first_author')
        case_report.year = data.get('year')
        case_report.abstract = data.get('abstract')
        case_report.path = data.get('path')
        case_report.is_open_access = data.get('open_access', False)
        case_report.other_citation = f"{data.get('first_author', 'Unknown')} ({data.get('year', 'Unknown')}). {data.get('title', 'No Title')}"

        # First, add and commit the case report to get its ID
        db_session.add(case_report)
        db_session.flush()  # This will generate the ID without fully committing

        # Now handle symptoms
        symptoms = data.get('symptoms', [])
        symptom_records = db_session.query(Symptom).filter(Symptom.name.in_(symptoms)).all()
        
        # Manually create association records
        for symptom in symptom_records:
            assoc = CaseReportSymptom(
                case_report_id=case_report.id,  # Now this will have a value
                symptom_id=symptom.id,
                user_id=user_id
            )
            db_session.add(assoc)

        # Commit all changes
        db_session.commit()
        
        print(f"Successfully inserted/updated CaseReport with PMID {data.get('pmid')} or DOI {data.get('doi')}.")

    except Exception as e:
        print(f"Error occurred while processing {json_file_path}: {e}")
        db_session.rollback()  # Rollback in case of error