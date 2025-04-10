from sqlalchemy import Integer, String, Float, Boolean, ForeignKey, func, DateTime
from sqlalchemy.orm import Mapped, mapped_column, DeclarativeBase, relationship, declared_attr
from typing import List, Optional, Union
from datetime import datetime
from sqlalchemy.schema import UniqueConstraint
from sqlalchemy.orm import validates
from sqlalchemy.exc import IntegrityError

class TrueBase(DeclarativeBase):
    pass

class User(TrueBase):
    __tablename__ = 'accounts_customuser'
    
    # Properties
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(150), unique=True, nullable=False)
    email: Mapped[Optional[str]] = mapped_column(String(254), unique=True, nullable=True)
    password: Mapped[str] = mapped_column(String(128), nullable=False)
    first_name: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    last_name: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_staff: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    date_joined: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)
    last_login: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Relationships
    inclusion_criteria: Mapped[List["InclusionCriteria"]] = relationship('InclusionCriteria', back_populates='user')
    level_progress: Mapped[List["UserLevelProgress"]] = relationship('UserLevelProgress', back_populates='user')
    usage_logs: Mapped[List["UsageLog"]] = relationship('UsageLog', back_populates='user')

class BaseNoUser(TrueBase):
    __abstract__ = True

    insert_date: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)

class Base(TrueBase):
    __abstract__ = True

    insert_date: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)
    
    @declared_attr
    def user_id(cls) -> Mapped[int]:
        return mapped_column(ForeignKey('accounts_customuser.id'), nullable=False)

    @declared_attr
    def user(cls) -> Mapped["User"]:
        return relationship('User')
    
"""Table Section:
Handling user progress through the levels of the lesion tracing practice.
Tables in this section:
- levels: Each row represents a level in the lesion tracing practice. Associated with user level progress.
- user_level_progress: Each row represents a user's progress through a level. Associated with a user and a level.
"""

class Level(BaseNoUser):
    __tablename__ = 'levels'
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    level_number: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    original_image_path: Mapped[str] = mapped_column(String(500), nullable=True)
    lesion_mask_path: Mapped[str] = mapped_column(String(500), nullable=True)
    
    # Relationships
    user_progress: Mapped[List["UserLevelProgress"]] = relationship('UserLevelProgress', back_populates='level', cascade='all, delete-orphan')
    
    def __repr__(self):
        return f"<Level(id={self.id}, level_number={self.level_number}, name='{self.name}')>"

class UserLevelProgress(Base):
    __tablename__ = 'user_level_progress'
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date_completed: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)
    # Removed: user_uploaded_mask: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    insert_date: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)
    score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    
    # Foreign Keys
    user_id: Mapped[int] = mapped_column(ForeignKey('accounts_customuser.id'), nullable=False)
    level_id: Mapped[int] = mapped_column(ForeignKey('levels.id'), nullable=False)
    
    # Relationships
    user: Mapped["User"] = relationship('User', back_populates='level_progress')
    level: Mapped["Level"] = relationship('Level', back_populates='user_progress')
    
    # Constraints
    __table_args__ = (
        UniqueConstraint('user_id', 'level_id', name='_user_level_uc'),
    )
    
    def __repr__(self):
        return f"<UserLevelProgress(user_id={self.user_id}, level_id={self.level_id}, date_completed={self.date_completed})>"
    
"""
Table Section: Arrays, parcellations, imaging files, parcels, and connectomes; Everything for querying imaging data.

Tables in this section:
- voxelwise_values: Each row represents a voxel in 3D MNI space. Associated with a parcel in a corresponding parcellation.
- parcels: Each row represents a parcel in a parcellation. Associated with a parcellation.
- parcellations: Each row represents a parcellation. Associated with parcels.
- parcelwise_connectivity_values: Each row represents the parcel value of a parcellated connectivity map. Associated with a parcel in a parcellation, and a connectivity file.
- parcelwise_group_level_map_values: Each row represents the parcel value of a parcellated group level map. Associated with a parcel in a parcellation, and a group level map file.
- parcelwise_roi_values: Each row represents the parcel value of a parcellated ROI map. Associated with a parcel in a parcellation, and an ROI file.
- connectivity_files: Each row represents a connectivity file. Associated with a subject, connectome, and parcellation.
- roi_files: Each row represents an ROI file. Associated with a subject, and parcellation.
- group_level_map_files: Each row represents a group level map file. Associated with a research paper, and parcellation.
- connectomes: Each row represents a connectome. Associated with connectivity files.

Common Queries:
- Find all subjects whose ROI arrays touch MNI coords (x, y, z)
- Find all subjects whose connectivity arrays are above t>5 at MNI coords (x, y, z)
- Find all subjects mapped with the GSP1000MF connectome

Notes:
- All connectivity maps, ROI maps, and group level maps should be parcellated rather than voxelwise, because this reduces the dimensionality of the data and makes it easier to query.
- Files in connectivity_files, roi_files, and group_level_map_files will probably be saved in s3; we'll have to think about how to handle this later.
"""

class Symptom(Base):
    __tablename__ = 'symptoms'
    
    # Properties
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String)
    description: Mapped[Optional[str]] = mapped_column(String)
    internal_use_only: Mapped[bool] = mapped_column(Boolean, default=False)

    # Foreign keys
    domain_id: Mapped[int] = mapped_column(ForeignKey('domains.id'))
    subdomain_id: Mapped[int] = mapped_column(ForeignKey('subdomains.id'))

    # Relationships
    subjects: Mapped[List["Subject"]] = relationship('Subject', secondary='subjects_symptoms', back_populates='symptoms')
    research_papers: Mapped[List["ResearchPaper"]] = relationship('ResearchPaper', secondary='research_papers_symptoms', back_populates='symptoms')
    synonyms: Mapped[List["Synonym"]] = relationship('Synonym', back_populates='symptom')
    domain: Mapped["Domain"] = relationship('Domain', back_populates='symptoms')
    subdomain: Mapped["Subdomain"] = relationship('Subdomain', back_populates='symptoms')
    synonyms: Mapped[List["Synonym"]] = relationship('Synonym', back_populates='symptom')
    mesh_terms: Mapped[List["MeshTerm"]] = relationship('MeshTerm', back_populates='symptoms')
    case_reports: Mapped[List["CaseReport"]] = relationship('CaseReport', secondary='case_reports_symptoms', back_populates='symptoms')
    group_level_map_files: Mapped[List["GroupLevelMapFile"]] = relationship('GroupLevelMapFile', back_populates='symptom')

class VoxelwiseValue(Base):  
    __tablename__ = 'voxelwise_values'

    # Properties
    id: Mapped[int] = mapped_column(primary_key=True)
    mni152_x: Mapped[int] = mapped_column(Integer)
    mni152_y: Mapped[int] = mapped_column(Integer)
    mni152_z: Mapped[int] = mapped_column(Integer)
    
    # Foreign keys
    parcel_id: Mapped[int] = mapped_column(ForeignKey('parcels.id'))
    
    # Relationships
    parcel: Mapped["Parcel"] = relationship('Parcel', back_populates='voxelwise_values')

class Parcel(Base):
    __tablename__ = 'parcels'
    
    # Properties (native columns)
    id: Mapped[int] = mapped_column(primary_key=True)
    value: Mapped[float] = mapped_column(Float)
    label: Mapped[Optional[str]] = mapped_column(String)

    # Foreign keys (foreign columns)
    parcellation_id: Mapped[int] = mapped_column(ForeignKey('parcellations.id'))
    
    # Relationships
    parcellation: Mapped["Parcellation"] = relationship('Parcellation', back_populates='parcels')
    voxelwise_values: Mapped[List["VoxelwiseValue"]] = relationship('VoxelwiseValue', back_populates='parcel')
    parcelwise_connectivity_values: Mapped[List["ParcelwiseConnectivityValue"]] = relationship('ParcelwiseConnectivityValue', back_populates='parcel')
    parcelwise_roi_values: Mapped[List["ParcelwiseROIValue"]] = relationship('ParcelwiseROIValue', back_populates='parcel')
    parcelwise_group_level_map_values: Mapped[List["ParcelwiseGroupLevelMapValue"]] = relationship('ParcelwiseGroupLevelMapValue', back_populates='parcel')

class Parcellation(Base):
    __tablename__ = 'parcellations'
    
    # Properties
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String)
    description: Mapped[str] = mapped_column(String)
    path: Mapped[Optional[str]] = mapped_column(String)
    md5: Mapped[Optional[str]] = mapped_column(String)
    
    # Relationships
    parcels: Mapped[List["Parcel"]] = relationship('Parcel', back_populates='parcellation')
    roi_files: Mapped[List["ROIFile"]] = relationship('ROIFile', back_populates='parcellation')
    connectivity_files: Mapped[List["ConnectivityFile"]] = relationship('ConnectivityFile', back_populates='parcellation')
    group_level_map_files: Mapped[List["GroupLevelMapFile"]] = relationship('GroupLevelMapFile', back_populates='parcellation')

class ParcelwiseConnectivityValue(Base):
    __tablename__ = 'parcelwise_connectivity_values'
    
    # Properties
    id: Mapped[int] = mapped_column(primary_key=True)
    value: Mapped[float] = mapped_column(Float)
    
    # Foreign keys
    connectivity_file_id: Mapped[int] = mapped_column(ForeignKey('connectivity_files.id'))
    parcel_id: Mapped[int] = mapped_column(ForeignKey('parcels.id'))
    
    # Relationships
    parcel: Mapped["Parcel"] = relationship('Parcel', back_populates='parcelwise_connectivity_values')
    connectivity_file: Mapped["ConnectivityFile"] = relationship('ConnectivityFile', back_populates='parcelwise_connectivity_values')

class ParcelwiseGroupLevelMapValue(Base):
    __tablename__ = 'parcelwise_group_level_map_values'
    
    # Properties
    id: Mapped[int] = mapped_column(primary_key=True)
    value: Mapped[float] = mapped_column(Float)
    
    # Foreign keys
    group_level_map_file_id: Mapped[int] = mapped_column(ForeignKey('group_level_map_files.id'))
    parcel_id: Mapped[int] = mapped_column(ForeignKey('parcels.id'))
    
    # Relationships
    parcel: Mapped["Parcel"] = relationship('Parcel', back_populates='parcelwise_group_level_map_values')
    group_level_map_file: Mapped["GroupLevelMapFile"] = relationship('GroupLevelMapFile', back_populates='parcelwise_group_level_map_values')

class ParcelwiseROIValue(Base):
    __tablename__ = 'parcelwise_roi_values'
    
    # Properties
    id: Mapped[int] = mapped_column(primary_key=True)
    value: Mapped[float] = mapped_column(Float)
    
    # Foreign keys
    roi_file_id: Mapped[int] = mapped_column(ForeignKey('roi_files.id'))
    parcel_id: Mapped[int] = mapped_column(ForeignKey('parcels.id'))
    
    # Relationships
    parcel: Mapped["Parcel"] = relationship('Parcel', back_populates='parcelwise_roi_values')
    roi_file: Mapped["ROIFile"] = relationship('ROIFile', back_populates='parcelwise_roi_values')

class StatisticType(Base):
    __tablename__ = 'statistic_types'

    # Properties
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String)
    code: Mapped[str] = mapped_column(String)
    description: Mapped[Optional[str]] = mapped_column(String)

    # Relationships
    connectivity_files: Mapped[List["ConnectivityFile"]] = relationship('ConnectivityFile', back_populates='statistic_type')
    group_level_map_files: Mapped[List["GroupLevelMapFile"]] = relationship('GroupLevelMapFile', back_populates='statistic_type')

    def __repr__(self):
        return f"<StatisticType(id={self.id}, name='{self.name}')>"

class ConnectivityFile(Base):
    __tablename__ = 'connectivity_files'
    
    # Properties
    id: Mapped[int] = mapped_column(primary_key=True)
    filetype: Mapped[str] = mapped_column(String)
    path: Mapped[str] = mapped_column(String)
    md5: Mapped[str] = mapped_column(String)

    # Foreign keys
    subject_id: Mapped[int] = mapped_column(ForeignKey('subjects.id'))
    parcellation_id: Mapped[Optional[int]] = mapped_column(ForeignKey('parcellations.id'))
    connectome_id: Mapped[int] = mapped_column(ForeignKey('connectomes.id'))
    statistic_type_id: Mapped[int] = mapped_column(ForeignKey('statistic_types.id'))
    coordinate_space_id: Mapped[int] = mapped_column(ForeignKey('coordinate_spaces.id'))

    # Relationships
    connectome: Mapped["Connectome"] = relationship('Connectome', back_populates='connectivity_files')
    parcellation: Mapped["Parcellation"] = relationship('Parcellation', back_populates='connectivity_files')
    subject: Mapped["Subject"] = relationship('Subject', back_populates='connectivity_files')
    parcelwise_connectivity_values: Mapped[List["ParcelwiseConnectivityValue"]] = relationship('ParcelwiseConnectivityValue', back_populates='connectivity_file')
    statistic_type: Mapped["StatisticType"] = relationship('StatisticType', back_populates='connectivity_files')
    coordinate_space: Mapped["CoordinateSpace"] = relationship('CoordinateSpace', back_populates='connectivity_files')

class ROIFile(Base):
    __tablename__ = 'roi_files'
    
    # Properties
    id: Mapped[int] = mapped_column(primary_key=True)
    filetype: Mapped[str] = mapped_column(String)
    path: Mapped[str] = mapped_column(String)
    md5: Mapped[str] = mapped_column(String)
    voxel_count: Mapped[Optional[int]] = mapped_column(Integer)
    roi_type: Mapped[Optional[str]] = mapped_column(String)
    
    # Foreign keys
    parcellation_id: Mapped[Optional[int]] = mapped_column(ForeignKey('parcellations.id'))
    subject_id: Mapped[int] = mapped_column(ForeignKey('subjects.id'))
    dimension_id: Mapped[int] = mapped_column(ForeignKey('dimensions.id'))
    coordinate_space_id: Mapped[int] = mapped_column(ForeignKey('coordinate_spaces.id'))
    
    # Relationships
    parcellation: Mapped["Parcellation"] = relationship('Parcellation', back_populates='roi_files')
    parcelwise_roi_values: Mapped[List["ParcelwiseROIValue"]] = relationship('ParcelwiseROIValue', back_populates='roi_file')
    subject: Mapped["Subject"] = relationship('Subject', back_populates='roi_files')
    dimension: Mapped["Dimension"] = relationship('Dimension', back_populates='roi_files')
    coordinate_space: Mapped["CoordinateSpace"] = relationship('CoordinateSpace', back_populates='roi_files')

class CoordinateSpace(Base):
    __tablename__ = 'coordinate_spaces'

    # Properties
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String)

    # Relationships
    connectivity_files: Mapped[List["ConnectivityFile"]] = relationship('ConnectivityFile', back_populates='coordinate_space')
    roi_files: Mapped[List["ROIFile"]] = relationship('ROIFile', back_populates='coordinate_space')
    group_level_map_files: Mapped[List["GroupLevelMapFile"]] = relationship('GroupLevelMapFile', back_populates='coordinate_space')

    def __repr__(self):
        return f"<CoordinateSpace(id={self.id}, name='{self.name}')>"

class Dimension(Base):
    __tablename__ = 'dimensions'
    
    # Properties
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String)
    description: Mapped[Optional[str]] = mapped_column(String)

    # Relationships
    roi_files: Mapped[List["ROIFile"]] = relationship('ROIFile', back_populates='dimension')

class GroupLevelMapFile(Base):
    __tablename__ = 'group_level_map_files'
    
    # Properties
    id: Mapped[int] = mapped_column(primary_key=True)
    filetype: Mapped[str] = mapped_column(String)
    path: Mapped[str] = mapped_column(String)
    md5: Mapped[str] = mapped_column(String)
    control_cohort: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    threshold: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    
    # Foreign keys
    parcellation_id: Mapped[Optional[int]] = mapped_column(ForeignKey('parcellations.id'))
    statistic_type_id: Mapped[int] = mapped_column(ForeignKey('statistic_types.id'))
    coordinate_space_id: Mapped[int] = mapped_column(ForeignKey('coordinate_spaces.id'))
    research_paper_id: Mapped[Optional[int]] = mapped_column(ForeignKey('research_papers.id'), nullable=True)

    # New Foreign keys
    map_type_id: Mapped[int] = mapped_column(ForeignKey('map_types.id'), nullable=False)
    domain_id: Mapped[Optional[int]] = mapped_column(ForeignKey('domains.id'), nullable=True)
    subdomain_id: Mapped[Optional[int]] = mapped_column(ForeignKey('subdomains.id'), nullable=True)
    symptom_id: Mapped[Optional[int]] = mapped_column(ForeignKey(Symptom.__tablename__ + '.id'), nullable=True)
    
    # Relationships
    parcellation: Mapped["Parcellation"] = relationship('Parcellation', back_populates='group_level_map_files')
    parcelwise_group_level_map_values: Mapped[List["ParcelwiseGroupLevelMapValue"]] = relationship('ParcelwiseGroupLevelMapValue', back_populates='group_level_map_file')
    research_paper: Mapped["ResearchPaper"] = relationship('ResearchPaper', back_populates='group_level_map_files')
    statistic_type: Mapped["StatisticType"] = relationship('StatisticType', back_populates='group_level_map_files')
    coordinate_space: Mapped["CoordinateSpace"] = relationship('CoordinateSpace', back_populates='group_level_map_files')
    domain: Mapped["Domain"] = relationship('Domain', back_populates='group_level_map_files')
    subdomain: Mapped["Subdomain"] = relationship('Subdomain', back_populates='group_level_map_files')
    symptom: Mapped["Symptom"] = relationship('Symptom', back_populates='group_level_map_files')
    map_type: Mapped["MapType"] = relationship('MapType', back_populates='group_level_map_files')

    @validates('domain_id', 'subdomain_id', 'symptom_id')
    def validate_single_association(self, key, value):
        if key == 'domain_id' and value:
            if self.subdomain_id or self.symptom_id:
                raise ValueError("GroupLevelMapFile can only be associated with one of Domain, Subdomain, or Symptom.")
        elif key == 'subdomain_id' and value:
            if self.domain_id or self.symptom_id:
                raise ValueError("GroupLevelMapFile can only be associated with one of Domain, Subdomain, or Symptom.")
        elif key == 'symptom_id' and value:
            if self.domain_id or self.subdomain_id:
                raise ValueError("GroupLevelMapFile can only be associated with one of Domain, Subdomain, or Symptom.")
        return value    

class MapType(Base):
    __tablename__ = 'map_types'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    # Relationships
    group_level_map_files: Mapped[List["GroupLevelMapFile"]] = relationship(
        'GroupLevelMapFile', back_populates='map_type'
    )

    def __repr__(self):
        return f"<MapType(id={self.id}, name='{self.name}')>"

class Connectome(Base):
    __tablename__ = 'connectomes'
    
    # Properties
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String)
    connectome_type: Mapped[Optional[str]] = mapped_column(String)
    description: Mapped[Optional[str]] = mapped_column(String)

    # Relationships
    connectivity_files: Mapped[List["ConnectivityFile"]] = relationship('ConnectivityFile', back_populates='connectome')

"""
Table Section: Subjects, original imaging files, case reports, and patient cohorts;

Tables in this section:
- subjects: Each row represents a subject. Associated with case reports and patient cohorts.
- original_image_files: Each row represents an original image file. Associated with a subject and an image modality.
- image_modalities: Each row represents an image modality. Associated with original image files.
- case_reports: Each row represents a case report. Associated with subjects.
- patient_cohorts: Each row represents a patient cohort. Associated with subjects.
- causes: Each row represents a cause. Associated with subjects.

Common Queries:
- Find all subjects with of a certain age/sex, etc
- Find all subjects with a certain lesion
- Find all subjects from cohort X
"""

class Subject(Base):
    __tablename__ = 'subjects'
    
    # Properties
    id: Mapped[int] = mapped_column(primary_key=True)
    age: Mapped[Optional[int]] = mapped_column(Integer)
    nickname: Mapped[Optional[str]] = mapped_column(String)
    internal_use_only: Mapped[bool] = mapped_column(Boolean, default=False)

    # Foreign keys
    case_report_id: Mapped[Optional[int]] = mapped_column(ForeignKey('case_reports.id'))
    patient_cohort_id: Mapped[Optional[int]] = mapped_column(ForeignKey('patient_cohorts.id'))
    cause_id: Mapped[Optional[int]] = mapped_column(ForeignKey('causes.id'))
    sex_id: Mapped[Optional[int]] = mapped_column(ForeignKey('sexes.id'))
    handedness_id: Mapped[Optional[int]] = mapped_column(ForeignKey('handedness.id'))

    # Relationships
    connectivity_files: Mapped[List["ConnectivityFile"]] = relationship('ConnectivityFile', back_populates='subject')
    roi_files: Mapped[List["ROIFile"]] = relationship('ROIFile', back_populates='subject')
    original_image_files: Mapped[List["OriginalImageFile"]] = relationship('OriginalImageFile', back_populates='subject')
    case_report: Mapped["CaseReport"] = relationship('CaseReport', back_populates='subjects')
    patient_cohort: Mapped["PatientCohort"] = relationship('PatientCohort', back_populates='subjects')
    symptoms: Mapped[List["Symptom"]] = relationship('Symptom', secondary='subjects_symptoms', back_populates='subjects')
    clinical_measures: Mapped[List["ClinicalMeasure"]] = relationship('ClinicalMeasure', back_populates='subject')
    cause: Mapped["Cause"] = relationship('Cause', back_populates='subjects')
    sex: Mapped["Sex"] = relationship('Sex', back_populates='subjects')
    handedness: Mapped["Handedness"] = relationship('Handedness', back_populates='subjects')
    research_papers: Mapped[List["ResearchPaper"]] = relationship('ResearchPaper', secondary='subjects_research_papers', back_populates='subjects')

class SubjectResearchPaper(BaseNoUser):
    __tablename__ = 'subjects_research_papers'

    research_paper_id: Mapped[int] = mapped_column(ForeignKey('research_papers.id'), primary_key=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey('subjects.id'), primary_key=True)

class Sex(Base):
    __tablename__ = 'sexes'

    # Properties
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String)

    # Relationships
    subjects: Mapped[List["Subject"]] = relationship('Subject', back_populates='sex')

class Handedness(Base):
    __tablename__ = 'handedness'

    # Properties
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String)

    # Relationships
    subjects: Mapped[List["Subject"]] = relationship('Subject', back_populates='handedness')

class Cause(Base):
    __tablename__ = 'causes'
    
    # Properties
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String)
    description: Mapped[Optional[str]] = mapped_column(String)

    # Relationships
    subjects: Mapped[List["Subject"]] = relationship('Subject', back_populates='cause')

class OriginalImageFile(Base):
    __tablename__ = 'original_image_files'
    
    # Properties
    id: Mapped[int] = mapped_column(primary_key=True)
    path: Mapped[str] = mapped_column(String)

    # Foreign keys:
    subject_id: Mapped[int] = mapped_column(ForeignKey('subjects.id'))
    image_modality_id: Mapped[int] = mapped_column(ForeignKey('image_modalities.id'))

    # Relationships
    subject: Mapped["Subject"] = relationship('Subject', back_populates='original_image_files')
    image_modality: Mapped["ImageModality"] = relationship('ImageModality', back_populates='original_image_files')

class ImageModality(Base):
    __tablename__ = 'image_modalities'
    
    # Properties
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String)
    description: Mapped[Optional[str]] = mapped_column(String)

    # Relationships
    original_image_files: Mapped[List["OriginalImageFile"]] = relationship('OriginalImageFile', back_populates='image_modality')

class CaseReport(Base):
    __tablename__ = 'case_reports'
    
    # Properties
    id: Mapped[int] = mapped_column(primary_key=True)
    doi: Mapped[Optional[str]] = mapped_column(String)
    pubmed_id: Mapped[Optional[int]] = mapped_column(Integer)
    other_citation: Mapped[Optional[str]] = mapped_column(String)
    title: Mapped[Optional[str]] = mapped_column(String)
    first_author: Mapped[Optional[str]] = mapped_column(String)
    year: Mapped[Optional[int]] = mapped_column(Integer)
    abstract: Mapped[Optional[str]] = mapped_column(String)
    path: Mapped[Optional[str]] = mapped_column(String)
    is_open_access: Mapped[bool] = mapped_column(Boolean)

    # Relationships
    subjects: Mapped[List["Subject"]] = relationship('Subject', back_populates='case_report')
    inclusion_criteria: Mapped[List["InclusionCriteria"]] = relationship('InclusionCriteria', back_populates='case_report')
    symptoms: Mapped[List["Symptom"]] = relationship('Symptom', secondary='case_reports_symptoms', back_populates='case_reports')

class PatientCohort(Base):
    __tablename__ = 'patient_cohorts'
    
    # Properties
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String)
    doi: Mapped[Optional[str]] = mapped_column(String)
    pubmed_id: Mapped[Optional[int]] = mapped_column(Integer)
    other_citation: Mapped[Optional[str]] = mapped_column(String)
    source: Mapped[Optional[str]] = mapped_column(String)
    first_author: Mapped[Optional[str]] = mapped_column(String)
    year: Mapped[Optional[int]] = mapped_column(Integer)
    description: Mapped[Optional[str]] = mapped_column(String)

    # Relationships
    subjects: Mapped[List["Subject"]] = relationship('Subject', back_populates='patient_cohort')
    inclusion_criteria: Mapped[List["InclusionCriteria"]] = relationship('InclusionCriteria', back_populates='patient_cohort')

"""
Table Section: Research papers, symptoms, clinical scores, inclusion criteria

Tables in this section:
- inclusion_criteria: Each row represents the inclusion criteria for a subject. Associated with a patient cohort or case report.
- subjects_symptoms: Each row represents a subject's symptoms. Associated with a subject and a symptom.
- symptoms: Each row represents a symptom. Associated with subjects and research papers.
- research_papers: Each row represents a research paper. Associated with symptoms and tags.
- research_papers_symptoms: Each row represents a research paper's symptoms. Associated with a research paper and a symptom.
- clinical_measures: Each row represents a clinical measure. Associated with a subject.
- tags: Each row represents a tag. Associated with a research paper.

Common Queries:
- Find all subjects with a certain symptom
- Find all research papers with a certain symptom
- Find all research papers with a certain tag
- Find all research papers with a certain clinical score
- Find all subjects with certain inclusion criteria
"""

class InclusionCriteria(Base):
    __tablename__ = 'inclusion_criteria'
    
    # Properties
    id: Mapped[int] = mapped_column(primary_key=True)
    is_case_study: Mapped[bool] = mapped_column(Boolean)
    is_english: Mapped[bool] = mapped_column(Boolean)
    is_relevant_symptoms: Mapped[bool] = mapped_column(Boolean)
    is_relevant_clinical_scores: Mapped[bool] = mapped_column(Boolean)
    is_full_text: Mapped[bool] = mapped_column(Boolean)
    is_temporally_linked: Mapped[bool] = mapped_column(Boolean)
    is_brain_scan: Mapped[bool] = mapped_column(Boolean)
    is_included: Mapped[bool] = mapped_column(Boolean)
    notes: Mapped[Optional[str]] = mapped_column(String)

    # Foreign keys
    patient_cohort_id: Mapped[Optional[int]] = mapped_column(ForeignKey('patient_cohorts.id'))
    case_report_id: Mapped[Optional[int]] = mapped_column(ForeignKey('case_reports.id'))

    # Relationships
    patient_cohort: Mapped["PatientCohort"] = relationship('PatientCohort', back_populates='inclusion_criteria')
    case_report: Mapped["CaseReport"] = relationship('CaseReport', back_populates='inclusion_criteria')
    user: Mapped["User"] = relationship('User', back_populates='inclusion_criteria')

class CaseReportSymptom(Base):
    __tablename__ = 'case_reports_symptoms'
    
    # Properties
    id: Mapped[int] = mapped_column(primary_key=True)

    # Foreign keys
    case_report_id: Mapped[int] = mapped_column(ForeignKey('case_reports.id'))
    symptom_id: Mapped[int] = mapped_column(ForeignKey(Symptom.__tablename__ + '.id'))

class SubjectSymptom(Base):
    __tablename__ = 'subjects_symptoms'
    
    # Properties
    id: Mapped[int] = mapped_column(primary_key=True)

    # Foreign keys
    subject_id: Mapped[int] = mapped_column(ForeignKey('subjects.id'))
    symptom_id: Mapped[int] = mapped_column(ForeignKey(Symptom.__tablename__ + '.id'))

class Synonym(Base):
    __tablename__ = 'synonyms'

    # Properties
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String)
    
    # Foreign Keys
    symptom_id: Mapped[int] = mapped_column(ForeignKey(Symptom.__tablename__ + '.id'))

    # Relationships
    symptom: Mapped["Symptom"] = relationship('Symptom', back_populates='synonyms')

class MeshTerm(Base):
    __tablename__ = 'mesh_terms'

    # Properties
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String)

    # Foreign Keys
    symptom_id: Mapped[int] = mapped_column(ForeignKey(Symptom.__tablename__ + '.id'))

    # Relationships
    symptoms: Mapped["Symptom"] = relationship('Symptom', back_populates='mesh_terms')

class Domain(Base):
    __tablename__ = 'domains'
    
    # Properties
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String)
    description: Mapped[Optional[str]] = mapped_column(String)

    # Relationships
    symptoms: Mapped[List["Symptom"]] = relationship('Symptom', back_populates='domain')
    subdomains: Mapped[List["Subdomain"]] = relationship('Subdomain', back_populates='domain')
    group_level_map_files: Mapped[List["GroupLevelMapFile"]] = relationship('GroupLevelMapFile', back_populates='domain')

    def __repr__(self):
        return f"<Domain(id={self.id}, name='{self.name}')>"

class Subdomain(Base):
    __tablename__ = 'subdomains'
    
    # Properties
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String)
    description: Mapped[Optional[str]] = mapped_column(String)

    # Foreign keys
    domain_id: Mapped[int] = mapped_column(ForeignKey('domains.id'))

    # Relationships
    symptoms: Mapped[List["Symptom"]] = relationship('Symptom', back_populates='subdomain')
    domain: Mapped["Domain"] = relationship('Domain', back_populates='subdomains')
    group_level_map_files: Mapped[List["GroupLevelMapFile"]] = relationship('GroupLevelMapFile', back_populates='subdomain')

    def __repr__(self):
        return f"<Subdomain(id={self.id}, name='{self.name}')>"

class ResearchPaper(Base):
    __tablename__ = 'research_papers'

    # Properties
    id: Mapped[int] = mapped_column(primary_key=True)
    doi: Mapped[Optional[str]] = mapped_column(String)
    pubmed_id: Mapped[Optional[int]] = mapped_column(Integer)
    other_citation: Mapped[Optional[str]] = mapped_column(String)
    title: Mapped[Optional[str]] = mapped_column(String)
    year: Mapped[Optional[int]] = mapped_column(Integer)
    abstract: Mapped[Optional[str]] = mapped_column(String)
    nickname: Mapped[Optional[str]] = mapped_column(String)
    comments: Mapped[Optional[str]] = mapped_column(String)

    # Foreign keys
    first_author_id: Mapped[int] = mapped_column(ForeignKey('authors.id'))

    # Relationships
    first_author: Mapped["Author"] = relationship('Author', back_populates='first_authored_papers')
    authors: Mapped[List["Author"]] = relationship('Author', secondary='research_papers_authors', back_populates='co_authored_papers')

    group_level_map_files: Mapped[List["GroupLevelMapFile"]] = relationship('GroupLevelMapFile', back_populates='research_paper')
    symptoms: Mapped[List["Symptom"]] = relationship('Symptom', secondary='research_papers_symptoms', back_populates='research_papers')
    tags: Mapped[List["Tag"]] = relationship('Tag', back_populates='research_paper')
    subjects: Mapped[List["Subject"]] = relationship('Subject', secondary='subjects_research_papers', back_populates='research_papers')

class ResearchPaperAuthor(BaseNoUser):
    __tablename__ = 'research_papers_authors'
    
    id: Mapped[int] = mapped_column(primary_key=True)
    research_paper_id: Mapped[int] = mapped_column(ForeignKey('research_papers.id'))
    author_id: Mapped[int] = mapped_column(ForeignKey('authors.id'))

class Author(Base):
    __tablename__ = 'authors'
    
    # Properties
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String)
    email: Mapped[Optional[str]] = mapped_column(String)
    institution: Mapped[Optional[str]] = mapped_column(String)

    # Relationships
    first_authored_papers: Mapped[List["ResearchPaper"]] = relationship('ResearchPaper', back_populates='first_author')
    co_authored_papers: Mapped[List["ResearchPaper"]] = relationship('ResearchPaper', secondary='research_papers_authors', back_populates='authors')

class ResearchPaperSymptom(BaseNoUser):
    __tablename__ = 'research_papers_symptoms'
    
    id: Mapped[int] = mapped_column(primary_key=True)

    # Foreign keys
    research_paper_id: Mapped[int] = mapped_column(ForeignKey('research_papers.id'))
    symptom_id: Mapped[int] = mapped_column(ForeignKey(Symptom.__tablename__ + '.id'))

class ClinicalMeasure(Base):
    __tablename__ = 'clinical_measures'
    
    # Properties
    id: Mapped[int] = mapped_column(primary_key=True)
    metric_name: Mapped[str] = mapped_column(String)
    value: Mapped[Union[int, float]] = mapped_column(Float)
    unit: Mapped[Optional[str]] = mapped_column(String)
    timepoint: Mapped[Optional[int]] = mapped_column(Integer)

    # Foreign keys
    subject_id: Mapped[int] = mapped_column(ForeignKey('subjects.id'))

    # Relationships
    subject: Mapped["Subject"] = relationship('Subject', back_populates='clinical_measures')

class Tag(Base):
    __tablename__ = 'tags'
    
    # Properties
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String)
    description: Mapped[Optional[str]] = mapped_column(String)

    # Foreign keys
    research_paper_id: Mapped[int] = mapped_column(ForeignKey('research_papers.id'))

    # Relationships
    research_paper: Mapped["ResearchPaper"] = relationship('ResearchPaper', back_populates='tags')

class UsageLog(Base):
    __tablename__ = "usage_logs"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    page_name: Mapped[str] = mapped_column(String(255), nullable=False)
    insert_date: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("accounts_customuser.id"), nullable=False)

    user: Mapped["User"] = relationship("User", back_populates="usage_logs")