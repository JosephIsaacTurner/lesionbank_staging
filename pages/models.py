# pages/models.py

from django.db import models
from django.utils.timezone import now
from accounts.models import CustomUser
from django.core.files.storage import default_storage
from django.conf import settings
from django.utils import timezone
from django.db import transaction
from urllib.parse import quote_plus
from django.db.models import Max

"""Helper Functions"""

def connectivity_file_path(instance, filename):
    subject_id = instance.subject.id if instance.subject else 'unknown'
    return f'subjects/sub-{subject_id}/connectivity/{filename}'

def roi_file_path(instance, filename):
    subject_id = instance.subject.id if instance.subject else 'unknown'
    return f'subjects/sub-{subject_id}/roi/{filename}'

def original_image_file_path(instance, filename):
    subject_id = instance.subject.id if instance.subject else 'unknown'
    return f'subjects/sub-{subject_id}/original_images/{filename}'

def group_level_map_file_path(instance, filename):
    if instance.domain:
        category = 'domains'
        filename = f'{instance.domain.name}/{filename}'
    elif instance.subdomain:
        category = 'subdomains'
        filename = f'{instance.subdomain.name}/{filename}'
    elif instance.symptom:
        category = 'symptoms'
        filename = f'{instance.symptom.name}/{filename}'
    else:
        category = 'unknown'
    return f'group_level_maps/{category}/{filename}'

"""Table Classes"""

class Level(models.Model):
    level_number = models.IntegerField(unique=True, editable=False)
    name = models.CharField(max_length=100)
    description = models.CharField(max_length=500, blank=True, null=True)
    insert_date = models.DateTimeField(auto_now_add=True)
    original_image_path = models.FileField(upload_to='original_images/', null=True, blank=True)
    lesion_mask_path = models.FileField(upload_to='true_masks/', null=True, blank=True)

    def __str__(self):
        return f"Level {self.level_number}: {self.name}"

    class Meta:
        db_table = 'levels'
        ordering = ['level_number']

    def save(self, *args, **kwargs):
        if not self.level_number:
            # Use a transaction to prevent race conditions
            with transaction.atomic():
                # Lock the table to prevent concurrent inserts
                last_level = Level.objects.select_for_update().aggregate(max_num=Max('level_number'))
                max_level_number = last_level['max_num'] or 0
                self.level_number = max_level_number + 1
        super().save(*args, **kwargs)

class UserLevelProgress(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='level_progress'
    )
    level = models.ForeignKey(
        Level,
        on_delete=models.CASCADE,
        related_name='user_progress'
    )
    date_completed = models.DateTimeField(auto_now_add=True)
    insert_date = models.DateTimeField(auto_now_add=True)
    score = models.FloatField(null=True, blank=True)

    class Meta:
        db_table = 'user_level_progress'
        unique_together = ('user', 'level')
        verbose_name = 'User Level Progress'
        verbose_name_plural = 'User Level Progresses'

    def __str__(self):
        return f"{self.user.username} - Level {self.level.level_number}"
    
    def update_score(self, new_score):
        if self.score is None or new_score > self.score:
            self.score = new_score
            self.date_completed = timezone.now() if new_score >= 70 else self.date_completed
            self.save()

class BaseModel(models.Model):
    insert_date = models.DateTimeField(default=now, null=False)
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE)

    class Meta:
        abstract = True

class MiscellaneousUpload(BaseModel):
    name = models.CharField(max_length=255)
    file = models.FileField(upload_to='uploads/')

    def __str__(self):
        return self.name

    class Meta:
        managed = True
        db_table = 'test_uploads'

class Parcellation(BaseModel):
    name = models.CharField(max_length=255)
    description = models.CharField(max_length=255)
    path = models.CharField(max_length=255, null=True, blank=True)
    md5 = models.CharField(max_length=255, null=True, blank=True)

    def __str__(self):
        return self.name
    
    class Meta:
        managed = False
        db_table = 'parcellations'

class Parcel(BaseModel):
    value = models.FloatField()
    label = models.CharField(max_length=255, null=True, blank=True)
    parcellation = models.ForeignKey(Parcellation, related_name='parcels', on_delete=models.CASCADE)

    def __str__(self):
        return self.label if self.label else str(self.value)
    
    class Meta:
        managed = False
        db_table = 'parcels'

class VoxelwiseValue(BaseModel):
    mni152_x = models.IntegerField()
    mni152_y = models.IntegerField()
    mni152_z = models.IntegerField()
    parcel = models.ForeignKey(Parcel, related_name='voxelwise_values', on_delete=models.CASCADE)

    def __str__(self):
        return f"Voxel({self.mni152_x}, {self.mni152_y}, {self.mni152_z})"
    
    class Meta:
        managed = False
        db_table = 'voxelwise_values'

class ParcelwiseConnectivityValue(BaseModel):
    value = models.FloatField()
    connectivity_file = models.ForeignKey('ConnectivityFile', related_name='parcelwise_connectivity_values', on_delete=models.CASCADE)
    parcel = models.ForeignKey('Parcel', related_name='parcelwise_connectivity_values', on_delete=models.CASCADE)

    class Meta:
        managed = False
        db_table = 'parcelwise_connectivity_values'

class ParcelwiseGroupLevelMapValue(BaseModel):
    value = models.FloatField()
    group_level_map_file = models.ForeignKey('GroupLevelMapFile', related_name='parcelwise_group_level_map_values', on_delete=models.CASCADE)
    parcel = models.ForeignKey('Parcel', related_name='parcelwise_group_level_map_values', on_delete=models.CASCADE)

    class Meta:
        managed = False
        db_table = 'parcelwise_group_level_map_values'

class ParcelwiseROIValue(BaseModel):
    value = models.FloatField()
    roi_file = models.ForeignKey('ROIFile', related_name='parcelwise_roi_values', on_delete=models.CASCADE)
    parcel = models.ForeignKey('Parcel', related_name='parcelwise_roi_values', on_delete=models.CASCADE)

    class Meta:
        managed = False
        db_table = 'parcelwise_roi_values'

class ConnectivityFile(BaseModel):
    filetype = models.CharField(max_length=255)
    path = models.FileField(upload_to=connectivity_file_path)
    md5 = models.CharField(max_length=255)
    subject = models.ForeignKey('Subject', related_name='connectivity_files', on_delete=models.CASCADE)
    parcellation = models.ForeignKey('Parcellation', related_name='connectivity_files', on_delete=models.CASCADE, null=True, blank=True)
    connectome = models.ForeignKey('Connectome', related_name='connectivity_files', on_delete=models.CASCADE)
    statistic_type = models.ForeignKey('StatisticType', related_name='connectivity_files', on_delete=models.CASCADE)
    coordinate_space = models.ForeignKey('CoordinateSpace', related_name='connectivity_files', on_delete=models.CASCADE)

    class Meta:
        managed = False
        db_table = 'connectivity_files'

    def delete_related_files(self):
        ParcelwiseConnectivityValue.objects.filter(connectivity_file=self).delete()
        if self.path:
            self.path.delete(save=False)

class GroupLevelMapFile(BaseModel):
    filetype = models.CharField(max_length=255)
    path = models.FileField(upload_to=group_level_map_file_path)
    md5 = models.CharField(max_length=255)
    control_cohort = models.CharField(max_length=255, null=True, blank=True)
    threshold = models.FloatField(null=True, blank=True)
    parcellation = models.ForeignKey('Parcellation', related_name='group_level_map_files', on_delete=models.CASCADE, null=True, blank=True)
    research_paper = models.ForeignKey('ResearchPaper', related_name='group_level_map_files_set', on_delete=models.CASCADE, null=True, blank=True)
    statistic_type = models.ForeignKey('StatisticType', related_name='group_level_map_files', on_delete=models.CASCADE)
    coordinate_space = models.ForeignKey('CoordinateSpace', related_name='group_level_map_files', on_delete=models.CASCADE)

    # New Foreign Keys
    map_type = models.ForeignKey(
        'MapType', 
        related_name='group_level_map_files', 
        on_delete=models.CASCADE
    )
    domain = models.ForeignKey(
        'Domain',
        related_name='group_level_map_files',
        on_delete=models.CASCADE,
        null=True,
        blank=True
    )
    subdomain = models.ForeignKey(
        'Subdomain',
        related_name='group_level_map_files',
        on_delete=models.CASCADE,
        null=True,
        blank=True
    )
    symptom = models.ForeignKey(
        'Symptom',
        related_name='group_level_map_files',
        on_delete=models.CASCADE,
        null=True,
        blank=True
    )

    class Meta:
        managed = False
        db_table = 'group_level_map_files'

    def __str__(self):
        return f"{self.filetype} - {self.path.name}"
    
    def clean(self):
        from django.core.exceptions import ValidationError
        if [self.domain, self.subdomain, self.symptom].count(None) < 2:
            raise ValidationError("GroupLevelMapFile must be associated with only one of Domain, Subdomain, or Symptom.")
        
    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def delete_related_files(self):
        print(f"Deleting related ParcelwiseGroupLevelMapValues for {self.id}")
        ParcelwiseGroupLevelMapValue.objects.filter(group_level_map_file=self).delete()
        if self.path:
            print(f"Deleting GroupLevelMapFile {self.id} file")
            self.path.delete(save=False)

    def delete(self, *args, **kwargs):
        print(f"Deleting GroupLevelMapFile {self.id}")
        self.delete_related_files()
        super(GroupLevelMapFile, self).delete(*args, **kwargs)

class MapType(BaseModel):
    name = models.CharField(max_length=255)
    description = models.TextField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = 'map_types'

    def __str__(self):
        return self.name

class ROIFile(BaseModel):
    filetype = models.CharField(max_length=255)
    path = models.FileField(upload_to=roi_file_path)
    md5 = models.CharField(max_length=255)
    voxel_count = models.IntegerField(null=True, blank=True)
    roi_type = models.CharField(max_length=255, null=True, blank=True)
    parcellation = models.ForeignKey('Parcellation', related_name='roi_files', on_delete=models.CASCADE, null=True, blank=True)
    subject = models.ForeignKey('Subject', related_name='roi_files', on_delete=models.CASCADE)
    dimension = models.ForeignKey('Dimension', related_name='roi_files', on_delete=models.CASCADE)
    coordinate_space = models.ForeignKey('CoordinateSpace', related_name='roi_files', on_delete=models.CASCADE)

    class Meta:
        managed = False
        db_table = 'roi_files'

    def delete_related_files(self):
        # Delete associated ParcelwiseConnectivityValue records
        ParcelwiseROIValue.objects.filter(roi_file=self).delete()
        # Delete the file itself
        if self.path:
            # Delete associated .npy file
            # npy_filename = self.path.name.replace('.nii.gz', '_parcellation-3209c91v.npy') # 'NoneType' object has no attribute 'replace'
            # self.path.storage.delete(npy_filename)
            # Delete the .nii.gz file
            self.path.delete(save=False)

class CoordinateSpace(BaseModel):
    name = models.CharField(max_length=255)

    class Meta:
        managed = False
        db_table = 'coordinate_spaces'

    def __str__(self):
        return self.name

class Dimension(BaseModel):
    name = models.CharField(max_length=255)
    description = models.TextField(null=True, blank=True)

    def __str__(self):
        return self.name
    
    class Meta:
        managed = False
        db_table = 'dimensions'

class StatisticType(BaseModel):
    name = models.CharField(max_length=255)
    code = models.CharField(max_length=255)
    description = models.TextField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = 'statistic_types'

    def __str__(self):
        return self.name

class Connectome(BaseModel):
    name = models.CharField(max_length=255)
    connectome_type = models.CharField(max_length=255, null=True, blank=True)
    description = models.CharField(max_length=255, null=True, blank=True)

    def __str__(self):
        return self.name
    
    class Meta:
        managed = False
        db_table = 'connectomes'

class Subject(BaseModel):
    age = models.IntegerField(null=True, blank=True)
    nickname = models.CharField(max_length=255, null=True, blank=True)
    internal_use_only = models.BooleanField(default=False)
    case_report = models.ForeignKey('CaseReport', related_name='subjects', on_delete=models.CASCADE, null=True, blank=True)
    patient_cohort = models.ForeignKey('PatientCohort', related_name='subjects', on_delete=models.CASCADE, null=True, blank=True)
    cause = models.ForeignKey('Cause', related_name='subjects', on_delete=models.CASCADE, null=True, blank=True)
    sex = models.ForeignKey('Sex', related_name='subjects', on_delete=models.CASCADE, null=True, blank=True)
    handedness = models.ForeignKey('Handedness', related_name='subjects', on_delete=models.CASCADE, null=True, blank=True)
    
    symptoms = models.ManyToManyField(
        'Symptom',
        through='SubjectSymptom',
        related_name='subjects_with_symptoms',  # Changed related_name to avoid conflict
        blank=True,
        help_text='Select symptoms associated with this subject.'
    )

    class Meta:
        managed = False
        db_table = 'subjects'

    def __str__(self):
        return f"Subject {self.id}"
    
    def delete_related_data(self):
        # Delete related files and data
        for roi_file in self.roi_files.all():
            roi_file.delete_related_files()
            roi_file.delete()
        for conn_file in self.connectivity_files.all():
            conn_file.delete_related_files()
            conn_file.delete()
        for orig_image in self.original_image_files.all():
            orig_image.delete_related_files()
            orig_image.delete()
    
class Sex(BaseModel):
    name = models.CharField(max_length=255, null=False, blank=False)

    def __str__(self):
        return self.name

    class Meta:
        managed = False
        db_table = 'sexes'

class Handedness(BaseModel):
    name = models.CharField(max_length=255)

    def __str__(self):
        return self.name

    class Meta:
        managed = False
        db_table = 'handedness'

class Cause(BaseModel):
    name = models.CharField(max_length=255)
    description = models.CharField(max_length=255, null=True, blank=True)

    def __str__(self):
        return self.name
    
    class Meta:
        managed = False
        db_table = 'causes'

class OriginalImageFile(BaseModel):
    path = models.FileField(upload_to=original_image_file_path)
    subject = models.ForeignKey('Subject', related_name='original_image_files', on_delete=models.CASCADE)
    image_modality = models.ForeignKey('ImageModality', related_name='original_image_files', on_delete=models.CASCADE)

    def __str__(self):
        return self.path
    
    class Meta:
        managed = False
        db_table = 'original_image_files'

    def delete_related_files(self):
        # Delete the file itself
        if self.path:
            self.path.delete(save=False)

class ImageModality(BaseModel):
    name = models.CharField(max_length=255)
    description = models.CharField(max_length=255, null=True, blank=True)

    def __str__(self):
        return self.name
    
    class Meta:
        managed = False
        db_table = 'image_modalities'
        
def case_report_file_path(instance, filename):
    # URL-encode the DOI
    doi = instance.doi or f'unknown{instance.id}'
    doi_encoded = quote_plus(doi)
    print(f'case_reports/doi-{doi_encoded}/doi-{doi_encoded}.pdf')
    return f'case_reports/doi-{doi_encoded}/doi-{doi_encoded}.pdf'

class CaseReport(BaseModel):
    doi = models.CharField(max_length=255, null=True, blank=True)
    pubmed_id = models.IntegerField(null=True, blank=True)
    other_citation = models.CharField(max_length=255, null=True, blank=True)
    title = models.CharField(max_length=255, null=True, blank=True)
    first_author = models.CharField(max_length=255, null=True, blank=True)
    year = models.IntegerField(null=True, blank=True)
    abstract = models.CharField(max_length=2500, null=True, blank=True)
    path = models.FileField(upload_to=case_report_file_path, null=True, blank=True)
    is_open_access = models.BooleanField()
    symptoms = models.ManyToManyField(
        'Symptom',
        through='CaseReportSymptom',
        related_name='case_reports',
        blank=True,
        help_text='Select relevant symptoms associated with this case report.'
    )

    def __str__(self):
        return self.title if self.title else f"CaseReport {self.id}"
    
    class Meta:
        managed = False
        db_table = 'case_reports'

class PatientCohort(BaseModel):
    name = models.CharField(max_length=255)
    doi = models.CharField(max_length=255, null=True, blank=True)
    pubmed_id = models.IntegerField(null=True, blank=True)
    other_citation = models.CharField(max_length=255, null=True, blank=True)
    source = models.CharField(max_length=255, null=True, blank=True)
    first_author = models.CharField(max_length=255, null=True, blank=True)
    year = models.IntegerField(null=True, blank=True)
    description = models.CharField(max_length=255, null=True, blank=True)

    def __str__(self):
        return self.name
    
    class Meta:
        managed = False
        db_table = 'patient_cohorts'

class CaseReportSymptom(BaseModel):
    case_report = models.ForeignKey('CaseReport', on_delete=models.CASCADE)
    symptom = models.ForeignKey('Symptom', on_delete=models.CASCADE)

    class Meta:
        managed = False
        db_table = 'case_reports_symptoms'

class InclusionCriteria(BaseModel):
    is_case_study = models.BooleanField()
    is_english = models.BooleanField()
    is_relevant_symptoms = models.BooleanField()
    is_relevant_clinical_scores = models.BooleanField()
    is_full_text = models.BooleanField()
    is_temporally_linked = models.BooleanField()
    is_brain_scan = models.BooleanField()
    is_included = models.BooleanField()
    notes = models.TextField(null=True, blank=True)
    patient_cohort = models.ForeignKey('PatientCohort', related_name='inclusion_criteria', on_delete=models.CASCADE, null=True, blank=True)
    case_report = models.ForeignKey('CaseReport', related_name='inclusion_criteria', on_delete=models.CASCADE, null=True, blank=True)

    class Meta:
        managed = False
        db_table = 'inclusion_criteria'

class SubjectSymptom(BaseModel):
    subject = models.ForeignKey('Subject', on_delete=models.CASCADE)
    symptom = models.ForeignKey('Symptom', on_delete=models.CASCADE)

    class Meta:
        managed = False
        db_table = 'subjects_symptoms'

class Symptom(BaseModel):
    name = models.CharField(max_length=255)
    description = models.TextField(null=True, blank=True)
    domain = models.ForeignKey('Domain', related_name='symptoms', on_delete=models.CASCADE)
    subdomain = models.ForeignKey('Subdomain', related_name='symptoms', on_delete=models.CASCADE, null=True, blank=True)
    research_papers = models.ManyToManyField('ResearchPaper', through='ResearchPaperSymptom', related_name='symptoms_m2m')
    internal_use_only = models.BooleanField(default=False)


    class Meta:
        managed = False
        db_table = 'symptoms'

    def __str__(self):
        domain_name = self.domain.name.capitalize()
        subdomain_name = self.subdomain.name.capitalize() if self.subdomain else 'N/A'
        return f"{self.name.capitalize()} ({domain_name}, {subdomain_name})"
    
class Synonym(BaseModel):
    name = models.CharField(max_length=255)
    symptom = models.ForeignKey('Symptom', related_name='synonyms', on_delete=models.CASCADE)

    class Meta:
        managed = False
        db_table = 'synonyms'

class MeshTerm(BaseModel):
    name = models.CharField(max_length=255)
    symptom = models.ForeignKey('Symptom', related_name='mesh_terms', on_delete=models.CASCADE)

    class Meta:
        managed = False
        db_table = 'mesh_terms'

class Domain(BaseModel):
    name = models.CharField(max_length=255)
    description = models.TextField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = 'domains'

    def __str__(self):
        return self.name

class Subdomain(BaseModel):
    name = models.CharField(max_length=255)
    description = models.TextField(null=True, blank=True)
    domain = models.ForeignKey('Domain', related_name='subdomains', on_delete=models.CASCADE)

    class Meta:
        managed = False
        db_table = 'subdomains'

    def __str__(self):
        return self.name

class SubjectResearchPaper(models.Model):
    research_paper = models.ForeignKey('ResearchPaper', on_delete=models.CASCADE)
    subject = models.ForeignKey('Subject', on_delete=models.CASCADE)

    class Meta:
        managed = False
        db_table = 'subjects_research_papers'

class ResearchPaper(BaseModel):
    doi = models.CharField(max_length=255, null=True, blank=True)
    pubmed_id = models.IntegerField(null=True, blank=True)
    other_citation = models.CharField(max_length=255, null=True, blank=True)
    title = models.CharField(max_length=255, null=True, blank=True)
    year = models.IntegerField(null=True, blank=True)
    abstract = models.TextField(null=True, blank=True)
    nickname = models.CharField(max_length=255, null=True, blank=True)
    comments = models.TextField(null=True, blank=True)
    first_author = models.ForeignKey('Author', related_name='first_authored_papers_set', on_delete=models.CASCADE)
    authors = models.ManyToManyField('Author', through='ResearchPaperAuthor', related_name='co_authored_papers_set')
    # group_level_map_files = models.ForeignKey('GroupLevelMapFile', related_name='research_papers_set', on_delete=models.CASCADE, null=True, blank=True)
    symptoms = models.ManyToManyField('Symptom', through='ResearchPaperSymptom', related_name='research_papers_set')
    tags = models.ManyToManyField('Tag', related_name='research_papers')
    subjects = models.ManyToManyField('Subject', through='SubjectResearchPaper', related_name='research_papers')

    class Meta:
        managed = False
        db_table = 'research_papers'

    def get_author_names(self):
        return ', '.join([author.name for author in self.authors.all()])
    
    def get_title(self):
        return self.title.replace('_', ' ')

class ResearchPaperAuthor(models.Model):
    research_paper = models.ForeignKey('ResearchPaper', on_delete=models.CASCADE)
    author = models.ForeignKey('Author', on_delete=models.CASCADE)

    class Meta:
        managed = False
        db_table = 'research_papers_authors'

class Author(BaseModel):
    name = models.CharField(max_length=255)
    email = models.CharField(max_length=255, null=True, blank=True)
    institution = models.CharField(max_length=255, null=True, blank=True)
    # first_authored_papers = models.ForeignKey('ResearchPaper', related_name='first_author_set', on_delete=models.CASCADE)
    # co_authored_papers = models.ManyToManyField('ResearchPaper', through='ResearchPaperAuthors', related_name='co_authors_set')

    class Meta:
        managed = False
        db_table = 'authors'

class ResearchPaperSymptom(models.Model):
    research_paper = models.ForeignKey('ResearchPaper', on_delete=models.CASCADE)
    symptom = models.ForeignKey('Symptom', on_delete=models.CASCADE)

    class Meta:
        managed = False
        db_table = 'research_papers_symptoms'

class ClinicalMeasure(BaseModel):
    metric_name = models.CharField(max_length=255)
    value = models.FloatField()
    unit = models.CharField(max_length=255, null=True, blank=True)
    timepoint = models.IntegerField(null=True, blank=True)
    subject = models.ForeignKey('Subject', related_name='clinical_measures', on_delete=models.CASCADE)

    class Meta:
        managed = False
        db_table = 'clinical_measures'

class Tag(BaseModel):
    name = models.CharField(max_length=255)
    description = models.TextField(null=True, blank=True)
    research_paper = models.ForeignKey('ResearchPaper', related_name='tags_fk', on_delete=models.CASCADE)

    class Meta:
        managed = False
        db_table = 'tags'

class UsageLog(models.Model):
    page_name = models.CharField(max_length=255)
    insert_date = models.DateTimeField(default=now, null=False)
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE)

    class Meta:
        managed = False
        db_table = 'usage_logs'