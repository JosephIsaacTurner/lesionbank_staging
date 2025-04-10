# pages/forms.py

# Standard library imports
import hashlib
import os
import re
import gzip
from io import BytesIO

# Third-party imports
from django import forms
from django.db import transaction
from django.forms import ClearableFileInput
from django.forms.models import inlineformset_factory, BaseInlineFormSet
from django.utils.timezone import now
from django.db.models import Max
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit
from django_select2.forms import Select2MultipleWidget, Select2Widget
import nibabel as nib
from sqlalchemy.sql import text
from sqlalchemy_utils import db_utils
from sqlalchemy_utils.db_session import get_session
from django.core.exceptions import ValidationError

# Local application imports
from .models import (
    CaseReport,
    Cause,
    ConnectivityFile,
    CoordinateSpace,
    Domain,
    GroupLevelMapFile,
    Handedness,
    ImageModality,
    InclusionCriteria,
    Level,
    MiscellaneousUpload,
    OriginalImageFile,
    Connectome,
    ROIFile,
    Sex,
    StatisticType,
    Subdomain,
    Symptom,
    Subject,
    UserLevelProgress,
    Dimension,
    Synonym,
    MeshTerm,
)


class LevelCreationForm(forms.ModelForm):
    """Form for creating a Level instance."""

    class Meta:
        model = Level
        fields = ['name', 'description', 'original_image_path', 'lesion_mask_path']
        widgets = {
            'description': forms.Textarea(attrs={'rows': 4}),
        }
        labels = {
            'name': 'Level Name',
            'description': 'Description',
            'original_image_path': 'Original Image (PNG/JPG)',
            'lesion_mask_path': 'Lesion Mask (NIFTI)',
        }

    def clean_original_image_path(self):
        image = self.cleaned_data.get('original_image_path')
        if image:
            if not image.name.lower().endswith(('.png', '.jpg', '.jpeg')):
                raise forms.ValidationError('Only PNG and JPG images are allowed.')
            if image.size > 5 * 1024 * 1024:  # 5MB limit
                raise forms.ValidationError('Image file size must be under 5MB.')
        return image

    def clean_lesion_mask_path(self):
        mask = self.cleaned_data.get('lesion_mask_path')
        if mask:
            if not mask.name.lower().endswith(('.nii', '.nii.gz')):
                raise forms.ValidationError('Only NIFTI files are allowed.')
            if mask.size > 20 * 1024 * 1024:  # 20MB limit
                raise forms.ValidationError('Lesion mask file size must be under 20MB.')
        return mask


class UserLevelProgressForm(forms.ModelForm):
    """Form for user to upload a traced lesion mask."""

    user_uploaded_mask = forms.FileField(
        required=True,
        label='Upload Your Traced Lesion (NIFTI format)',
        widget=forms.FileInput(attrs={'accept': '.nii,.gz'})
    )

    class Meta:
        model = UserLevelProgress
        fields = []

    def clean_user_uploaded_mask(self):
        file = self.cleaned_data.get('user_uploaded_mask')
        if file:
            if not file.name.endswith(('.nii', '.nii.gz')):
                raise forms.ValidationError('Only NIFTI files are allowed.')
            if file.size > 10 * 1024 * 1024:  # 10MB limit
                raise forms.ValidationError('File size must be under 10MB.')
        return file


class MiscellaneousUploadForm(forms.ModelForm):
    """Form for uploading miscellaneous files."""

    class Meta:
        model = MiscellaneousUpload
        fields = ['file']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.update({'class': 'form-control'})

    def save(self, commit=True, user=None):
        instance = super().save(commit=False)
        if user:
            instance.user = user
        if commit:
            instance.save()
        return instance


class CaseStudyInclusionForm(forms.ModelForm):
    """Form for inclusion criteria of a case study."""

    class Meta:
        model = InclusionCriteria
        fields = [
            'is_case_study',
            'is_english',
            'is_relevant_symptoms',
            'is_full_text',
            'is_temporally_linked',
            'is_brain_scan',
            'is_included',
            'is_relevant_clinical_scores',
            'notes',
        ]
        labels = {
            'is_case_study': 'Is this a case study?',
            'is_english': 'Is the study in English?',
            'is_relevant_symptoms': (
                "Does the study have relevant neuropsychiatric, cognitive, or motor symptoms? "
                "Don't worry about specifying the exact symptoms here—we'll get to that when we start creating individual subjects."
            ),
            'is_full_text': 'Do you have access to the full text of the study?',
            'is_temporally_linked': (
                'Is the onset of the symptom temporally linked to the lesion? '
                'I.e., was the symptom likely caused by the lesion?'
            ),
            'is_brain_scan': 'Does the study include a visible image of lesion in a brain scan (MRI, CT, etc.)?',
            'is_included': (
                'If you answered "yes" to all of the above, you can mark this study as included. '
                'If you answered "no" to any of the above, you can mark this study as excluded. '
                'There might be some cases where it technically meets the criteria but for a very convincing but unforeseen reason, it should be excluded. '
                'In that case, you can mark it as excluded and provide a note.'
            ),
            'is_relevant_clinical_scores': 'Does the study include relevant clinical scores (e.g., NIHSS, mRS, etc.)?',
            'notes': 'Any additional notes?',
        }
        help_texts = {
            'notes': 'Provide any extra information or context here.',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_method = 'post'
        self.helper.add_input(Submit('submit', 'Submit Validation'))


class SubjectForm(forms.ModelForm):
    """Form for creating or updating a Subject instance."""
    
    symptoms = forms.ModelMultipleChoiceField(
        queryset=Symptom.objects.all(),
        required=False,
        widget=forms.SelectMultiple(attrs={'class': 'select2-multiple form-control'}),
        label='Symptoms'
    )
    
    case_report = forms.ModelChoiceField(
        queryset=CaseReport.objects.all(),
        required=False,
        widget=Select2Widget(
            attrs={
                'data-placeholder': 'Search and select a Case Report...',
                'style': 'width: 100%;',
            },
        ),
        label='Associate Case Report'
    )
    
    class Meta:
        model = Subject
        fields = ['age', 'sex', 'handedness', 'cause', 'symptoms', 'internal_use_only', 'case_report']
        widgets = {
            'internal_use_only': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        fixed_case_report = kwargs.pop('fixed_case_report', None)
        super().__init__(*args, **kwargs)

        data = self.data if self.is_bound else None
        files = self.files if self.is_bound else None

        # Set required fields
        self.fields['age'].required = True
        self.fields['sex'].required = True
        self.fields['handedness'].required = True
        self.fields['cause'].required = True
        self.fields['internal_use_only'].required = False

        # Configure 'cause' field
        self.fields['cause'].queryset = Cause.objects.all()
        self.fields['cause'].label_from_instance = lambda obj: f"{obj.name} - {obj.description}"

        # Set default values if adding a new subject
        if not self.instance.pk:
            default_cause = Cause.objects.filter(name="ischemic stroke").first()
            if default_cause:
                self.fields['cause'].initial = default_cause.id

            default_handedness = Handedness.objects.filter(name="unknown").first()
            if default_handedness:
                self.fields['handedness'].initial = default_handedness.id

            default_sex = Sex.objects.filter(name='unknown').first()
            if default_sex:
                self.fields['sex'].initial = default_sex.id

        # Add 'form-control' class to all fields except 'internal_use_only'
        for field_name, field in self.fields.items():
            if field_name == 'internal_use_only':
                continue  # Already has 'form-check-input'
            existing_classes = field.widget.attrs.get('class', '')
            classes = existing_classes.split()
            if 'form-control' not in classes:
                classes.append('form-control')
            field.widget.attrs['class'] = ' '.join(classes)

        # Pre-select existing symptoms if editing
        if self.instance and self.instance.pk:
            self.fields['symptoms'].initial = self.instance.symptoms.all()

        # Initialize file forms
        if not self.instance or not self.instance.pk:
            # Adding a new subject
            self.connectivity_file_forms = [
                ConnectivityFileForm(data=data, files=files, prefix='connectivity')
            ]
            self.roi_file_forms = [
                ROIFileForm(data=data, files=files, prefix='roi')
            ]
            self.original_image_forms = [
                OriginalImageForm(data=data, files=files, prefix='original_image')
            ]
        else:
            # Editing an existing subject
            self.connectivity_file_forms = []
            existing_connectivity_files = ConnectivityFile.objects.filter(subject=self.instance)
            for i, conn_file in enumerate(existing_connectivity_files):
                self.connectivity_file_forms.append(
                    ConnectivityFileForm(
                        data=data,
                        files=files,
                        prefix=f'connectivity_{i}',
                        instance=conn_file
                    )
                )
            # Add an extra empty form for adding new files
            self.connectivity_file_forms.append(
                ConnectivityFileForm(
                    data=data,
                    files=files,
                    prefix=f'connectivity_{len(existing_connectivity_files)}'
                )
            )

            self.roi_file_forms = []
            existing_roi_files = ROIFile.objects.filter(subject=self.instance)
            for i, roi_file in enumerate(existing_roi_files):
                self.roi_file_forms.append(
                    ROIFileForm(
                        data=data,
                        files=files,
                        prefix=f'roi_{i}',
                        instance=roi_file
                    )
                )
            # Add an extra empty form for adding new files
            self.roi_file_forms.append(
                ROIFileForm(
                    data=data,
                    files=files,
                    prefix=f'roi_{len(existing_roi_files)}'
                )
            )

            self.original_image_forms = []
            existing_original_images = OriginalImageFile.objects.filter(subject=self.instance)
            for i, orig_img in enumerate(existing_original_images):
                self.original_image_forms.append(
                    OriginalImageForm(
                        data=data,
                        files=files,
                        prefix=f'original_image_{i}',
                        instance=orig_img
                    )
                )
            # Add an extra empty form for adding new files
            self.original_image_forms.append(
                OriginalImageForm(
                    data=data,
                    files=files,
                    prefix=f'original_image_{len(existing_original_images)}'
                )
            )

        # Handle fixed_case_report if provided (used in add_subject_to_case_report view)
        if fixed_case_report:
            # Pre-populate and hide the case_report field to enforce association
            self.fields['case_report'].initial = fixed_case_report
            self.fields['case_report'].widget = forms.HiddenInput()

    def clean_case_report(self):
        """
        Validate and return the associated CaseReport instance or None.
        """
        case_report = self.cleaned_data.get('case_report')
        return case_report  # Already a CaseReport instance or None

    def is_valid(self):
        """
        Override is_valid to include validation for optional file forms.
        """
        forms_valid = super().is_valid()

        # Combine all optional forms
        optional_forms = (
            self.connectivity_file_forms +
            self.roi_file_forms +
            self.original_image_forms
        )

        # Collect errors from optional forms but don't affect overall validity
        for form in optional_forms:
            if form.has_changed() and not form.is_valid():
                for field, errors in form.errors.items():
                    self.add_error(None, f"{form.prefix}: {errors}")

        return forms_valid

    @transaction.atomic
    def save(self, commit=True, case_report=None):
        """
        Save the Subject instance, handling the association with CaseReport
        and saving related file forms.
        """
        instance = super().save(commit=False)
        if self.user:
            instance.user = self.user

        if case_report:
            instance.case_report = case_report
        else:
            # If case_report is not provided via parameter, get from cleaned data
            cleaned_case_report = self.cleaned_data.get('case_report')
            if cleaned_case_report:
                instance.case_report = cleaned_case_report
            else:
                instance.case_report = None

        instance.insert_date = now()  # Set insert_date here

        if commit:
            print("Attempting to save subject...")
            instance.save()

            # Save symptoms manually with user context
            instance.symptoms.clear()
            selected_symptoms = self.cleaned_data.get('symptoms')
            if selected_symptoms:
                for symptom in selected_symptoms:
                    instance.symptoms.through.objects.create(
                        subject=instance,
                        symptom=symptom,
                        user=self.user
                    )

            # Save associated file forms
            optional_forms = (
                self.connectivity_file_forms +
                self.roi_file_forms +
                self.original_image_forms
            )
            for form in optional_forms:
                if form.has_changed() and form.is_valid():
                    form.save(subject=instance, user=self.user)

            # Handle deletion of files if necessary
            self.handle_file_deletions()

        else:
            print("Not saving subject...")

        return instance

    def handle_file_deletions(self):
        """
        Handle deletion of related file instances based on form data.
        """
        # Deletion of Original Image Files
        for i, form in enumerate(self.original_image_forms):
            if form.instance.pk:
                delete_flag = self.data.get(f'delete_original_image_{i}')
                if delete_flag:
                    form.instance.delete_related_files()
                    form.instance.delete()

        # Deletion of ROI Files
        for i, form in enumerate(self.roi_file_forms):
            if form.instance.pk:
                delete_flag = self.data.get(f'delete_roi_{i}')
                if delete_flag:
                    form.instance.delete_related_files()
                    form.instance.delete()

        # Deletion of Connectivity Files
        for i, form in enumerate(self.connectivity_file_forms):
            if form.instance.pk:
                delete_flag = self.data.get(f'delete_connectivity_{i}')
                if delete_flag:
                    form.instance.delete_related_files()
                    form.instance.delete()

    def get_connectivity_file_forms(self):
        """Return connectivity file forms."""
        return self.connectivity_file_forms

    def get_roi_file_forms(self):
        """Return ROI file forms."""
        return self.roi_file_forms

    def get_original_image_forms(self):
        """Return original image forms."""
        return self.original_image_forms


class ROIFileForm(forms.ModelForm):
    """Form for uploading ROI files."""

    class Meta:
        model = ROIFile
        fields = ['dimension', 'path']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        for field in self.fields.values():
            field.required = False
            field.widget.attrs.update({'class': 'form-control'})

        default_dimension = Dimension.objects.filter(name="2d").first()
        if default_dimension and not self.instance.pk:
            self.fields['dimension'].initial = default_dimension.id

        self.fields['path'].widget.attrs.update({'name': 'roi_file_path'})

    def get_next_id(self):
        max_id = ROIFile.objects.aggregate(max_id=Max('id'))['max_id']
        return (max_id or 0) + 1

    def save(self, commit=True, subject=None, user=None):
        instance = super().save(commit=False)
        if subject:
            instance.subject = subject
        if not self.instance.pk:
            # New instance, set additional fields
            instance.filetype = db_utils.determine_filetype(instance.path.name)
            instance.md5 = hashlib.md5(instance.path.read()).hexdigest()
            instance.coordinate_space = CoordinateSpace.objects.filter(name='unknown').first()
            file_id = self.get_next_id()
            filename = f"sub-{instance.subject.id}_file-{file_id}_roi.{instance.filetype}"
            instance.path.name = filename
            if user:
                instance.user = user
        if commit:
            instance.save()

            if instance.filetype in ['nii', 'nii.gz']:
                # Attempt to process ROI file after commit
                def process_roi_file():
                    try:
                        session = get_session()
                        nifti_file = db_utils.fetch_from_s3(instance.path.name)
                        coordinate_space_name = db_utils.determine_coordinate_space(
                            nifti_file.shape, nifti_file.affine
                        )
                        coordinate_space = CoordinateSpace.objects.filter(
                            name=coordinate_space_name
                        ).first()
                        instance.coordinate_space = coordinate_space
                        instance.save()

                        db_utils.data_to_parcelwise_values_table(
                            parcellation=db_utils.fetch_atlas_3209c91v(),
                            voxelwise_map=nifti_file,
                            session=session,
                            strategy='sum',
                            map_type='roi',
                            voxelwise_map_name=instance.path.name
                        )
                    except Exception:
                        # Handle processing error
                        pass
                    finally:
                        session.close()

                transaction.on_commit(process_roi_file)

        return instance


class ConnectivityFileForm(forms.ModelForm):
    """Form for uploading connectivity files."""

    class Meta:
        model = ConnectivityFile
        fields = ['statistic_type', 'connectome', 'path']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields['connectome'].queryset = Connectome.objects.all()
        self.fields['connectome'].label_from_instance = lambda obj: f"{obj.name} - {obj.description}"

        default_connectome = Connectome.objects.filter(name="GSP1000MF").first()
        if default_connectome and not self.instance.pk:
            self.fields['connectome'].initial = default_connectome.id

        self.fields['statistic_type'].queryset = StatisticType.objects.all()
        self.fields['statistic_type'].label_from_instance = lambda obj: f"{obj.name} - {obj.description}"

        default_statistic_type = StatisticType.objects.filter(name="student's t").first()
        if default_statistic_type and not self.instance.pk:
            self.fields['statistic_type'].initial = default_statistic_type.id

        for field in self.fields.values():
            field.required = False
            field.widget.attrs.update({'class': 'form-control'})

        self.fields['path'].widget.attrs.update({'name': 'connectivity_file_path'})

    def get_next_id(self):
        max_id = ROIFile.objects.aggregate(max_id=Max('id'))['max_id']
        return (max_id or 0) + 1

    def save(self, commit=True, subject=None, user=None):
        instance = super().save(commit=False)
        if subject:
            instance.subject = subject
        if not self.instance.pk:
            # New instance, set additional fields
            instance.filetype = db_utils.determine_filetype(instance.path.name)
            instance.md5 = hashlib.md5(instance.path.read()).hexdigest()
            instance.coordinate_space = CoordinateSpace.objects.filter(name='unknown').first()
            file_id = self.get_next_id()
            # Sanitize connectome and statistic_type names if necessary
            connectome_name_safe = re.sub(r'\W+', '_', instance.connectome.name.lower())
            statistic_code_safe = re.sub(r'\W+', '_', instance.statistic_type.code.lower())
            filename = (
                f"sub-{instance.subject.id}_file-{file_id}_tome-{connectome_name_safe}_stat-"
                f"{statistic_code_safe}_conn.{instance.filetype}"
            )
            instance.path.name = filename
            if user:
                instance.user = user
        if commit:
            instance.save()

            # Additional processing if needed
            if instance.filetype in ['nii', 'nii.gz']:
                # Attempt to process Connectivity file after commit
                def process_connectivity_file():
                    try:
                        session = get_session()
                        nifti_file = db_utils.fetch_from_s3(instance.path.name)
                        coordinate_space_name = db_utils.determine_coordinate_space(
                            nifti_file.shape, nifti_file.affine
                        )
                        coordinate_space = CoordinateSpace.objects.filter(
                            name=coordinate_space_name
                        ).first()
                        instance.coordinate_space = coordinate_space
                        instance.save()

                        db_utils.data_to_parcelwise_values_table(
                            parcellation=db_utils.fetch_atlas_3209c91v(),
                            voxelwise_map=nifti_file,
                            session=session,
                            strategy='mean',
                            map_type='connectivity',
                            voxelwise_map_name=instance.path.name
                        )
                    except Exception:
                        # Handle processing error
                        pass
                    finally:
                        session.close()

                transaction.on_commit(process_connectivity_file)

        return instance


class OriginalImageForm(forms.ModelForm):
    """Form for uploading original image files."""

    class Meta:
        model = OriginalImageFile
        fields = ['image_modality', 'path']
        widgets = {
            'path': ClearableFileInput(attrs={'accept': 'image/*'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        for field in self.fields.values():
            field.required = False
            field.widget.attrs.update({'class': 'form-control'})

        self.fields['image_modality'].label_from_instance = lambda obj: f"{obj.name} - {obj.description}"
        default_modality = ImageModality.objects.filter(name="T1").first()
        if default_modality and not self.instance.pk:
            self.fields['image_modality'].initial = default_modality.id

        self.fields['path'].widget.attrs.update({'name': 'original_image_path', 'class': 'original-file-input'})

    def get_next_id(self):
        max_id = ROIFile.objects.aggregate(max_id=Max('id'))['max_id']
        return (max_id or 0) + 1

    def clean(self):
        cleaned_data = super().clean()
        image_modality = cleaned_data.get('image_modality')
        path = cleaned_data.get('path')

        if self.has_changed():
            # Ensure required fields are provided when form has changed
            if not image_modality:
                self.add_error('image_modality', 'This field is required when adding an image.')
            if not path:
                self.add_error('path', 'This field is required when adding an image.')
        return cleaned_data

    def save(self, commit=True, subject=None, user=None):
        instance = super().save(commit=False)
        if subject:
            instance.subject = subject
        if not self.instance.pk:
            # New instance, set additional fields
            filetype = db_utils.determine_filetype(self.cleaned_data['path'].name)
            instance.filetype = filetype
            file_id = self.get_next_id()
            filename = f"sub-{subject.id}_file-{file_id}_orig.{filetype}"
            instance.path.name = filename
            if user:
                instance.user = user
        if commit:
            instance.save()
        return instance


class CaseReportForm(forms.ModelForm):
    """Form for creating or updating a CaseReport instance."""

    symptoms = forms.ModelMultipleChoiceField(
        queryset=Symptom.objects.all(),
        required=False,
        widget=forms.SelectMultiple(attrs={'class': 'select2-multiple'}),
        label='Symptoms'
    )

    class Meta:
        model = CaseReport
        fields = [
            'doi', 'pubmed_id', 'other_citation', 'title', 'first_author',
            'year', 'abstract', 'path', 'is_open_access', 'symptoms'
        ]
        help_texts = {
            'doi': 'Do not include the prefix "doi.org". Enter only the DOI ID itself.',
            'first_author': 'Please enter only the surname (last name) of the first author.',
            'symptoms': 'Optionally tag this case report with relevant symptoms.',
        }
        widgets = {
            'doi': forms.TextInput(attrs={'placeholder': 'e.g., 10.1000/xyz123'}),
            'first_author': forms.TextInput(attrs={'placeholder': 'e.g., Smith'}),
            'abstract': forms.Textarea(attrs={
                'rows': 4,
                'placeholder': 'Enter the abstract here...'
            }),
            # Additional widgets can be added here
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)  # Accept and store the user
        super().__init__(*args, **kwargs)
        if self.user is None:
            raise ValueError("CaseReportForm requires a 'user' parameter.")
        
        self.helper = FormHelper()
        self.helper.form_method = 'post'
        self.helper.add_input(Submit('submit', 'Submit'))

        # Pre-select existing symptoms if editing
        if self.instance and self.instance.pk:
            self.fields['symptoms'].initial = self.instance.symptoms.all()

    def clean_path(self):
        path = self.cleaned_data.get('path')
        if path and not path.name.lower().endswith('.pdf'):
            raise forms.ValidationError('Only PDF files are allowed.')
        return path

    @transaction.atomic
    def save(self, commit=True):
        # Start with saving the CaseReport instance without committing to handle user
        instance = super().save(commit=False)

        if self.user:
            print(f"Setting user: {self.user.username}")  # Debugging
            instance.user = self.user  # Set the user here
        else:
            print("No user provided!")  # Debugging
            raise ValueError("User must be provided to save the form.")

        if commit:
            print("Attempting to save CaseReport...")
            instance.insert_date = now()  # Ensure insert_date is set
            instance.save()

            # Clear existing symptoms and add selected ones with user context
            instance.symptoms.clear()
            selected_symptoms = self.cleaned_data.get('symptoms')
            if selected_symptoms:
                through_model = instance.symptoms.through
                bulk_create_instances = [
                    through_model(
                        case_report=instance,
                        symptom=symptom,
                        user=self.user  # Set the user here
                    )
                    for symptom in selected_symptoms
                ]
                print(f"Creating {len(bulk_create_instances)} CaseReportSymptom instances with user {self.user.username}")  # Debugging
                through_model.objects.bulk_create(bulk_create_instances)

            # Handle any additional logic, such as saving related files
            # For example:
            # self.handle_related_files()

        else:
            print("Not saving CaseReport...")

        return instance
    

class BaseGroupLevelMapForm(forms.ModelForm):
    """Base form for uploading group level map files."""

    class Meta:
        model = GroupLevelMapFile
        fields = [
            'path',
            'map_type',
            'statistic_type',
            'research_paper'
        ]

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        self.related_object = kwargs.pop('related_object', None)
        self.category = kwargs.pop('category', None)
        super().__init__(*args, **kwargs)

        for field in self.fields.values():
            field.required = False
            field.widget.attrs.update({'class': 'form-control'})

        self.fields['path'].widget.attrs.update({'name': 'group_level_map_file_path'})

    def get_next_id(self):
        max_id = ROIFile.objects.aggregate(max_id=Max('id'))['max_id']
        return (max_id or 0) + 1

    def save(self, commit=True, category_name=None):
        instance = super().save(commit=False)

        # Set the relevant association
        if self.category == 'symptom':
            instance.symptom = self.related_object
        elif self.category == 'subdomain':
            instance.subdomain = self.related_object
        elif self.category == 'domain':
            instance.domain = self.related_object

        instance.insert_date = now()

        if not self.instance.pk:
            instance.filetype = db_utils.determine_filetype(instance.path.name)
            instance.md5 = hashlib.md5(instance.path.read()).hexdigest()
            instance.coordinate_space = CoordinateSpace.objects.filter(name='unknown').first()
            file_id = self.get_next_id()

            if instance.domain:
                category_name = instance.domain.name
            elif instance.subdomain:
                category_name = instance.subdomain.name
            elif instance.symptom:
                category_name = instance.symptom.name

            filename = f"{category_name}_{instance.map_type}_{instance.statistic_type}.{instance.filetype}"
            instance.path.name = filename

            if self.user:
                instance.user = self.user

        if commit:
            instance.save()

            if instance.filetype in ['nii', 'nii.gz']:
                # Attempt to process Group Level Map file after commit
                def process_group_level_map_file():
                    try:
                        session = get_session()
                        nifti_file = db_utils.fetch_from_s3(instance.path.name)
                        coordinate_space_name = db_utils.determine_coordinate_space(
                            nifti_file.shape, nifti_file.affine
                        )
                        coordinate_space = CoordinateSpace.objects.filter(
                            name=coordinate_space_name
                        ).first()
                        if coordinate_space:
                            instance.coordinate_space = coordinate_space
                            instance.save()

                        db_utils.data_to_parcelwise_values_table(
                            parcellation=db_utils.fetch_atlas_3209c91v(),
                            voxelwise_map=nifti_file,
                            session=session,
                            strategy='sum',
                            map_type='group_level_map',
                            voxelwise_map_name=instance.path.name
                        )
                    except Exception:
                        # Handle processing error
                        pass
                    finally:
                        session.close()

                transaction.on_commit(process_group_level_map_file)
            else:
                # Group Level Map file is not a NIFTI file
                pass

        return instance


class SymptomGroupLevelMapForm(BaseGroupLevelMapForm):
    """Form for uploading group level map files related to a Symptom."""
    pass


class SubdomainGroupLevelMapForm(BaseGroupLevelMapForm):
    """Form for uploading group level map files related to a Subdomain."""
    pass


class DomainGroupLevelMapForm(BaseGroupLevelMapForm):
    """Form for uploading group level map files related to a Domain."""
    pass


class SymptomForm(forms.ModelForm):
    """Form for creating or updating a Symptom."""

    class Meta:
        model = Symptom
        fields = ['name', 'description', 'internal_use_only']
        widgets = {
            'description': forms.Textarea(attrs={'rows': 4}),
            'internal_use_only': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class SubdomainForm(forms.ModelForm):
    """Form for creating or updating a Subdomain."""

    class Meta:
        model = Subdomain
        fields = ['name', 'description']


class DomainForm(forms.ModelForm):
    """Form for creating or updating a Domain."""

    class Meta:
        model = Domain
        fields = ['name', 'description']


class BaseGroupLevelMapInlineFormSet(BaseInlineFormSet):
    """Custom inline formset to pass 'user' to each form."""

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

    def _construct_form(self, i, **kwargs):
        kwargs['user'] = self.user
        return super()._construct_form(i, **kwargs)


# Define separate inline formsets for each parent model using the custom formset
SymptomGroupLevelMapFileFormSet = inlineformset_factory(
    parent_model=Symptom,
    model=GroupLevelMapFile,
    form=BaseGroupLevelMapForm,
    formset=BaseGroupLevelMapInlineFormSet,
    fields=['path', 'map_type', 'statistic_type', 'research_paper'],
    extra=1,
    can_delete=True
)

SubdomainGroupLevelMapFileFormSet = inlineformset_factory(
    parent_model=Subdomain,
    model=GroupLevelMapFile,
    form=BaseGroupLevelMapForm,
    formset=BaseGroupLevelMapInlineFormSet,
    fields=['path', 'map_type', 'statistic_type', 'research_paper'],
    extra=1,
    can_delete=True
)

DomainGroupLevelMapFileFormSet = inlineformset_factory(
    parent_model=Domain,
    model=GroupLevelMapFile,
    form=BaseGroupLevelMapForm,
    formset=BaseGroupLevelMapInlineFormSet,
    fields=['path', 'map_type', 'statistic_type', 'research_paper'],
    extra=1,
    can_delete=True
)


class NiftiUploadForm(forms.Form):
    """Form for uploading NIFTI brain map files."""

    TAXONOMY_CHOICES = [
        ('symptom', 'Symptom'),
        ('subdomain', 'Subdomain'),
        ('domain', 'Domain'),
    ]

    brain_map = forms.FileField(
        required=True,
        label='Upload Brain Map (NIFTI format)',
        widget=forms.FileInput(attrs={
            'accept': '.nii,.nii.gz,.gz',
            'class': 'form-control'
        })
    )

    taxonomy_level = forms.ChoiceField(
        choices=TAXONOMY_CHOICES,
        required=True,
        label='Taxonomy Level',
        widget=forms.Select(attrs={'class': 'form-control'})
    )

    def clean_brain_map(self):
        file = self.cleaned_data.get('brain_map')
        if not file:
            raise forms.ValidationError('Please upload a file.')

        # Check file extension
        if not file.name.lower().endswith(('.nii', '.nii.gz')):
            raise forms.ValidationError('Only NIFTI files (.nii or .nii.gz) are allowed.')

        # Check file size (10MB limit)
        if file.size > 10 * 1024 * 1024:
            raise forms.ValidationError('File size must be under 10MB.')

        try:
            # Try to load the NIFTI file using the custom loader
            self.load_nifti_from_in_memory_file(file)

            # Reset file pointer for future use
            file.seek(0)

            return file

        except Exception as e:
            raise forms.ValidationError(f'Invalid NIFTI file: {str(e)}')

    @staticmethod
    def load_nifti_from_in_memory_file(file_obj):
        """
        Load a Nifti1Image from an UploadedFile or file-like object.

        Args:
            file_obj (UploadedFile or file-like object): The NIFTI file.

        Returns:
            nib.Nifti1Image: The loaded NIFTI image.
        """
        # Reset the file pointer to the beginning
        file_obj.seek(0)

        # Read the file content into bytes
        file_content = file_obj.read()

        # Determine if the file is gzipped
        if file_obj.name.lower().endswith('.nii.gz'):
            # Wrap the bytes in a GzipFile
            gzip_file = gzip.GzipFile(fileobj=BytesIO(file_content))
            file_holder = nib.FileHolder(fileobj=gzip_file)
        elif file_obj.name.lower().endswith('.nii'):
            # Wrap the bytes in a BytesIO object
            file_holder = nib.FileHolder(fileobj=BytesIO(file_content))
        else:
            raise ValueError("Unsupported NIfTI file format. Only .nii and .nii.gz are supported.")

        # Create a Nifti1Image from the file map
        nifti_image = nib.Nifti1Image.from_file_map({'header': file_holder, 'image': file_holder})

        return nifti_image

    def process_nifti(self):
        """
        Process the uploaded NIFTI file using the custom loader.
        Returns the nibabel image object for further processing.
        """
        if self.is_valid():
            file = self.cleaned_data['brain_map']
            return self.load_nifti_from_in_memory_file(file)
        return None


class TagMultipleChoiceField(forms.MultipleChoiceField):
    """
    Custom MultipleChoiceField that allows arbitrary choices.
    Useful for tagging functionality where users can add new tags on the fly.
    """
    def validate(self, value):
        if self.required and not value:
            raise ValidationError(self.error_messages['required'], code='required')
        # Override to allow any value, not just those in self.choices
        return
    

class AddSymptomForm(forms.Form):
    name = forms.CharField(
        max_length=255, 
        required=True,
        widget=forms.TextInput(attrs={'class': 'form-control'})
    )
    domain = forms.ModelChoiceField(
        queryset=Domain.objects.all(),
        required=True,
        widget=Select2Widget(attrs={'class': 'select2-single', 'id': 'id_domain'})
    )
    subdomain = forms.ModelChoiceField(
        queryset=Subdomain.objects.none(),
        required=True,
        widget=Select2Widget(attrs={'class': 'select2-single', 'id': 'id_subdomain'})
    )
    description = forms.CharField(
        widget=forms.Textarea(attrs={'rows': 4, 'class': 'form-control'}),
        required=False
    )
    internal_use_only = forms.BooleanField(
        required=False, 
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )

    synonyms = TagMultipleChoiceField(
        required=False,
        choices=[],  # Empty choices to allow any input
        widget=Select2MultipleWidget(
            attrs={
                'class': 'select2-multiple',
                'data-tags': 'true',      # Enable tagging
                'data-placeholder': 'Add synonyms...'
            }
        )
    )
    mesh_terms = TagMultipleChoiceField(
        required=False,
        choices=[],  # Empty choices to allow any input
        widget=Select2MultipleWidget(
            attrs={
                'class': 'select2-multiple',
                'data-tags': 'true',      # Enable tagging
                'data-placeholder': 'Add mesh terms...'
            }
        )
    )

    def __init__(self, *args, **kwargs):
        domain_selected = kwargs.pop('domain_selected', None)
        super().__init__(*args, **kwargs)
        # Filter subdomains based on selected domain if given
        if domain_selected:
            self.fields['subdomain'].queryset = Subdomain.objects.filter(domain=domain_selected)
        else:
            self.fields['subdomain'].queryset = Subdomain.objects.none()

    def clean_synonyms(self):
        """
        Process the synonyms input into a list of unique, stripped strings.
        """
        synonyms = self.cleaned_data.get('synonyms', [])
        # Remove duplicates and strip whitespace
        synonyms = list(set([syn.strip() for syn in synonyms if syn.strip()]))
        return synonyms

    def clean_mesh_terms(self):
        """
        Process the mesh_terms input into a list of unique, stripped strings.
        """
        mesh_terms = self.cleaned_data.get('mesh_terms', [])
        # Remove duplicates and strip whitespace
        mesh_terms = list(set([mt.strip() for mt in mesh_terms if mt.strip()]))
        return mesh_terms

    def clean(self):
        cleaned_data = super().clean()
        domain = cleaned_data.get('domain')
        subdomain = cleaned_data.get('subdomain')
        synonym_list = cleaned_data.get('synonyms', [])
        mesh_list = cleaned_data.get('mesh_terms', [])

        # Validate that the domain-subdomain combination is valid
        if domain and subdomain and subdomain.domain != domain:
            self.add_error('subdomain', "Invalid domain-subdomain combination.")

        # Check uniqueness of synonyms
        for syn in synonym_list:
            if Synonym.objects.filter(name__iexact=syn).exists():
                existing_syn = Synonym.objects.filter(name__iexact=syn).first()
                assoc_symptom = existing_syn.symptom
                self.add_error('synonyms', f"Synonym '{syn}' already exists and is associated with symptom '{assoc_symptom.name}'.")

        # Check uniqueness of mesh terms
        for mt in mesh_list:
            if MeshTerm.objects.filter(name__iexact=mt).exists():
                existing_mt = MeshTerm.objects.filter(name__iexact=mt).first()
                assoc_symptom = existing_mt.symptom
                self.add_error('mesh_terms', f"Mesh term '{mt}' already exists and is associated with symptom '{assoc_symptom.name}'.")

        return cleaned_data