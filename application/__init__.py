"""Composition root shared by current UI and a future HTTP backend; import-safe."""
from dataclasses import dataclass
from .materials import MaterialService
from .knowledge import KnowledgeService
from .assessments import AssessmentService
from .documents import DocumentService
from .students import StudentService
from .assistant import AssistantService
from .overview import ActivityService,DashboardService

@dataclass(frozen=True)
class ApplicationServices:
    materials: MaterialService
    knowledge: KnowledgeService
    assessments: AssessmentService
    documents: DocumentService
    students: StudentService
    assistant: AssistantService
    activity: ActivityService
    dashboard: DashboardService
    def initialize_local_storage(self):
        """Explicit legacy app startup, never invoked by construction/import."""
        from .errors import call
        return call(self.materials._repo().init_db)


def create_application_services(*, materials=None, knowledge=None, assessments=None,
                                documents=None, students=None, assistant=None,
                                activity=None, dashboard=None, context=None,
                                security_repository=None, collection_factory=None):
    """Scoped/default-deny unless explicit development legacy context is supplied."""
    materials=materials if materials is not None else MaterialService()
    activity=activity if activity is not None else ActivityService()
    documents=documents if documents is not None else DocumentService()
    base = ApplicationServices(materials,knowledge if knowledge is not None else KnowledgeService(),
        assessments if assessments is not None else AssessmentService(),
        documents,
        students if students is not None else StudentService(),
        assistant if assistant is not None else AssistantService(),activity,
        dashboard if dashboard is not None else DashboardService(materials,activity,documents=documents))

    from security.models import LegacyDevelopmentContext
    if isinstance(context,LegacyDevelopmentContext):return base
    if context is not None:
        from security.policy import AccessDeniedError
        raise AccessDeniedError() # scoped identity is supplied per operation, not stored globally
    from .scoped import scoped_services
    return scoped_services(base,security_repository,collection_factory)
