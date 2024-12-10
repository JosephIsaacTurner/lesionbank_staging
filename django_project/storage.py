# django_project/storage.py
from storages.backends.s3boto3 import S3Boto3Storage

class CustomS3Boto3Storage(S3Boto3Storage):
    def get_object_parameters(self, name):
        if name.endswith('.nii.gz'):
            # Without this, the browser will try to decompress the file when served
            params = {}
            params['ContentType'] = 'application/gzip'
            return params
        else:
            # For all other files, use the default parameters
            return super().get_object_parameters(name)